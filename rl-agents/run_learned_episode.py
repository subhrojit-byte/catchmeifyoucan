"""Run the trained policies against one existing scenario via run_episode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from .api_client import CatchMeIfYouCanApiClient
    from .evaluate import build_policy_factory
    from .ground_truth import PostgresGroundTruthReader
    from .rl_training import train_existing_scenario, train_existing_investigator_scenario
    from .run_episode import AgentObservationError, run_episode
except ImportError:  # Supports ``python run_learned_episode.py``.
    from api_client import CatchMeIfYouCanApiClient
    from evaluate import build_policy_factory
    from ground_truth import PostgresGroundTruthReader
    from rl_training import train_existing_scenario, train_existing_investigator_scenario
    from run_episode import AgentObservationError, run_episode


EVENT_PREFIX = "CATCHME_AGENT_EVENT "
DEFAULT_FRAUDSTER_CHECKPOINT = Path(__file__).with_name(
    "fraudster-trained-lifecycle-20261024.json"
)
DEFAULT_INVESTIGATOR_CHECKPOINT = Path(__file__).with_name(
    "investigator-trained-lifecycle-20261024.json"
)


def _emit_event(event: dict[str, Any]) -> None:
    # Progress events are evaluator/UI-facing; strip policy-private data at all
    # nesting levels before serialization.
    def public(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: public(item) for key, item in value.items()
                if key != "privateShellCompanyIds"
                and not any(secret_word in key.lower()
                            for secret_word in ("credential", "authorization", "token"))
            }
        if isinstance(value, list):
            return [public(item) for item in value]
        return value

    print(EVENT_PREFIX + json.dumps(public(event), separators=(",", ":"), ensure_ascii=True), flush=True)


def _emit_checkpoint_provenance(policy_factory: Any) -> None:
    provenance = getattr(policy_factory, "checkpoint_provenance", None)
    if isinstance(provenance, list) and provenance:
        _emit_event({"event_type": "checkpoint_provenance", "checkpoints": provenance})


class RoundPauseGate:
    """Pause the same run_episode process until the bridge sends CONTINUE."""

    def __init__(self, emit_event: Any = _emit_event, pause_reason: str = "round_boundary"):
        self.emit_event = emit_event
        self.completed_rounds = 0
        self.pause_reason = pause_reason

    def __call__(self, scenario_id: int, state: dict[str, Any]) -> None:
        self.completed_rounds += 1
        self.emit_event({
            "event_type": "round_paused",
            "scenario_id": scenario_id,
            "round_number": self.completed_rounds,
            "pause_reason": self.pause_reason,
            "state": state,
        })
        command = sys.stdin.readline()
        if command.strip().upper() != "CONTINUE":
            raise RuntimeError("Learned-agent run was cancelled while paused.")
        self.emit_event({
            "event_type": "round_resumed",
            "scenario_id": scenario_id,
            "round_number": self.completed_rounds,
        })


def run_learned_episode(
    scenario_id: int,
    *,
    client: CatchMeIfYouCanApiClient | None = None,
    fraudster_checkpoint: str | Path = DEFAULT_FRAUDSTER_CHECKPOINT,
    investigator_checkpoint: str | Path = DEFAULT_INVESTIGATOR_CHECKPOINT,
    max_actions: int = 60,
    seed: int = 0,
    pause_between_rounds: bool = False,
) -> dict[str, Any]:
    """Run learned policies on an existing ID without creating a scenario."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer.")

    # Consume the backend-issued child-process secret before policy objects,
    # including the investigator policy, are constructed.
    api_client = client or CatchMeIfYouCanApiClient()
    policy_factory = build_policy_factory(
        "learned",
        seed=seed,
        fraudster_checkpoint=fraudster_checkpoint,
        investigator_checkpoint=investigator_checkpoint,
    )
    _emit_checkpoint_provenance(policy_factory)
    fraudster_policy, investigator_policy = policy_factory(0)

    def authorized_shell_ids(current_scenario_id: int) -> list[int]:
        response = api_client.get_fraudster_authorization_probe(current_scenario_id)
        if (not isinstance(response, dict)
                or response.get("status") != "authorized"
                or not isinstance(response.get("privateShellCompanyIds"), list)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        ids = response["privateShellCompanyIds"]
        if (any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in ids)
                or len(set(ids)) != len(ids)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        return ids

    result: dict[str, Any] = {}
    final_state = run_episode(
        api_client,
        scenario_id=scenario_id,
        max_actions=max_actions,
        result_collector=result,
        fraudster_policy=fraudster_policy,
        investigator_policy=investigator_policy,
        event_callback=_emit_event,
        pause_before_fraudster=RoundPauseGate() if pause_between_rounds else None,
        private_shell_knowledge_provider=authorized_shell_ids,
    )
    _emit_event({
        "event_type": "episode_result",
        "scenario_id": scenario_id,
        "episode_class": result.get("episode_class"),
        "actions_attempted": result.get("actions_attempted"),
        "stop_reason": result.get("stop_reason"),
        "investigator_evidence": result.get("investigator_evidence"),
        "candidate_opportunities": result.get("candidate_opportunities"),
        "candidate_opportunities_complete": result.get("candidate_opportunities_complete"),
        "final_state": final_state,
    })
    return result


def run_human_fraudster_episode(
    scenario_id: int,
    *,
    investigator_checkpoint: str | Path,
    client: CatchMeIfYouCanApiClient | None = None,
    max_actions: int = 60,
    seed: int = 0,
) -> dict[str, Any]:
    """Pause for real UI fraudster actions and answer with the learned investigator."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer.")
    api_client = client or CatchMeIfYouCanApiClient()
    policy_factory = build_policy_factory(
        "learned_investigator", seed=seed, investigator_checkpoint=investigator_checkpoint,
    )
    _emit_checkpoint_provenance(policy_factory)
    _, investigator_policy = policy_factory(0)
    result: dict[str, Any] = {}
    final_state = run_episode(
        api_client,
        scenario_id=scenario_id,
        max_actions=max_actions,
        result_collector=result,
        investigator_policy=investigator_policy,
        event_callback=_emit_event,
        pause_before_fraudster=RoundPauseGate(pause_reason="human_fraudster"),
        human_controlled_fraudster=True,
    )
    _emit_event({
        "event_type": "episode_result",
        "scenario_id": scenario_id,
        "episode_class": result.get("episode_class"),
        "actions_attempted": result.get("actions_attempted"),
        "stop_reason": result.get("stop_reason"),
        "investigator_evidence": result.get("investigator_evidence"),
        "final_state": final_state,
    })
    return result


def run_fraudster_training_episode(
    scenario_id: int,
    *,
    fraudster_checkpoint: str | Path | None = None,
    investigator_checkpoint: str | Path | None = None,
    fraudster_output_checkpoint: str | Path,
    investigator_output_checkpoint: str | Path,
    client: CatchMeIfYouCanApiClient | None = None,
    ground_truth_reader: Any | None = None,
    max_actions: int = 60,
    seed: int = 0,
    initialize_fresh: bool = False,
) -> dict[str, Any]:
    """Train on one app-managed active scenario using its run-scoped grant."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer.")

    api_client = client or CatchMeIfYouCanApiClient()

    def authorized_shell_ids(current_scenario_id: int) -> list[int]:
        response = api_client.get_fraudster_authorization_probe(current_scenario_id)
        if (not isinstance(response, dict)
                or response.get("status") != "authorized"
                or not isinstance(response.get("privateShellCompanyIds"), list)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        ids = response["privateShellCompanyIds"]
        if (any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in ids)
                or len(set(ids)) != len(ids)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        return ids

    result = train_existing_scenario(
        api_client,
        ground_truth_reader or PostgresGroundTruthReader.from_environment(),
        scenario_id=scenario_id,
        max_actions=max_actions,
        seed=seed,
        fraudster_checkpoint=fraudster_checkpoint,
        investigator_checkpoint=investigator_checkpoint,
        fraudster_output_checkpoint=fraudster_output_checkpoint,
        investigator_output_checkpoint=investigator_output_checkpoint,
        private_shell_knowledge_provider=authorized_shell_ids,
        ensure_shell_path=True,
        initialize_fresh=initialize_fresh,
    )
    _emit_event({
        "event_type": "training_result",
        "scenario_id": scenario_id,
        "episode_count": 1,
        "episode_completed": result.get("episode_completed"),
        "actions_attempted": result.get("actions_attempted"),
        "terminal_outcome": result.get("terminal_outcome"),
        "fraudster_reward": result.get("fraudster_reward"),
        "fraudster_transition_count": result.get("transition_counts", {}).get("fraudster"),
        "fraudster_training_steps": result.get("fraudster_training_steps"),
        "fraudster_checkpoint": result.get("fraudster_checkpoint"),
        "investigator_training_steps": result.get("investigator_training_steps"),
        "investigator_checkpoint": result.get("investigator_checkpoint"),
        "fraudster_action_type_counts": result.get("fraudster_action_type_counts"),
        "shell_path_transfer_confirmed": result.get("shell_path_transfer_confirmed"),
        "path_positive_candidate_count": result.get("path_positive_candidate_count"),
        "path_negative_candidate_count": result.get("path_negative_candidate_count"),
    })
    _emit_event({
        "event_type": "episode_result",
        "scenario_id": scenario_id,
        "episode_class": "completed",
        "actions_attempted": result.get("actions_attempted"),
        "stop_reason": "training episode terminated",
        "final_state": {
            "id": scenario_id,
            "status": result.get("terminal_outcome"),
        },
    })
    return result


def run_investigator_training_episode(
    scenario_id: int, *, investigator_checkpoint: str | Path | None,
    investigator_output_checkpoint: str | Path, client: CatchMeIfYouCanApiClient | None = None,
    ground_truth_reader: Any | None = None, max_actions: int = 60, seed: int = 0,
    initialize_fresh: bool = False,
) -> dict[str, Any]:
    api_client = client or CatchMeIfYouCanApiClient()

    def authorized_shell_ids(current_scenario_id: int) -> list[int]:
        response = api_client.get_fraudster_authorization_probe(current_scenario_id)
        if (not isinstance(response, dict)
                or response.get("status") != "authorized"
                or not isinstance(response.get("privateShellCompanyIds"), list)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        ids = response["privateShellCompanyIds"]
        if (any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in ids)
                or len(set(ids)) != len(ids)):
            raise AgentObservationError("Protected shell-knowledge response is malformed.")
        return ids

    result = train_existing_investigator_scenario(
        api_client, ground_truth_reader or PostgresGroundTruthReader.from_environment(),
        scenario_id=scenario_id, max_actions=max_actions, seed=seed,
        investigator_checkpoint=investigator_checkpoint,
        investigator_output_checkpoint=investigator_output_checkpoint,
        private_shell_knowledge_provider=authorized_shell_ids,
        initialize_fresh=initialize_fresh,
    )
    _emit_event({
        "event_type": "training_result", "scenario_id": scenario_id, "episode_count": 1,
        "episode_completed": result.get("episode_completed"),
        "actions_attempted": result.get("actions_attempted"),
        "terminal_outcome": result.get("terminal_outcome"),
        "investigator_transition_count": result.get("transition_counts", {}).get("investigator"),
        "investigator_training_steps": result.get("investigator_training_steps"),
        "fraudster_action_type_counts": result.get("fraudster_action_type_counts"),
        "shell_path_transfer_confirmed": result.get("shell_path_transfer_confirmed"),
        "path_positive_candidate_count": result.get("path_positive_candidate_count"),
        "path_negative_candidate_count": result.get("path_negative_candidate_count"),
        "investigator_checkpoint": result.get("investigator_checkpoint"),
    })
    _emit_event({"event_type": "episode_result", "scenario_id": scenario_id,
                 "episode_class": "completed", "actions_attempted": result.get("actions_attempted"),
                 "stop_reason": "training episode terminated",
                 "final_state": {"id": scenario_id, "status": result.get("terminal_outcome")}})
    return result


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True, type=_positive_int)
    # Checkpoint defaults belong to inference only. Keeping these unset in the
    # parsed arguments ensures fresh training cannot accidentally inherit an
    # old default checkpoint as an input.
    parser.add_argument("--fraudster-checkpoint", type=Path)
    parser.add_argument("--investigator-checkpoint", type=Path)
    parser.add_argument("--max-actions", type=_positive_int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pause-between-rounds", action="store_true")
    parser.add_argument("--human-fraudster", action="store_true")
    parser.add_argument("--train-fraudster", action="store_true")
    parser.add_argument("--train-investigator", action="store_true")
    parser.add_argument("--initialize-fresh", action="store_true")
    parser.add_argument("--fraudster-output-checkpoint", type=Path)
    parser.add_argument("--investigator-output-checkpoint", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.human_fraudster:
            if (args.train_fraudster or args.train_investigator or args.pause_between_rounds
                    or args.fraudster_checkpoint is not None
                    or args.fraudster_output_checkpoint is not None
                    or args.investigator_output_checkpoint is not None
                    or args.initialize_fresh or args.investigator_checkpoint is None):
                raise ValueError("Human-fraudster mode requires only an investigator checkpoint.")
            run_human_fraudster_episode(
                args.scenario_id, investigator_checkpoint=args.investigator_checkpoint,
                max_actions=args.max_actions, seed=args.seed,
            )
        elif args.train_investigator:
            if args.train_fraudster or args.pause_between_rounds or args.fraudster_checkpoint is not None \
                    or args.fraudster_output_checkpoint is not None or args.investigator_output_checkpoint is None:
                raise ValueError("Investigator training requires its output path and cannot combine with other modes.")
            if args.initialize_fresh == (args.investigator_checkpoint is not None):
                raise ValueError("Fresh investigator training takes no input checkpoint; resume requires one.")
            run_investigator_training_episode(
                args.scenario_id, investigator_checkpoint=args.investigator_checkpoint,
                investigator_output_checkpoint=args.investigator_output_checkpoint,
                max_actions=args.max_actions, seed=args.seed, initialize_fresh=args.initialize_fresh,
            )
        elif args.train_fraudster:
            if (args.fraudster_output_checkpoint is None
                    or args.investigator_output_checkpoint is None
                    or args.pause_between_rounds
                    or not args.initialize_fresh):
                raise ValueError(
                    "Training requires --initialize-fresh, both fresh output checkpoints, "
                    "and does not use round pausing."
                )
            run_fraudster_training_episode(
                args.scenario_id,
                fraudster_output_checkpoint=args.fraudster_output_checkpoint,
                investigator_output_checkpoint=args.investigator_output_checkpoint,
                max_actions=args.max_actions,
                seed=args.seed,
                initialize_fresh=True,
            )
        else:
            if (args.fraudster_output_checkpoint is not None
                    or args.investigator_output_checkpoint is not None
                    or args.initialize_fresh):
                raise ValueError("Training options are valid only with --train-fraudster.")
            run_learned_episode(
                args.scenario_id,
                fraudster_checkpoint=args.fraudster_checkpoint or DEFAULT_FRAUDSTER_CHECKPOINT,
                investigator_checkpoint=args.investigator_checkpoint or DEFAULT_INVESTIGATOR_CHECKPOINT,
                max_actions=args.max_actions,
                seed=args.seed,
                pause_between_rounds=args.pause_between_rounds,
            )
        return 0
    except Exception as error:
        diagnostic = getattr(error, "diagnostic", None)
        if isinstance(diagnostic, dict):
            _emit_event({
                "event_type": "runner_diagnostic",
                "diagnostic": {
                    key: diagnostic[key]
                    for key in ("stage", "exception_type", "sqlstate")
                    if isinstance(diagnostic.get(key), str)
                },
            })
        _emit_event({
            "event_type": "runner_error",
            "scenario_id": args.scenario_id,
            "message": str(error) or error.__class__.__name__,
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
