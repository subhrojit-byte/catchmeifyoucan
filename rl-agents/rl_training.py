"""Offline-testable training runner for the existing REST environment.

The runner uses the existing client endpoints. Investigator labels and flag
correctness are read only after an episode through the evaluator reader and
are never included in state keys, action choices, or live observations.

Fraudster terminal rewards are +5 for financial success and a separate +5 for
evading detection through the turn limit, or -10 when correctly detected.
Investigator reward uses evaluator-only labels after the terminal transition.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from api_client import CatchMeIfYouCanApiClient
from fraudster_bot import FraudsterBot
from ground_truth import EvaluatorDataError, PostgresGroundTruthReader
from q_learning import QLearningAgent, checkpoint_compatibility
from rl_policies import RLFraudsterPolicy, RLInvestigatorPolicy
from run_episode import build_agent_observation
from state_abstraction import (
    fraudster_state_key,
    legal_fraudster_actions,
)


FRAUDSTER_OBJECTIVE_REWARD = 5.0
FRAUDSTER_EVASION_REWARD = 5.0
FRAUDSTER_DETECTION_PENALTY = -10.0
INVESTIGATOR_TRUE_POSITIVE_REWARD = 1.0
INVESTIGATOR_FALSE_POSITIVE_PENALTY = -1.0
INVESTIGATOR_FALSE_NEGATIVE_PENALTY = -1.0
INVESTIGATOR_TRUE_NEGATIVE_REWARD = 0.0
FRAUDSTER_ACTION_TYPES = (
    "DIRECT_TRANSFER", "ROUTE_TRANSFER", "SPLIT_TRANSFER", "WAIT",
)


@dataclass(frozen=True)
class Transition:
    state: Any
    action: Any
    next_state: Any
    next_actions: tuple[Any, ...]


def apply_delayed_terminal_reward(
    learner: QLearningAgent,
    transitions: list[Transition],
    reward: float,
) -> None:
    """Apply discounted terminal credit once to every episode transition.

    The terminal reward is assigned to the final transition at full value and
    to each preceding transition as ``reward * gamma ** distance``.  Each
    update is terminal, so Q-learning does not bootstrap from a later update
    and the terminal outcome is not counted twice.  The learner's configured
    discount factor is the convention used unless an explicit value is added
    in a future caller.
    """
    discount = learner.discount_factor
    for index, transition in enumerate(transitions):
        distance = len(transitions) - 1 - index
        learner.update(
            transition.state,
            transition.action,
            reward * (discount ** distance),
            None,
            (),
            done=True,
        )


def investigator_terminal_reward(candidates: list[Any]) -> float:
    """Reward detections of shell companies on persisted fraudster transfer paths."""
    reward = 0.0
    for candidate in candidates:
        shell = getattr(candidate, "shell_company", None)
        flagged = getattr(candidate, "flagged", None)
        path_involved = getattr(candidate, "fraud_path_involved", None)
        if (not isinstance(shell, bool) or not isinstance(flagged, bool)
                or not isinstance(path_involved, bool)):
            raise EvaluatorDataError(
                "Evaluator candidates require boolean shell, decision, and fraud-path fields."
            )
        path_shell = shell and path_involved
        if path_shell and flagged:
            reward += INVESTIGATOR_TRUE_POSITIVE_REWARD
        elif path_shell and not flagged:
            reward += INVESTIGATOR_FALSE_NEGATIVE_PENALTY
        elif flagged:
            reward += INVESTIGATOR_FALSE_POSITIVE_PENALTY
        else:
            reward += INVESTIGATOR_TRUE_NEGATIVE_REWARD
    return reward


def _legal_flag_candidate_ids(investigator: Any, state: dict[str, Any]) -> set[int]:
    """Capture exactly the validated legal flag choices before one decision."""
    legal_actions = getattr(investigator, "legal_actions", None)
    if not callable(legal_actions):
        raise EvaluatorDataError(
            "Investigator training requires legal actions to capture decision-time flag candidates."
        )
    actions = legal_actions(state)
    if not isinstance(actions, list):
        raise EvaluatorDataError("Investigator legal actions are malformed.")
    company_ids: set[int] = set()
    for action in actions:
        if not isinstance(action, dict):
            raise EvaluatorDataError("Investigator legal actions are malformed.")
        if action.get("action_type") != "FLAG_COMPANY":
            continue
        company_id = action.get("company_id")
        if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
            raise EvaluatorDataError("A legal flag candidate has an invalid company ID.")
        company_ids.add(company_id)
    return company_ids


def _has_authorized_shell_transfer(state: dict[str, Any], shell_ids: set[int]) -> bool:
    """Check public, scenario-scoped transaction history for an executed shell edge."""
    scenario_id = state.get("id")
    for transaction in state.get("transactionHistory") or []:
        if (not isinstance(transaction, dict)
                or transaction.get("scenarioId") != scenario_id
                or transaction.get("origin") != "FRAUDSTER_ACTION"):
            continue
        endpoints = {
            (transaction.get("sourceCompany") or {}).get("id"),
            (transaction.get("destinationCompany") or {}).get("id"),
        }
        if endpoints & shell_ids:
            return True
    return False


def _legal_shell_route_action(state: dict[str, Any], shell_ids: set[int]) -> dict[str, Any]:
    """Choose a shell route from the already validated legal action population."""
    for action in legal_fraudster_actions(state):
        if action.get("action_type") != "ROUTE_TRANSFER":
            continue
        targets = action.get("targets")
        if (isinstance(targets, list) and targets
                and isinstance(targets[0], dict)
                and targets[0].get("destinationCompanyId") in shell_ids):
            return action
    raise EvaluatorDataError(
        "Shell-path training requires an authorized shell that is currently a legal route destination."
    )


def _validate_discovered_candidate_decisions(
    scenario_id: int,
    candidate_ids: set[int],
    candidates: Any,
) -> list[Any]:
    if not isinstance(candidates, list):
        raise EvaluatorDataError("Evaluator discovered-candidate data is malformed.")
    expected = {(scenario_id, company_id) for company_id in candidate_ids}
    found: set[tuple[int, int]] = set()
    path_shell_labels: set[bool] = set()
    for candidate in candidates:
        candidate_scenario_id = getattr(candidate, "scenario_id", None)
        company_id = getattr(candidate, "company_id", None)
        shell_company = getattr(candidate, "shell_company", None)
        flagged = getattr(candidate, "flagged", None)
        fraud_path_involved = getattr(candidate, "fraud_path_involved", None)
        if (isinstance(candidate_scenario_id, bool)
                or not isinstance(candidate_scenario_id, int)
                or isinstance(company_id, bool) or not isinstance(company_id, int)
                or candidate_scenario_id != scenario_id or company_id <= 0
                or not isinstance(shell_company, bool) or not isinstance(flagged, bool)
                or not isinstance(fraud_path_involved, bool)):
            raise EvaluatorDataError("Evaluator discovered-candidate data is malformed.")
        pair = (candidate_scenario_id, company_id)
        if pair not in expected or pair in found:
            raise EvaluatorDataError(
                "Evaluator discovered-candidate data does not match captured legal flag choices."
            )
        found.add(pair)
        path_shell_labels.add(shell_company and fraud_path_involved)
    if found != expected:
        raise EvaluatorDataError(
            "Evaluator discovered-candidate data is incomplete for captured legal flag choices."
        )
    if path_shell_labels != {False, True}:
        raise EvaluatorDataError(
            "Investigator training skipped: discovered legal flag candidates must include "
            "at least one path-involved shell and one non-positive candidate; "
            "no investigator updates were applied."
        )
    return candidates


def fraudster_terminal_reward(
    state: dict[str, Any],
    transitions: list[Transition],
    *,
    correctly_flagged: bool,
) -> float:
    """Assign terminal reward only when evaluator evidence matches terminal status."""
    if not isinstance(correctly_flagged, bool):
        raise EvaluatorDataError("Terminal correct-flag evidence must be boolean.")

    final_action_type = (
        transitions[-1].action.get("action_type") if transitions else None
    )
    status = state.get("status")
    if status == "COMPLETED":
        if not correctly_flagged or final_action_type != "FLAG_COMPANY":
            raise EvaluatorDataError(
                "COMPLETED scenario lacks validated correct-flag terminal evidence."
            )
        return FRAUDSTER_DETECTION_PENALTY
    if status != "MAX_TURNS_REACHED":
        raise EvaluatorDataError(
            f"Unsupported terminal outcome for fraudster reward: {status!r}."
        )
    if correctly_flagged:
        raise EvaluatorDataError(
            "MAX_TURNS_REACHED conflicts with persisted correct-flag evidence."
        )
    evasion = FRAUDSTER_EVASION_REWARD
    objective = (FRAUDSTER_OBJECTIVE_REWARD
                 if state.get("financialObjectiveAchieved") is True else 0.0)
    return evasion + objective


class RLTrainingRunner:
    def __init__(self, client: Any, ground_truth_reader: Any):
        self.client = client
        self.ground_truth_reader = ground_truth_reader

    def run_episode(
        self,
        *,
        source_company_id: int,
        target_company_id: int,
        amount: str,
        fraudster: Any,
        investigator: RLInvestigatorPolicy,
        max_actions: int = 20,
        train_fraudster: bool = True,
        private_shell_knowledge_provider: Any | None = None,
        existing_scenario_id: int | None = None,
        ensure_shell_path: bool = False,
    ) -> dict[str, Any]:
        if train_fraudster and not callable(private_shell_knowledge_provider):
            raise EvaluatorDataError(
                "Fraudster training requires an authorized private shell-knowledge provider."
            )
        if ensure_shell_path and not callable(private_shell_knowledge_provider):
            raise EvaluatorDataError(
                "Shell-path training requires an authorized private shell-knowledge provider."
            )
        if existing_scenario_id is None:
            created = self.client.create_scenario(
                source_company_id=source_company_id,
                target_company_id=target_company_id,
                amount=amount,
            )
            scenario_id = created["id"]
        else:
            if (isinstance(existing_scenario_id, bool)
                    or not isinstance(existing_scenario_id, int)
                    or existing_scenario_id <= 0):
                raise ValueError("existing_scenario_id must be a positive integer.")
            scenario_id = existing_scenario_id
        state = self.client.get_scenario(scenario_id)
        fraud_transitions: list[Transition] = []
        investigator_transitions: list[Transition] = []
        investigator_candidate_ids: set[int] = set()
        fraudster_action_counts = {action_type: 0 for action_type in FRAUDSTER_ACTION_TYPES}
        shell_path_confirmed = False
        for _ in range(max_actions):
            if state.get("status") != "ACTIVE":
                break
            before = state
            if state.get("turn") == "FRAUDSTER":
                private_ids = ()
                if train_fraudster or ensure_shell_path:
                    private_ids = private_shell_knowledge_provider(scenario_id)
                before = build_agent_observation(
                    self.client, scenario_id, state, role="FRAUDSTER",
                    private_shell_company_ids=private_ids,
                )
                action = fraudster.choose_action(before)
                if ensure_shell_path and not shell_path_confirmed:
                    shell_ids = set(private_ids)
                    shell_path_confirmed = _has_authorized_shell_transfer(before, shell_ids)
                    if not shell_path_confirmed:
                        action = _legal_shell_route_action(before, shell_ids)
                created_action = self.client.create_fraudster_action(
                    scenario_id=scenario_id,
                    action_type=action["action_type"],
                    source_position_id=action["source_position_id"],
                    targets=action.get("targets"),
                )
                self.client.execute_fraudster_action(created_action["id"])
                if action.get("action_type") in fraudster_action_counts:
                    fraudster_action_counts[action["action_type"]] += 1
                state = self.client.get_scenario(scenario_id)
                next_observation = build_agent_observation(
                    self.client, scenario_id, state, role="FRAUDSTER",
                    private_shell_company_ids=(
                        private_shell_knowledge_provider(scenario_id)
                        if train_fraudster or ensure_shell_path else ()
                    ),
                )
                if ensure_shell_path and not shell_path_confirmed:
                    shell_path_confirmed = _has_authorized_shell_transfer(
                        next_observation, set(private_ids)
                    )
                    if not shell_path_confirmed:
                        raise EvaluatorDataError(
                            "Executed fraudster action did not produce a persisted authorized-shell transfer."
                        )
                next_actions = tuple(legal_fraudster_actions(next_observation))
                if train_fraudster:
                    fraud_transitions.append(Transition(
                        fraudster_state_key(before), action,
                        fraudster_state_key(next_observation), next_actions
                    ))
            elif state.get("turn") == "INVESTIGATOR":
                before = build_agent_observation(
                    self.client, scenario_id, state, role="INVESTIGATOR"
                )
                # Capture the legal FLAG_COMPANY population before the action,
                # matching evaluate._record_candidate_opportunity. A candidate
                # discovered by this action is captured only at a later decision.
                investigator_candidate_ids.update(
                    _legal_flag_candidate_ids(investigator, before)
                )
                before_key = investigator.state_key(before)
                action = investigator.choose_action(before)
                learning_action = getattr(investigator, "learning_action", None)
                learned_action = (
                    learning_action(before, action) if callable(learning_action) else action
                )
                response = self.client.submit_investigator_action(
                    scenario_id=scenario_id,
                    action_type=action["action_type"],
                    company_id=action.get("company_id"),
                    transaction_id=action.get("transaction_id"),
                )
                state = self.client.get_scenario(scenario_id)
                next_observation = build_agent_observation(
                    self.client, scenario_id, state, role="INVESTIGATOR"
                )
                sanitized = investigator.fallback.sanitize_action_response(
                    response,
                    scenario_id=scenario_id,
                    expected_transaction_id=action.get("transaction_id"),
                )
                investigator.mark_action_completed(action, sanitized)
                learning_actions = getattr(investigator, "learning_actions", None)
                next_actions = tuple(
                    learning_actions(next_observation) if callable(learning_actions)
                    else investigator.legal_actions(next_observation)
                )
                investigator_transitions.append(Transition(
                    before_key,
                    learned_action,
                    investigator.state_key(next_observation),
                    next_actions,
                ))
            else:
                raise RuntimeError(f"Unknown backend turn: {state.get('turn')!r}")
        if state.get("status") not in {"COMPLETED", "MAX_TURNS_REACHED"}:
            raise EvaluatorDataError("RL training requires a completed episode for delayed rewards.")
        if ensure_shell_path and not shell_path_confirmed:
            raise EvaluatorDataError(
                "Shell-path training reached terminal status without a confirmed authorized-shell transfer."
            )

        # Both evaluator lookups happen only after the live API confirms a
        # terminal state. Validate the terminal reason before updating either
        # learner, so an inconsistent legacy status cannot earn detection credit.
        fraud_reward = None
        if train_fraudster:
            correct_flag_outcomes = self.ground_truth_reader.read_correct_flag_outcomes(
                [scenario_id]
            )
            if not isinstance(correct_flag_outcomes, dict) or scenario_id not in correct_flag_outcomes:
                raise EvaluatorDataError(
                    "Evaluator returned no correct-flag evidence for the completed scenario."
                )
            fraud_reward = fraudster_terminal_reward(
                state,
                investigator_transitions,
                correctly_flagged=correct_flag_outcomes[scenario_id],
            )
        read_discovered_candidates = getattr(
            self.ground_truth_reader, "read_discovered_candidates", None
        )
        if not callable(read_discovered_candidates):
            raise EvaluatorDataError(
                "Evaluator reader does not support terminal discovered-candidate labels."
            )
        candidates = read_discovered_candidates(
            [scenario_id], {scenario_id: investigator_candidate_ids}
        )
        candidates = _validate_discovered_candidate_decisions(
            scenario_id, investigator_candidate_ids, candidates
        )
        investigator_reward = investigator_terminal_reward(candidates)
        path_positive_candidate_count = sum(
            candidate.shell_company and candidate.fraud_path_involved
            for candidate in candidates
        )
        path_negative_candidate_count = len(candidates) - path_positive_candidate_count
        if train_fraudster:
            apply_delayed_terminal_reward(fraudster.learner, fraud_transitions, fraud_reward)
        apply_delayed_terminal_reward(
            investigator.learner, investigator_transitions, investigator_reward
        )
        return {
            "scenario_id": scenario_id,
            "episode_completed": True,
            "actions_attempted": (
                sum(fraudster_action_counts.values()) + len(investigator_transitions)
            ),
            "financial_objective_achieved": state.get("financialObjectiveAchieved") is True,
            "terminal_outcome": state.get("status"),
            "fraudster_reward": fraud_reward,
            "investigator_training_reward": investigator_reward,
            "fraudster_action_type_counts": dict(fraudster_action_counts),
            "shell_path_transfer_confirmed": shell_path_confirmed,
            "path_positive_candidate_count": path_positive_candidate_count,
            "path_negative_candidate_count": path_negative_candidate_count,
            "transition_counts": {
                "fraudster": len(fraud_transitions),
                "investigator": len(investigator_transitions),
            },
        }


def train_existing_scenario(
    client: Any,
    ground_truth_reader: Any,
    *,
    scenario_id: int,
    max_actions: int,
    seed: int,
    fraudster_checkpoint: str | Path | None,
    investigator_checkpoint: str | Path | None,
    fraudster_output_checkpoint: str | Path,
    investigator_output_checkpoint: str | Path,
    private_shell_knowledge_provider: Any,
    initialize_fresh: bool = False,
    ensure_shell_path: bool = False,
) -> dict[str, Any]:
    """Train one paired episode inside the app-authorized existing scenario."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    max_actions = _positive_int(max_actions, "max_actions")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if not callable(private_shell_knowledge_provider):
        raise EvaluatorDataError(
            "Fraudster training requires an authorized private shell-knowledge provider."
        )

    if initialize_fresh:
        if fraudster_checkpoint is not None or investigator_checkpoint is not None:
            raise ValueError("Fresh training must not load input checkpoints.")
    elif fraudster_checkpoint is None or investigator_checkpoint is None:
        raise ValueError("Resume training requires both role-compatible input checkpoints.")
    fraudster_output = Path(fraudster_output_checkpoint)
    investigator_output = Path(investigator_output_checkpoint)
    if fraudster_output.resolve() == investigator_output.resolve():
        raise ValueError("fraudster and investigator output checkpoints must be different.")
    for output in (fraudster_output, investigator_output):
        if output.exists():
            raise FileExistsError(f"Training output checkpoint already exists: {output}")
        if not output.parent.is_dir():
            raise ValueError(f"Training checkpoint directory does not exist: {output.parent}")

    fraudster_learner = (
        QLearningAgent.for_role("fraudster", seed=seed)
        if initialize_fresh
        else _load_resume_learner(Path(fraudster_checkpoint), "fraudster")
    )
    investigator_learner = (
        QLearningAgent.for_role("investigator", seed=seed + 1)
        if initialize_fresh
        else _load_resume_learner(Path(investigator_checkpoint), "investigator")
    )
    fraudster_learner.reseed(seed)
    investigator_learner.reseed(seed + 1)
    initial_state = client.get_scenario(scenario_id)
    source_company_id = (initial_state.get("sourceCompany") or {}).get("id")
    target_company_id = (initial_state.get("targetCompany") or {}).get("id")
    amount = initial_state.get("targetAmount")
    provenance = {
        "episodes": 1,
        "seed": seed,
        "max_actions": max_actions,
        "source_company_id": source_company_id,
        "target_company_id": target_company_id,
        "amount": amount,
        "training_mode": (
            "application_managed_fresh_existing_scenario"
            if initialize_fresh else "application_managed_existing_scenario"
        ),
        "scenario_id": scenario_id,
        "shell_path_coverage_target": 1.0 if ensure_shell_path else 0.0,
    }
    fraudster_learner.metadata["training_provenance"] = dict(provenance)
    investigator_learner.metadata["training_provenance"] = dict(provenance)
    result = RLTrainingRunner(client, ground_truth_reader).run_episode(
        source_company_id=source_company_id,
        target_company_id=target_company_id,
        amount=str(amount),
        fraudster=RLFraudsterPolicy(fraudster_learner),
        investigator=RLInvestigatorPolicy(investigator_learner),
        max_actions=max_actions,
        train_fraudster=True,
        private_shell_knowledge_provider=private_shell_knowledge_provider,
        existing_scenario_id=scenario_id,
        ensure_shell_path=ensure_shell_path,
    )
    if result.get("episode_completed") is not True:
        raise EvaluatorDataError("Training episode did not complete; checkpoints were not saved.")
    if result.get("transition_counts", {}).get("fraudster", 0) <= 0:
        raise EvaluatorDataError(
            "No fraudster action transition completed; training checkpoints were not saved."
        )

    provenance["episode_results"] = [{
        "scenario_id": scenario_id,
        "fraudster_action_type_counts": result["fraudster_action_type_counts"],
        "shell_path_transfer_confirmed": result["shell_path_transfer_confirmed"],
        "path_positive_candidate_count": result["path_positive_candidate_count"],
        "path_negative_candidate_count": result["path_negative_candidate_count"],
    }]
    fraudster_learner.metadata["training_provenance"] = dict(provenance)
    investigator_learner.metadata["training_provenance"] = dict(provenance)

    # Outputs are run-specific fresh paths. Save only after terminal rewards
    # have been applied successfully; existing input checkpoints are untouched.
    saved_outputs: list[Path] = []
    try:
        fraudster_learner.save_new(fraudster_output)
        saved_outputs.append(fraudster_output)
        investigator_learner.save_new(investigator_output)
        saved_outputs.append(investigator_output)
    except Exception:
        for output in saved_outputs:
            output.unlink(missing_ok=True)
        raise
    return {
        **result,
        "fraudster_training_steps": fraudster_learner.training_steps,
        "investigator_training_steps": investigator_learner.training_steps,
        "fraudster_checkpoint": str(fraudster_output),
        "investigator_checkpoint": str(investigator_output),
    }


def train_existing_investigator_scenario(
    client: Any, ground_truth_reader: Any, *, scenario_id: int, max_actions: int,
    seed: int, investigator_checkpoint: str | Path | None,
    investigator_output_checkpoint: str | Path,
    private_shell_knowledge_provider: Any | None = None,
    initialize_fresh: bool = False,
) -> dict[str, Any]:
    """Train only the investigator on one app-authorized existing scenario."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    max_actions = _positive_int(max_actions, "max_actions")
    if initialize_fresh != (investigator_checkpoint is None):
        raise ValueError("Fresh investigator training takes no input checkpoint; resume requires one.")
    output = Path(investigator_output_checkpoint)
    if output.exists():
        raise FileExistsError(f"Training output checkpoint already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"Training checkpoint directory does not exist: {output.parent}")
    if initialize_fresh:
        learner = QLearningAgent.for_role("investigator", seed=seed)
    else:
        learner = _load_resume_learner(Path(investigator_checkpoint), "investigator")
        provenance = learner.metadata.get("training_provenance", {})
        if (learner.training_steps <= 0 or not isinstance(provenance, dict)
                or provenance.get("training_mode") not in {
                    "application_managed_investigator_fresh_existing_scenario",
                    "application_managed_investigator_resume_existing_scenario",
                }):
            raise ValueError("Investigator resume checkpoint was not produced by a successful managed investigator run.")
    learner.reseed(seed)
    state = client.get_scenario(scenario_id)
    source_company_id = (state.get("sourceCompany") or {}).get("id")
    target_company_id = (state.get("targetCompany") or {}).get("id")
    amount = state.get("targetAmount")
    learner.metadata["training_provenance"] = {
        "episodes": 1, "seed": seed, "max_actions": max_actions,
        "source_company_id": source_company_id, "target_company_id": target_company_id,
        "amount": amount, "scenario_id": scenario_id,
        "training_mode": ("application_managed_investigator_fresh_existing_scenario"
                          if initialize_fresh else "application_managed_investigator_resume_existing_scenario"),
        "shell_path_coverage_target": 1.0,
    }
    result = RLTrainingRunner(client, ground_truth_reader).run_episode(
        source_company_id=source_company_id, target_company_id=target_company_id,
        amount=str(amount), fraudster=FraudsterBot(),
        investigator=RLInvestigatorPolicy(learner), max_actions=max_actions,
        train_fraudster=False, existing_scenario_id=scenario_id,
        private_shell_knowledge_provider=private_shell_knowledge_provider,
        ensure_shell_path=True,
    )
    if result.get("episode_completed") is not True:
        raise EvaluatorDataError("Training episode did not complete; checkpoint was not saved.")
    if result.get("transition_counts", {}).get("investigator", 0) <= 0 or learner.training_steps <= 0:
        raise EvaluatorDataError("No investigator learning updates completed; checkpoint was not saved.")
    learner.metadata["training_provenance"]["episode_results"] = [{
        "scenario_id": scenario_id,
        "fraudster_action_type_counts": result["fraudster_action_type_counts"],
        "shell_path_transfer_confirmed": result["shell_path_transfer_confirmed"],
        "path_positive_candidate_count": result["path_positive_candidate_count"],
        "path_negative_candidate_count": result["path_negative_candidate_count"],
    }]
    learner.save_new(output)
    return {**result, "investigator_training_steps": learner.training_steps,
            "investigator_checkpoint": str(output)}


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer.") from None
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _positive_amount(value: str) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("amount must be a positive finite number.") from None
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("amount must be a positive finite number.")
    return str(value)


def _validate_training_paths(
    fraudster_checkpoint: str | Path | None,
    investigator_checkpoint: str | Path,
    *,
    overwrite_checkpoints: bool,
    require_existing: bool = False,
) -> tuple[Path | None, Path]:
    fraudster_path = Path(fraudster_checkpoint) if fraudster_checkpoint is not None else None
    investigator_path = Path(investigator_checkpoint)
    if fraudster_path is not None and fraudster_path.resolve() == investigator_path.resolve():
        raise ValueError("fraudster and investigator checkpoint paths must be different.")
    paths = ([fraudster_path] if fraudster_path is not None else []) + [investigator_path]
    for path in paths:
        if require_existing and not path.is_file():
            raise FileNotFoundError(f"Resume checkpoint does not exist: {path}")
        if path.exists() and not overwrite_checkpoints:
            raise FileExistsError(
                f"Checkpoint already exists: {path}. "
                "Pass --overwrite-checkpoints to replace it explicitly."
            )
        if not path.parent.is_dir():
            raise ValueError(f"Checkpoint directory does not exist: {path.parent}")
    return fraudster_path, investigator_path


def _load_resume_learner(path: Path, role: str) -> QLearningAgent:
    try:
        learner = QLearningAgent.load(path)
    except ValueError as error:
        raise ValueError(f"Unable to load {role} resume checkpoint {path}: {error}") from error
    expected = checkpoint_compatibility(role)
    if learner.compatibility != expected:
        if learner.compatibility is None:
            raise ValueError(
                f"{role} resume checkpoint {path} has no compatibility metadata."
            )
        raise ValueError(
            f"{role} resume checkpoint {path} is incompatible with the current "
            "role or state/action schema."
        )
    return learner


def train(
    client: Any,
    ground_truth_reader: Any,
    *,
    episodes: int,
    source_company_id: int,
    target_company_id: int,
    amount: str,
    max_actions: int,
    seed: int,
    fraudster_checkpoint: str | Path | None,
    investigator_checkpoint: str | Path,
    overwrite_checkpoints: bool = False,
    resume: bool = False,
    investigator_only: bool = False,
    private_shell_knowledge_provider: Any | None = None,
) -> dict[str, Any]:
    """Train selected policies and save checkpoints only after full success."""
    episodes = _positive_int(episodes, "episodes")
    max_actions = _positive_int(max_actions, "max_actions")
    if isinstance(source_company_id, bool) or not isinstance(source_company_id, int) or source_company_id <= 0:
        raise ValueError("source_company_id must be a positive integer.")
    if isinstance(target_company_id, bool) or not isinstance(target_company_id, int) or target_company_id <= 0:
        raise ValueError("target_company_id must be a positive integer.")
    if source_company_id == target_company_id:
        raise ValueError("source_company_id and target_company_id must be different.")
    amount = _positive_amount(amount)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if investigator_only and fraudster_checkpoint is not None:
        raise ValueError("Investigator-only training must not be given a fraudster checkpoint path.")
    if not investigator_only and fraudster_checkpoint is None:
        raise ValueError("Paired training requires a fraudster checkpoint path.")
    if not investigator_only and not callable(private_shell_knowledge_provider):
        raise ValueError(
            "Paired training requires authorized private shell context for every fraudster observation."
        )
    if resume and not overwrite_checkpoints:
        raise ValueError(
            "Resume training updates the supplied checkpoints; pass "
            "overwrite_checkpoints=True explicitly."
        )
    fraudster_path, investigator_path = _validate_training_paths(
        fraudster_checkpoint,
        investigator_checkpoint,
        overwrite_checkpoints=overwrite_checkpoints,
        require_existing=resume,
    )

    if resume:
        fraudster_learner = (
            None if investigator_only else _load_resume_learner(fraudster_path, "fraudster")
        )
        investigator_learner = _load_resume_learner(investigator_path, "investigator")
    else:
        fraudster_learner = (
            None if investigator_only else QLearningAgent.for_role("fraudster", seed=seed)
        )
        investigator_learner = QLearningAgent.for_role("investigator", seed=seed + 1)
    training_provenance = {
        "episodes": episodes,
        "seed": seed,
        "max_actions": max_actions,
        "source_company_id": source_company_id,
        "target_company_id": target_company_id,
        "amount": amount,
        "training_mode": "investigator_only" if investigator_only else "paired",
        "shell_path_coverage_target": 0.0 if investigator_only else 1.0,
    }
    if investigator_only:
        training_provenance["fraudster_opponent"] = "FraudsterBot (non-RL baseline)"
    else:
        fraudster_learner.metadata["training_provenance"] = dict(training_provenance)
    investigator_learner.metadata["training_provenance"] = dict(training_provenance)
    fraudster = FraudsterBot() if investigator_only else RLFraudsterPolicy(fraudster_learner)
    runner = RLTrainingRunner(client, ground_truth_reader)
    episode_results: list[dict[str, Any]] = []

    for episode_number in range(1, episodes + 1):
        # Investigator evidence is scenario-scoped. Reuse the learner, but
        # start each episode with a fresh policy memory and fallback bot.
        investigator = RLInvestigatorPolicy(investigator_learner)
        result = runner.run_episode(
            source_company_id=source_company_id,
            target_company_id=target_company_id,
            amount=amount,
            fraudster=fraudster,
            investigator=investigator,
            max_actions=max_actions,
            train_fraudster=not investigator_only,
            private_shell_knowledge_provider=private_shell_knowledge_provider,
            ensure_shell_path=not investigator_only,
        )
        if result.get("episode_completed") is not True:
            raise EvaluatorDataError(
                f"Episode {episode_number} did not complete; checkpoints were not saved."
            )
        episode_results.append(result)
        training_provenance.setdefault("episode_results", []).append({
            "scenario_id": result["scenario_id"],
            "fraudster_action_type_counts": result["fraudster_action_type_counts"],
            "shell_path_transfer_confirmed": result["shell_path_transfer_confirmed"],
            "path_positive_candidate_count": result["path_positive_candidate_count"],
            "path_negative_candidate_count": result["path_negative_candidate_count"],
        })
        print(
            f"Episode {episode_number}/{episodes}: "
            f"scenario={result.get('scenario_id')}, "
            f"outcome={result.get('terminal_outcome')}, "
            f"objective={result.get('financial_objective_achieved')}, "
            f"fraudster_reward={result.get('fraudster_reward')}, "
            f"investigator_reward={result.get('investigator_training_reward')}"
        )

    # Checkpoint writes are intentionally after every required episode succeeds.
    if fraudster_learner is not None:
        fraudster_learner.metadata["training_provenance"] = dict(training_provenance)
        fraudster_learner.save(fraudster_path)
    investigator_learner.metadata["training_provenance"] = dict(training_provenance)
    investigator_learner.save(investigator_path)
    objective_successes = sum(
        result.get("financial_objective_achieved") is True
        for result in episode_results
    )
    return {
        "episode_count": len(episode_results),
        "completed_episode_count": len(episode_results),
        "objective_success_count": objective_successes,
        "objective_success_rate": objective_successes / len(episode_results),
        "fraudster_transition_count": sum(
            result["transition_counts"]["fraudster"] for result in episode_results
        ),
        "investigator_transition_count": sum(
            result["transition_counts"]["investigator"] for result in episode_results
        ),
        "fraudster_checkpoint": str(fraudster_path) if fraudster_path is not None else None,
        "investigator_checkpoint": str(investigator_path),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train CatchMeIfYouCan RL agent policies.")
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--source-company-id", type=int, required=True)
    parser.add_argument("--target-company-id", type=int, required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--max-actions", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fraudster-checkpoint")
    parser.add_argument("--investigator-checkpoint", required=True)
    parser.add_argument(
        "--investigator-only",
        action="store_true",
        help="Train only the investigator against the explicitly non-RL FraudsterBot baseline.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load existing role-specific checkpoints before training.",
    )
    parser.add_argument(
        "--overwrite-checkpoints",
        action="store_true",
        help="Explicitly allow replacement of existing checkpoint files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        # Perform all local validation before constructing a database reader or
        # making any possible API request.
        _positive_int(args.episodes, "episodes")
        _positive_int(args.max_actions, "max_actions")
        _positive_amount(args.amount)
        if args.resume and not args.overwrite_checkpoints:
            raise ValueError(
                "--resume requires --overwrite-checkpoints because the supplied "
                "checkpoints will be updated."
            )
        if args.investigator_only and args.fraudster_checkpoint is not None:
            raise ValueError("--investigator-only cannot be combined with --fraudster-checkpoint.")
        if not args.investigator_only and args.fraudster_checkpoint is None:
            raise ValueError("Paired training requires --fraudster-checkpoint.")
        if not args.investigator_only:
            raise ValueError(
                "The standalone CLI cannot authorize generated training scenarios for fraudster shell context; "
                "use --investigator-only or a trusted in-process trainer integration."
            )
        _validate_training_paths(
            args.fraudster_checkpoint,
            args.investigator_checkpoint,
            overwrite_checkpoints=args.overwrite_checkpoints,
            require_existing=args.resume,
        )
        if args.source_company_id <= 0 or args.target_company_id <= 0:
            raise ValueError("source_company_id and target_company_id must be positive integers.")
        if args.source_company_id == args.target_company_id:
            raise ValueError("source_company_id and target_company_id must be different.")
        reader = PostgresGroundTruthReader.from_environment()
        report = train(
            CatchMeIfYouCanApiClient(),
            reader,
            episodes=args.episodes,
            source_company_id=args.source_company_id,
            target_company_id=args.target_company_id,
            amount=args.amount,
            max_actions=args.max_actions,
            seed=args.seed,
            fraudster_checkpoint=args.fraudster_checkpoint,
            investigator_checkpoint=args.investigator_checkpoint,
            overwrite_checkpoints=args.overwrite_checkpoints,
            resume=args.resume,
            investigator_only=args.investigator_only,
        )
    except Exception as error:
        print(f"Training failed: {error}", file=sys.stderr)
        return 1
    print(
        "Training complete: "
        f"episodes={report['completed_episode_count']}, "
        f"objective_success_rate={report['objective_success_rate']:.3f}, "
        f"fraudster_transitions={report['fraudster_transition_count']}, "
        f"investigator_transitions={report['investigator_transition_count']}"
    )
    if report["fraudster_checkpoint"] is not None:
        print(f"Fraudster checkpoint: {report['fraudster_checkpoint']}")
    print(f"Investigator checkpoint: {report['investigator_checkpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

