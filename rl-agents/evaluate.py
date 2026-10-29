"""Run independent CatchMeIfYouCan episodes and aggregate safe metrics."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import Any

try:
    from .api_client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError
    from .detection_metrics import calculate_detection_metrics
    from .ground_truth import EvaluatorDataError, PostgresGroundTruthReader
    from .q_learning import QLearningAgent, ReadOnlyQLearningAgent, checkpoint_compatibility
    from .fraudster_bot import FraudsterBot
    from .investigator_bot import InvestigatorBot
    from .rl_policies import (
        RLFraudsterPolicy,
        RLInvestigatorPolicy,
        RandomFraudsterPolicy,
        RandomInvestigatorPolicy,
    )
    from .run_episode import FRAUDSTER_ACTION_TYPES, TERMINAL_STATUSES, run_episode
except ImportError:  # Supports ``python evaluate.py`` from rl-agents.
    from api_client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError
    from detection_metrics import calculate_detection_metrics
    from ground_truth import EvaluatorDataError, PostgresGroundTruthReader
    from q_learning import QLearningAgent, ReadOnlyQLearningAgent, checkpoint_compatibility
    from fraudster_bot import FraudsterBot
    from investigator_bot import InvestigatorBot
    from rl_policies import (
        RLFraudsterPolicy,
        RLInvestigatorPolicy,
        RandomFraudsterPolicy,
        RandomInvestigatorPolicy,
    )
    from run_episode import FRAUDSTER_ACTION_TYPES, TERMINAL_STATUSES, run_episode


_EVIDENCE_COUNT_FIELDS = (
    "successful_director_investigations",
    "unique_director_ids_discovered",
    "unique_connected_company_ids_discovered",
    "unique_company_director_relationships",
    "unique_director_company_connections",
)


def build_policy_factory(
    policy_name: str,
    *,
    seed: int = 0,
    fraudster_checkpoint: str | Path | None = None,
    investigator_checkpoint: str | Path | None = None,
    allow_legacy_checkpoints: bool = False,
):
    """Return a factory for fresh per-episode policies.

    Learned tables are loaded once and wrapped read-only. Evaluation therefore
    cannot add unseen actions, update Q-values, or save checkpoints.
    """
    if policy_name == "heuristic":
        return lambda episode_index: (FraudsterBot(), InvestigatorBot())
    if policy_name == "random":
        return lambda episode_index: (
            RandomFraudsterPolicy(seed + episode_index * 2),
            RandomInvestigatorPolicy(seed + episode_index * 2 + 1),
        )
    if policy_name == "learned_investigator":
        if investigator_checkpoint is None:
            raise ValueError(
                "learned_investigator evaluation requires investigator_checkpoint."
            )
        if not Path(investigator_checkpoint).is_file():
            raise ValueError("The requested investigator checkpoint does not exist.")
        investigator_learner = QLearningAgent.load(investigator_checkpoint)
        expected = checkpoint_compatibility("investigator")
        if investigator_learner.compatibility != expected:
            compatibility = investigator_learner.compatibility or {}
            mismatched = sorted(
                key for key, value in expected.items() if compatibility.get(key) != value
            )
            raise ValueError(
                "investigator checkpoint compatibility is incompatible; mismatched fields: "
                + ", ".join(mismatched)
                + "."
            )

        def learned_investigator_factory(episode_index: int):
            return (
                FraudsterBot(),
                RLInvestigatorPolicy(ReadOnlyQLearningAgent(
                    investigator_learner, seed=seed + episode_index
                )),
            )

        learned_investigator_factory.checkpoint_provenance = [  # type: ignore[attr-defined]
            _checkpoint_provenance("investigator", investigator_checkpoint, investigator_learner)
        ]
        return learned_investigator_factory
    if policy_name != "learned":
        raise ValueError(
            "policy_name must be one of: random, heuristic, learned, learned_investigator."
        )
    if fraudster_checkpoint is None or investigator_checkpoint is None:
        raise ValueError(
            "learned evaluation requires both fraudster_checkpoint and investigator_checkpoint."
        )
    if not Path(fraudster_checkpoint).is_file() or not Path(investigator_checkpoint).is_file():
        raise ValueError("The requested learned-policy checkpoint does not exist.")
    fraudster_learner = QLearningAgent.load(fraudster_checkpoint)
    investigator_learner = QLearningAgent.load(investigator_checkpoint)

    for role, learner in (
        ("fraudster", fraudster_learner),
        ("investigator", investigator_learner),
    ):
        compatibility = learner.compatibility
        if compatibility is None:
            if not allow_legacy_checkpoints:
                raise ValueError(
                    f"{role} checkpoint is legacy format-1 without compatibility metadata; "
                    "pass allow_legacy_checkpoints=True explicitly."
                )
            continue
        expected_compatibility = checkpoint_compatibility(role)
        if compatibility != expected_compatibility:
            mismatched = sorted(
                key for key, expected in expected_compatibility.items()
                if compatibility.get(key) != expected
            )
            raise ValueError(
                f"{role} checkpoint compatibility is incompatible; mismatched fields: "
                + ", ".join(mismatched)
                + "."
            )

    def learned_factory(episode_index: int):
        return (
            RLFraudsterPolicy(ReadOnlyQLearningAgent(
                fraudster_learner, seed=seed + episode_index * 2
            )),
            RLInvestigatorPolicy(ReadOnlyQLearningAgent(
                investigator_learner, seed=seed + episode_index * 2 + 1
            )),
        )

    learned_factory.checkpoint_provenance = [  # type: ignore[attr-defined]
        _checkpoint_provenance("fraudster", fraudster_checkpoint, fraudster_learner),
        _checkpoint_provenance("investigator", investigator_checkpoint, investigator_learner),
    ]
    return learned_factory


def _checkpoint_provenance(role: str, path: str | Path, learner: QLearningAgent) -> dict[str, Any]:
    """Describe only checkpoint data successfully loaded and compatibility-validated."""
    checkpoint_hash = getattr(learner, "_loaded_checkpoint_sha256", None)
    loaded_path = getattr(learner, "_loaded_checkpoint_path", None)
    training_provenance = learner.metadata.get("training_provenance", {})
    allowed_training_fields = (
        "episode_count", "completed_episode_count", "objective_success_rate",
        "fraudster_transition_count", "investigator_transition_count",
        "fraudster_training_steps", "investigator_training_steps",
        "shell_path_transfer_confirmed", "path_positive_candidate_count",
        "path_negative_candidate_count", "episodes", "seed", "max_actions",
        "training_mode", "shell_path_coverage_target",
    )
    training_metadata = {
        key: training_provenance[key]
        for key in allowed_training_fields
        if isinstance(training_provenance, dict) and key in training_provenance
        and isinstance(training_provenance[key], (str, int, float, bool, type(None)))
    }
    if isinstance(training_provenance, dict):
        episode_results = []
        for item in training_provenance.get("episode_results", []):
            if not isinstance(item, dict):
                continue
            episode = {
                key: item[key]
                for key in ("scenario_id", "shell_path_transfer_confirmed",
                            "path_positive_candidate_count", "path_negative_candidate_count")
                if key in item and isinstance(item[key], (str, int, float, bool, type(None)))
            }
            action_counts = item.get("fraudster_action_type_counts")
            if isinstance(action_counts, dict) and all(
                    isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
                    for key, value in action_counts.items()):
                episode["fraudster_action_type_counts"] = dict(action_counts)
            episode_results.append(episode)
        if episode_results:
            training_metadata["episode_results"] = episode_results
    return {
        "role": role,
        "file_name": Path(loaded_path or path).name,
        "sha256": checkpoint_hash,
        "compatibility": learner.compatibility,
        "compatibility_status": (
            "validated" if learner.compatibility is not None
            else "accepted without compatibility metadata"
        ),
        "training_steps": learner.training_steps,
        "training_metadata": training_metadata,
    }


def _creation_failure(
    *,
    source_company_id: int,
    target_company_id: int,
    error: Exception,
) -> dict[str, Any]:
    return {
        "scenario_id": None,
        "initial_source_company_id": source_company_id,
        "initial_target_company_id": target_company_id,
        "final_state": None,
        "actions_attempted": None,
        "stop_reason": "scenario_creation_failed",
        "episode_class": "failed",
        "failure_stage": "scenario_creation",
        "error": str(error),
        "creation_succeeded": False,
        "investigator_evidence": None,
    }


def attach_detection_metrics(
    report: dict[str, Any],
    episode_results: list[dict[str, Any]],
    ground_truth_reader: Any,
) -> dict[str, Any]:
    """Attach evaluator-only metrics after every supplied episode is terminal.

    This also supports post-hoc scoring of a saved evaluation report when it
    retained the legal flag-candidate snapshots. Labels are fetched only here,
    after all episodes have completed, and are never copied into episode data.
    """
    created_ids = [
        result.get("scenario_id")
        for result in episode_results
        if result.get("creation_succeeded")
    ]
    if not created_ids:
        raise EvaluatorDataError("No successfully created scenarios are available for detection evaluation.")
    incomplete = [
        result for result in episode_results
        if result.get("creation_succeeded") and (
            result.get("episode_class") != "completed"
            or not isinstance(result.get("final_state"), dict)
            or result["final_state"].get("status") not in TERMINAL_STATUSES
        )
    ]
    if incomplete:
        raise EvaluatorDataError(
            "Detection metrics require all created episodes to complete; "
            f"{len(incomplete)} episode(s) are incomplete."
        )
    if any(isinstance(scenario_id, bool) or not isinstance(scenario_id, int)
           or scenario_id <= 0 for scenario_id in created_ids):
        raise EvaluatorDataError("Detection metrics require valid positive integer scenario IDs.")
    if len(created_ids) != len(set(created_ids)):
        raise EvaluatorDataError("Detection metrics require unique scenario IDs.")

    candidate_ids_by_scenario: dict[int, set[int]] = {}
    for result in episode_results:
        if not result.get("creation_succeeded"):
            continue
        scenario_id = result.get("scenario_id")
        if result.get("candidate_opportunities_complete") is not True:
            raise EvaluatorDataError(
                f"Scenario {scenario_id} is missing validated legal flag-candidate snapshots."
            )
        opportunities = result.get("candidate_opportunities")
        if not isinstance(opportunities, list):
            raise EvaluatorDataError(
                f"Scenario {scenario_id} is missing validated legal flag-candidate snapshots."
            )
        candidates: set[int] = set()
        for index, opportunity in enumerate(opportunities):
            if not isinstance(opportunity, dict):
                raise EvaluatorDataError("Candidate opportunities must be objects.")
            opportunity_scenario_id = opportunity.get("scenario_id")
            decision_index = opportunity.get("decision_index")
            if (isinstance(opportunity_scenario_id, bool)
                    or not isinstance(opportunity_scenario_id, int)
                    or opportunity_scenario_id != scenario_id
                    or isinstance(decision_index, bool)
                    or not isinstance(decision_index, int)
                    or decision_index != index):
                raise EvaluatorDataError("Candidate opportunity scenario or decision index is inconsistent.")
            company_ids = opportunity.get("candidate_company_ids")
            if not isinstance(company_ids, list):
                raise EvaluatorDataError("Candidate opportunity is missing its legal flag choices.")
            for company_id in company_ids:
                if (isinstance(company_id, bool) or not isinstance(company_id, int)
                        or company_id <= 0):
                    raise EvaluatorDataError("Captured candidate company IDs must be positive integers.")
                candidates.add(company_id)
        candidate_ids_by_scenario[scenario_id] = candidates

    baseline_records = ground_truth_reader.read_candidates(created_ids)
    if len(baseline_records) != 2 * len(created_ids):
        raise EvaluatorDataError("Ground truth must contain one source and one destination per scenario.")
    baseline_by_scenario: dict[int, list[Any]] = {scenario_id: [] for scenario_id in created_ids}
    for candidate in baseline_records:
        if candidate.scenario_id not in baseline_by_scenario:
            raise EvaluatorDataError("Source/destination ground truth contains an unexpected scenario.")
        baseline_by_scenario[candidate.scenario_id].append(candidate)
    for scenario_id, episode in (
        (result["scenario_id"], result)
        for result in episode_results if result.get("creation_succeeded")
    ):
        source_id = episode.get("initial_source_company_id")
        destination_id = episode.get("initial_target_company_id")
        if (isinstance(source_id, bool) or not isinstance(source_id, int)
                or isinstance(destination_id, bool) or not isinstance(destination_id, int)
                or source_id <= 0 or destination_id <= 0 or source_id == destination_id):
            raise EvaluatorDataError("Episode is missing valid source/destination company IDs.")
        records = baseline_by_scenario[scenario_id]
        by_company = {candidate.company_id: candidate for candidate in records}
        if len(records) != 2 or set(by_company) != {source_id, destination_id}:
            raise EvaluatorDataError("Ground truth does not match the episode source and destination.")
    baseline_metrics = calculate_detection_metrics(
        [
            {"shell_company": item.shell_company, "flagged": item.flagged}
            for item in baseline_records
        ]
    )
    baseline_metrics["candidate_population"] = "scenario source and target companies"
    baseline_metrics["metric_scope"] = "source_target_baseline"
    baseline_metrics["evaluated_scenario_count"] = len(created_ids)
    report["detection_metrics"] = baseline_metrics

    discovered_records = ground_truth_reader.read_discovered_candidates(
        created_ids, candidate_ids_by_scenario
    )
    expected_discovered_count = sum(len(ids) for ids in candidate_ids_by_scenario.values())
    if len(discovered_records) != expected_discovered_count:
        raise EvaluatorDataError("Discovered-candidate ground truth is incomplete.")
    discovered_metrics = calculate_detection_metrics(
        [
            {"shell_company": item.shell_company, "flagged": item.flagged}
            for item in discovered_records
        ]
    )
    discovered_metrics["candidate_population"] = (
        "unique scenario-company pairs available as legal FLAG_COMPANY choices "
        "immediately before an investigator decision"
    )
    discovered_metrics["label_definition"] = (
        "general shell classification: shell_company status, whether or not the company "
        "appears on a FRAUDSTER_ACTION transfer path"
    )
    discovered_metrics["metric_scope"] = "discovered_candidate_population"
    discovered_metrics["evaluated_scenario_count"] = len(created_ids)
    report["discovered_candidate_metrics"] = discovered_metrics

    path_labels = []
    for item in discovered_records:
        path_involved = getattr(item, "fraud_path_involved", None)
        if not isinstance(item.shell_company, bool) or not isinstance(path_involved, bool):
            raise EvaluatorDataError(
                "Discovered-candidate ground truth is missing validated fraud-path labels."
            )
        path_labels.append({
            # The metrics helper consumes a binary truth field named
            # shell_company; here it deliberately represents the narrower
            # positive class: shell AND present on a FRAUDSTER_ACTION path.
            "shell_company": item.shell_company and path_involved,
            "flagged": item.flagged,
        })
    path_metrics = calculate_detection_metrics(path_labels)
    path_metrics["candidate_population"] = (
        "unique scenario-company pairs available as legal FLAG_COMPANY choices "
        "immediately before an investigator decision"
    )
    path_metrics["label_definition"] = (
        "positive only when the candidate is a shell company and appears as a source "
        "or destination in a scenario transaction with origin FRAUDSTER_ACTION"
    )
    path_metrics["metric_scope"] = "fraud_path_shell_detection"
    path_metrics["evaluated_scenario_count"] = len(created_ids)
    report["fraud_path_detection_metrics"] = path_metrics
    report["detection_metric_provenance"] = {
        "label_source": "read-only evaluator database",
        "label_access_phase": "after every episode reached a terminal status",
        "investigator_observation_access": False,
        "fraud_path_label_definition": path_metrics["label_definition"],
        "evaluated_scenario_count": len(created_ids),
    }

    episode_by_id = {result["scenario_id"]: result for result in episode_results
                     if result.get("creation_succeeded")}
    for scenario_id in created_ids:
        episode = episode_by_id[scenario_id]
        baseline_episode = baseline_by_scenario[scenario_id]
        discovered_episode = [item for item in discovered_records if item.scenario_id == scenario_id]
        episode["detection_metrics"] = calculate_detection_metrics(
            [{"shell_company": item.shell_company, "flagged": item.flagged}
             for item in baseline_episode]
        )
        episode["detection_metrics"]["metric_scope"] = "source_target_baseline"
        episode["discovered_candidate_metrics"] = calculate_detection_metrics(
            [{"shell_company": item.shell_company, "flagged": item.flagged}
             for item in discovered_episode]
        )
        episode["discovered_candidate_metrics"]["metric_scope"] = "discovered_candidate_population"
        episode["discovered_candidate_metrics"]["label_definition"] = (
            "general shell classification, independent of fraudster transfer-path membership"
        )
        episode_path_records = []
        for item in discovered_episode:
            path_involved = getattr(item, "fraud_path_involved", None)
            if not isinstance(item.shell_company, bool) or not isinstance(path_involved, bool):
                raise EvaluatorDataError(
                    "Discovered-candidate ground truth is missing validated fraud-path labels."
                )
            episode_path_records.append({
                "shell_company": item.shell_company and path_involved,
                "flagged": item.flagged,
            })
        episode["fraud_path_detection_metrics"] = calculate_detection_metrics(
            episode_path_records
        )
        episode["fraud_path_detection_metrics"]["metric_scope"] = "fraud_path_shell_detection"
        episode["fraud_path_detection_metrics"]["candidate_population"] = (
            "unique scenario-company pairs available as legal FLAG_COMPANY choices "
            "immediately before an investigator decision"
        )
        episode["fraud_path_detection_metrics"]["label_definition"] = path_metrics[
            "label_definition"
        ]
    return report


def run_evaluation(
    client: CatchMeIfYouCanApiClient,
    *,
    scenario_count: int,
    source_company_id: int,
    target_company_id: int,
    amount: str,
    max_actions: int = 20,
    continue_on_failure: bool = False,
    detection_metrics: bool = False,
    ground_truth_reader: Any | None = None,
    policy_name: str = "heuristic",
    seed: int = 0,
    fraudster_checkpoint: str | Path | None = None,
    investigator_checkpoint: str | Path | None = None,
    allow_legacy_checkpoints: bool = False,
) -> dict[str, Any]:
    _validate_evaluation_inputs(
        scenario_count, source_company_id, target_company_id, amount, max_actions
    )
    if scenario_count < 0:
        raise ValueError("scenario_count must not be negative.")
    managed_learned = policy_name == "learned"
    loaded_checkpoint_provenance = None
    if managed_learned:
        # Managed AgentRun creates a fresh grant for each scenario and owns its
        # child credential's revocation lifecycle. Validate explicit checkpoint
        # files/contracts before creating scenarios; actual managed paths are
        # selected by the server's existing agents.* configuration.
        if fraudster_checkpoint is None or investigator_checkpoint is None:
            raise ValueError("learned evaluation requires both checkpoint paths.")
        validation_factory = build_policy_factory(
            policy_name, seed=seed, fraudster_checkpoint=fraudster_checkpoint,
            investigator_checkpoint=investigator_checkpoint,
            allow_legacy_checkpoints=allow_legacy_checkpoints,
        )
        # These are only the CLI-side validation loads; managed runs select
        # checkpoints independently through the Spring agents.* configuration.
        loaded_checkpoint_provenance = getattr(validation_factory, "checkpoint_provenance", None)
        if not all(callable(getattr(client, name, None)) for name in (
                "start_agent_run", "get_agent_run", "continue_agent_run", "cancel_agent_run")):
            raise EvaluatorDataError(
                "Learned evaluation requires the managed per-scenario AgentRun API."
            )
    else:
        policy_factory = build_policy_factory(
            policy_name,
            seed=seed,
            fraudster_checkpoint=fraudster_checkpoint,
            investigator_checkpoint=investigator_checkpoint,
            allow_legacy_checkpoints=allow_legacy_checkpoints,
        )
        loaded_checkpoint_provenance = getattr(policy_factory, "checkpoint_provenance", None)
    results: list[dict[str, Any]] = []
    for episode_index in range(scenario_count):
        try:
            created = client.create_scenario(
                source_company_id=source_company_id,
                target_company_id=target_company_id,
                amount=amount,
            )
            scenario_id = created["id"]
        except (CatchMeIfYouCanApiError, KeyError, TypeError) as error:
            result = _creation_failure(
                source_company_id=source_company_id,
                target_company_id=target_company_id,
                error=error,
            )
            results.append(result)
            if not continue_on_failure:
                break
            continue

        result: dict[str, Any] = {}
        try:
            if managed_learned:
                result.update(_run_managed_learned_scenario(client, scenario_id))
            else:
                policies = policy_factory(episode_index)
                episode_kwargs = {
                    "scenario_id": scenario_id,
                    "max_actions": max_actions,
                    "result_collector": result,
                }
                if policy_name != "heuristic":
                    episode_kwargs.update({
                        "fraudster_policy": policies[0],
                        "investigator_policy": policies[1],
                    })
                run_episode(client, **episode_kwargs)
        except (CatchMeIfYouCanApiError, RuntimeError) as error:
            result.update({
                "scenario_id": scenario_id,
                "initial_source_company_id": source_company_id,
                "initial_target_company_id": target_company_id,
                "final_state": None,
                "actions_attempted": result.get("actions_attempted"),
                "stop_reason": "runner_failed",
                "episode_class": "failed",
                "investigator_evidence": result.get("investigator_evidence"),
            })
            result["failure_stage"] = "episode_execution"
            result["error"] = str(error)

        if result.get("episode_class") == "completed":
            final_state = result.get("final_state")
            terminal_status = (
                final_state.get("status") if isinstance(final_state, dict) else None
            )
            if terminal_status not in TERMINAL_STATUSES:
                result.update({
                    "episode_class": "failed",
                    "failure_stage": "invalid_terminal_status",
                    "stop_reason": "invalid terminal status",
                    "error": (
                        "Episode reported completion with invalid terminal status "
                        f"{terminal_status!r}."
                    ),
                })

        result.setdefault("scenario_id", scenario_id)
        result.setdefault("initial_source_company_id", source_company_id)
        result.setdefault("initial_target_company_id", target_company_id)
        result["creation_succeeded"] = True
        results.append(result)
        if result.get("episode_class") == "failed" and not continue_on_failure:
            break

    report = aggregate_episode_results(
        results, requested_count=scenario_count, policy_name=policy_name
    )
    report["checkpoint_provenance"] = {
        "loaded_checkpoint_records": loaded_checkpoint_provenance,
        "checkpoint_compatibility_validation_inputs": {
            "fraudster": str(fraudster_checkpoint) if fraudster_checkpoint else None,
            "investigator": str(investigator_checkpoint) if investigator_checkpoint else None,
        },
        "execution_mode": "managed AgentRun per scenario" if managed_learned else "local evaluator",
        "effective_managed_checkpoint_selection": (
            "server agents.fraudster-checkpoint and agents.investigator-checkpoint; "
            "the managed API does not return checkpoint paths"
            if managed_learned else None
        ),
    }
    report["scenario_ids"] = [r.get("scenario_id") for r in results if r.get("creation_succeeded")]
    if detection_metrics:
        reader = ground_truth_reader or PostgresGroundTruthReader.from_environment()
        attach_detection_metrics(report, results, reader)
    elif managed_learned:
        report["fraud_path_detection_metrics"] = {
            "metric_scope": "fraud_path_shell_detection",
            "status": "not_computed",
            "reason": "Pass --detection-metrics to score terminal-only fraud-path labels.",
        }
    return report


def _run_managed_learned_scenario(client: Any, scenario_id: int) -> dict[str, Any]:
    """Run one episode under a newly issued scenario/run-bound backend grant."""
    run_id = None
    try:
        started = client.start_agent_run(scenario_id)
        if not isinstance(started, dict):
            raise EvaluatorDataError("Managed AgentRun returned a malformed response.")
        run_id = started.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise EvaluatorDataError("Managed AgentRun returned an invalid run ID.")
        if started.get("scenarioId") != scenario_id:
            raise EvaluatorDataError("Managed AgentRun returned a mismatched scenario ID.")
        deadline = time.monotonic() + 300
        state = started
        while state.get("status") in {"RUNNING", "PAUSED"}:
            if time.monotonic() >= deadline:
                raise EvaluatorDataError("Managed AgentRun timed out before a terminal result.")
            if state.get("status") == "PAUSED":
                state = client.continue_agent_run(run_id)
                if (not isinstance(state, dict) or state.get("runId") != run_id
                        or state.get("scenarioId") != scenario_id):
                    raise EvaluatorDataError(
                        "Continued AgentRun response does not match its scenario and run IDs."
                    )
                continue
            time.sleep(0.1)
            state = client.get_agent_run(run_id)
            if not isinstance(state, dict) or state.get("runId") != run_id or state.get("scenarioId") != scenario_id:
                raise EvaluatorDataError("Managed AgentRun response does not match its scenario and run IDs.")
        if state.get("status") not in {"COMPLETED", "FAILED"}:
            raise EvaluatorDataError("Managed AgentRun returned an invalid terminal status.")
        events = state.get("events")
        episode_event = next((event for event in reversed(events or [])
                              if isinstance(event, dict) and event.get("event_type") == "episode_result"), None)
        if state["status"] != "COMPLETED" or episode_event is None:
            return {
                "scenario_id": scenario_id,
                "episode_class": "failed",
                "failure_stage": "managed_agent_run",
                "error": state.get("message") or "Managed AgentRun did not emit a completed episode result.",
            }
        final_state = episode_event.get("final_state")
        if not isinstance(final_state, dict) or final_state.get("id") != scenario_id:
            raise EvaluatorDataError("Managed episode result has a mismatched scenario ID.")
        return {
            "scenario_id": scenario_id,
            "episode_class": "completed" if final_state.get("status") in TERMINAL_STATUSES else "failed",
            "final_state": final_state,
            "actions_attempted": episode_event.get("actions_attempted"),
            "investigator_evidence": episode_event.get("investigator_evidence"),
            "candidate_opportunities": episode_event.get("candidate_opportunities"),
            "candidate_opportunities_complete": episode_event.get("candidate_opportunities_complete"),
            "stop_reason": episode_event.get("stop_reason"),
            "managed_run_id": run_id,
        }
    except Exception:
        if run_id is not None:
            try:
                client.cancel_agent_run(run_id)
            except Exception:
                pass
        raise


def _evaluation_shell_context(
    client: Any, requested_scenario_id: int, expected_scenario_id: int
) -> list[int]:
    """Fetch the fraudster-only shell feature through the active run grant."""
    if requested_scenario_id != expected_scenario_id:
        raise EvaluatorDataError(
            "Learned-fraudster evaluation requested shell context for another scenario."
        )
    probe = getattr(client, "get_fraudster_authorization_probe", None)
    if not callable(probe):
        raise EvaluatorDataError(
            "Learned-fraudster evaluation requires a scenario-bound managed run authorization."
        )
    try:
        response = probe(requested_scenario_id)
    except Exception as error:
        raise EvaluatorDataError(
            "Learned-fraudster evaluation could not obtain authorized scenario shell context."
        ) from error
    if (not isinstance(response, dict)
            or response.get("status") != "authorized"
            or not isinstance(response.get("privateShellCompanyIds"), list)):
        raise EvaluatorDataError(
            "Learned-fraudster evaluation could not obtain authorized scenario shell context."
        )
    shell_ids = response["privateShellCompanyIds"]
    if (any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in shell_ids)
            or len(set(shell_ids)) != len(shell_ids)):
        raise EvaluatorDataError(
            "Learned-fraudster evaluation received malformed authorized scenario shell context."
        )
    return shell_ids


def _validate_evaluation_inputs(
    scenario_count: int,
    source_company_id: int,
    target_company_id: int,
    amount: str,
    max_actions: int,
) -> None:
    if isinstance(scenario_count, bool) or not isinstance(scenario_count, int) or scenario_count < 0:
        raise ValueError("scenario_count must be a non-negative integer.")
    for name, value in (("source_company_id", source_company_id), ("target_company_id", target_company_id)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer.")
    try:
        numeric_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("amount must be a positive finite number.") from None
    if not numeric_amount.is_finite() or numeric_amount <= 0:
        raise ValueError("amount must be a positive finite number.")


def aggregate_episode_results(
    results: list[dict[str, Any]],
    *,
    requested_count: int | None = None,
    policy_name: str = "heuristic",
) -> dict[str, Any]:
    requested = len(results) if requested_count is None else requested_count
    created = [result for result in results if result.get("creation_succeeded")]
    completed = [result for result in results if result.get("episode_class") == "completed"]
    failed = [result for result in results if result.get("episode_class") == "failed"]
    action_limit = [
        result for result in results if result.get("episode_class") == "action_limit"
    ]
    incomplete = [
        result
        for result in results
        if result.get("episode_class") not in {"completed", "failed", "action_limit"}
    ]

    objective_values = [
        result["final_state"].get("financialObjectiveAchieved")
        for result in results
        if isinstance(result.get("final_state"), dict)
        and result["final_state"].get("financialObjectiveAchieved") is not None
    ]
    action_values = [
        result["actions_attempted"]
        for result in results
        if isinstance(result.get("actions_attempted"), int)
    ]
    evidence_results = [
        result
        for result in results
        if isinstance(result.get("investigator_evidence"), dict)
    ]

    evidence_totals = {
        field: sum(
            result["investigator_evidence"].get(field, 0)
            for result in evidence_results
        )
        for field in _EVIDENCE_COUNT_FIELDS
    }

    fraudster_action_results = [
        result for result in results
        if isinstance(result.get("fraudster_action_counts"), dict)
    ]
    fraudster_action_totals = {
        action_type: sum(
            result["fraudster_action_counts"].get(action_type, 0)
            for result in fraudster_action_results
        )
        for action_type in FRAUDSTER_ACTION_TYPES
    }
    fraudster_action_totals.update({
        "missing_action_type_count": sum(
            result["fraudster_action_counts"].get("missing_action_type_count", 0)
            for result in fraudster_action_results
        ),
        "unrecognized_action_type_count": sum(
            result["fraudster_action_counts"].get("unrecognized_action_type_count", 0)
            for result in fraudster_action_results
        ),
        "successful_action_count": sum(
            result["fraudster_action_counts"].get("successful_action_count", 0)
            for result in fraudster_action_results
        ),
        "observed_episode_count": len(fraudster_action_results),
    })

    objective_achieved_count = sum(1 for value in objective_values if value is True)
    report = {
        "policy_name": policy_name,
        "requested_episode_count": requested,
        "executed_episode_count": len(results),
        "successfully_created_scenarios": len(created),
        "completed_scenarios": len(completed),
        "failed_scenarios": len(failed),
        "action_limit_episodes": len(action_limit),
        "incomplete_episodes": len(incomplete),
        "financial_simulation_outcome": {
            "objective_achieved_count": objective_achieved_count,
            "objective_observed_count": len(objective_values),
            "objective_achievement_rate": (
                objective_achieved_count / len(objective_values)
                if objective_values
                else None
            ),
            "metric_scope": "financial simulation outcome, not fraud-detection accuracy",
        },
        "objective_success_rate": (
            objective_achieved_count / len(objective_values)
            if objective_values else None
        ),
        "average_episode_length": mean(action_values) if action_values else None,
        "median_episode_length": median(action_values) if action_values else None,
        "actions_attempted": {
            "mean": mean(action_values) if action_values else None,
            "median": median(action_values) if action_values else None,
            "observed_episode_count": len(action_values),
        },
        "investigator_evidence_aggregate": {
            **evidence_totals,
            "observed_episode_count": len(evidence_results),
        },
        "fraudster_action_counts_aggregate": fraudster_action_totals,
        "scenario_ids": [
            result["scenario_id"]
            for result in results
            if result.get("scenario_id") is not None
        ],
        "episodes": results,
    }
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    def positive_int(value: str) -> int:
        parsed = int(value)
        if parsed <= 0:
            raise argparse.ArgumentTypeError("must be positive")
        return parsed

    def nonnegative_int(value: str) -> int:
        parsed = int(value)
        if parsed < 0:
            raise argparse.ArgumentTypeError("must be non-negative")
        return parsed

    def positive_amount(value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            raise argparse.ArgumentTypeError("must be a positive finite number") from None
        if not parsed.is_finite() or parsed <= 0:
            raise argparse.ArgumentTypeError("must be a positive finite number")
        return value

    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=nonnegative_int, default=1)
    parser.add_argument("--source-company-id", type=positive_int, required=True)
    parser.add_argument("--target-company-id", type=positive_int, required=True)
    parser.add_argument("--amount", type=positive_amount, required=True)
    parser.add_argument("--max-actions", type=positive_int, default=20)
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue creating independent scenarios after a failed episode.",
    )
    parser.add_argument(
        "--detection-metrics",
        action="store_true",
        help=(
            "Enable offline source/target baseline and discovered-candidate "
            "metrics using the read-only evaluator database."
        ),
    )
    parser.add_argument(
        "--policy",
        choices=("random", "heuristic", "learned", "learned_investigator"),
        default="heuristic",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fraudster-checkpoint")
    parser.add_argument("--investigator-checkpoint")
    parser.add_argument("--allow-legacy-checkpoints", action="store_true")
    parser.add_argument(
        "--report-file",
        type=Path,
        help="Write the completed JSON report to this path (fails if it already exists).",
    )
    parser.add_argument(
        "--overwrite-report",
        action="store_true",
        help="Allow replacing the report file named by --report-file.",
    )
    args = parser.parse_args(argv)
    if args.report_file is not None:
        args.report_file = args.report_file.expanduser()
    if args.overwrite_report and args.report_file is None:
        parser.error("--overwrite-report requires --report-file.")
    if (args.report_file is not None and args.report_file.exists()
            and not args.overwrite_report):
        parser.error(
            f"Report destination already exists: {args.report_file}. "
            "Choose another path or pass --overwrite-report explicitly."
        )
    return args


def _serialize_report(report: dict[str, Any]) -> str:
    """Serialize one deterministic, strict JSON representation for stdout and file."""
    return json.dumps(
        report,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    )


def _write_report_file(
    report: dict[str, Any],
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> None:
    """Atomically publish a complete report without implicit replacement."""
    report_json = _serialize_report(report) + "\n"
    path = Path(destination).expanduser()
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Report destination already exists: {path}. "
            "Choose another path or pass --overwrite-report explicitly."
        )
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(report_json)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                # Linking the same-directory temporary is atomic and fails if
                # another process created the destination after preflight.
                os.link(temporary, path)
            except FileExistsError:
                raise FileExistsError(
                    f"Report destination already exists: {path}. "
                    "Choose another path or pass --overwrite-report explicitly."
                ) from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _print_human_summary(report: dict[str, Any]) -> None:
    outcome = report["financial_simulation_outcome"]
    print(
        "Evaluation summary: "
        f"requested={report['requested_episode_count']}, "
        f"created={report['successfully_created_scenarios']}, "
        f"completed={report['completed_scenarios']}, "
        f"failed={report['failed_scenarios']}, "
        f"action_limit={report['action_limit_episodes']}, "
        f"objective_rate={outcome['objective_achievement_rate']!r}"
    )
    print(_serialize_report(report))


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    evaluation = run_evaluation(
        CatchMeIfYouCanApiClient(),
        scenario_count=args.scenarios,
        source_company_id=args.source_company_id,
        target_company_id=args.target_company_id,
        amount=args.amount,
        max_actions=args.max_actions,
        continue_on_failure=args.continue_on_failure,
        detection_metrics=args.detection_metrics,
        policy_name=args.policy,
        seed=args.seed,
        fraudster_checkpoint=args.fraudster_checkpoint,
        investigator_checkpoint=args.investigator_checkpoint,
        allow_legacy_checkpoints=args.allow_legacy_checkpoints,
    )
    if args.report_file is not None:
        _write_report_file(
            evaluation,
            args.report_file,
            overwrite=args.overwrite_report,
        )
    _print_human_summary(evaluation)
    return evaluation


if __name__ == "__main__":
    main()
