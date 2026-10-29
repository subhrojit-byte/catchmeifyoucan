import json
import hashlib
import unittest
import copy
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import evaluate
from client import CatchMeIfYouCanApiError
from fraudster_bot import FraudsterBot
from q_learning import QLearningAgent, checkpoint_compatibility
from rl_policies import RLInvestigatorPolicy
from state_abstraction import legal_fraudster_actions
from ground_truth import EvaluatorDataError


def versioned_learner(role, seed):
    return QLearningAgent(
        seed=seed,
        compatibility=checkpoint_compatibility(role),
    )


def episode_result(
    scenario_id,
    *,
    episode_class="completed",
    objective=True,
    actions=2,
    evidence=None,
):
    return {
        "scenario_id": scenario_id,
        "initial_source_company_id": 1,
        "initial_target_company_id": 2,
        "final_state": (
            {"status": "COMPLETED", "financialObjectiveAchieved": objective}
            if objective is not None
            else None
        ),
        "actions_attempted": actions,
        "stop_reason": "scenario terminated" if episode_class == "completed" else episode_class,
        "episode_class": episode_class,
        "investigator_evidence": evidence,
        "creation_succeeded": True,
    }


class ManagedEvaluationClient:
    """Offline stand-in for AgentRun's per-scenario grant lifecycle."""
    def __init__(self, *, mismatch_started_scenario=False, authorization_denied=False,
                 poll_error=False):
        self.created = 0
        self.mismatch_started_scenario = mismatch_started_scenario
        self.authorization_denied = authorization_denied
        self.poll_error = poll_error
        self.started_scenarios = []
        self.probed_scenarios = []
        self.completed_runs = []
        self.cancelled_runs = []
        self.continued_runs = []
        self.final_statuses = {}

    def create_scenario(self, **kwargs):
        self.created += 1
        return {"id": 100 + self.created}

    def start_agent_run(self, scenario_id):
        self.started_scenarios.append(scenario_id)
        return {"runId": f"run-{scenario_id}",
                "scenarioId": scenario_id - 1 if self.mismatch_started_scenario else scenario_id,
                "status": "PAUSED"}

    def continue_agent_run(self, run_id):
        self.continued_runs.append(run_id)
        scenario_id = int(run_id.split("-")[-1])
        return {"runId": run_id, "scenarioId": scenario_id, "status": "RUNNING"}

    def get_agent_run(self, run_id):
        if self.poll_error:
            raise RuntimeError("poll failed")
        scenario_id = int(run_id.split("-")[-1])
        if self.authorization_denied:
            self.probed_scenarios.append(scenario_id)
            self.final_statuses[run_id] = "FAILED"
            return {"runId": run_id, "scenarioId": scenario_id, "status": "FAILED",
                    "message": "authorization denied", "events": []}
        self.probed_scenarios.append(scenario_id)
        self.completed_runs.append((run_id, scenario_id))
        self.final_statuses[run_id] = "COMPLETED"
        return {"runId": run_id, "scenarioId": scenario_id, "status": "COMPLETED",
                "events": [{"event_type": "episode_result", "scenario_id": scenario_id,
                            "episode_class": "completed", "actions_attempted": 2,
                            "investigator_evidence": {}, "candidate_opportunities": [],
                            "candidate_opportunities_complete": True,
                            "final_state": {"id": scenario_id, "status": "COMPLETED",
                                             "financialObjectiveAchieved": True}}]}

    def cancel_agent_run(self, run_id):
        self.cancelled_runs.append(run_id)

    def get_fraudster_authorization_probe(self, scenario_id):
        self.probed_scenarios.append(scenario_id)
        return {"status": "authorized", "privateShellCompanyIds": [scenario_id + 1000]}


class EvaluationTest(unittest.TestCase):
    def test_managed_investigator_checkpoint_artifact_loads_with_current_contract(self):
        investigator_path = Path(__file__).with_name(
            "investigator-managed-run-29b5f61c-d747-46b6-ae22-46a141ac5cb9.json"
        )

        factory = evaluate.build_policy_factory(
            "learned_investigator", investigator_checkpoint=investigator_path
        )
        policies = factory(0)

        self.assertEqual(
            checkpoint_compatibility("investigator"),
            policies[1].learner._learner.compatibility,
        )
        self.assertEqual("validated", factory.checkpoint_provenance[0]["compatibility_status"])

    def test_learned_investigator_evaluation_uses_only_compatible_investigator_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("investigator", 17).save(investigator_path)
            expected_hash = hashlib.sha256(investigator_path.read_bytes()).hexdigest()

            factory = evaluate.build_policy_factory(
                "learned_investigator", investigator_checkpoint=investigator_path
            )
            provenance = factory.checkpoint_provenance[0]
            policies = factory(0)

        self.assertIsInstance(policies[0], FraudsterBot)
        self.assertIsInstance(policies[1], RLInvestigatorPolicy)
        self.assertEqual(
            checkpoint_compatibility("investigator"),
            policies[1].learner._learner.compatibility,
        )
        self.assertEqual("investigator", provenance["role"])
        self.assertEqual(investigator_path.name, provenance["file_name"])
        self.assertEqual(expected_hash, provenance["sha256"])
        self.assertEqual("validated", provenance["compatibility_status"])
        self.assertEqual(0, provenance["training_steps"])

    def test_learned_investigator_evaluation_rejects_incompatible_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            investigator_path = Path(directory) / "investigator.json"
            bad = versioned_learner("investigator", 17)
            bad.compatibility["legal_action_schema_version"] = "old-actions"
            bad.save(investigator_path)

            with self.assertRaisesRegex(ValueError, "legal_action_schema_version"):
                evaluate.build_policy_factory(
                    "learned_investigator", investigator_checkpoint=investigator_path
                )

    def test_cli_report_file_matches_stdout_json_and_preserves_episode_details(self):
        report = evaluate.aggregate_episode_results([], requested_count=0)
        report.update({
            "episodes": [{
                "scenario_id": 190,
                "episode_class": "completed",
                "final_state": {
                    "status": "MAX_TURNS_REACHED",
                    "financialObjectiveAchieved": True,
                },
                "actions_attempted": 7,
                "candidate_opportunities_complete": True,
                "candidate_opportunities": [{
                    "scenario_id": 190,
                    "decision_index": 0,
                    "step": 1,
                    "investigator_actions_remaining": 3,
                    "candidate_company_ids": [1, 2],
                }],
            }],
            "detection_metrics": {"metric_scope": "source_target_baseline", "tp": 1},
            "discovered_candidate_metrics": {
                "metric_scope": "discovered_candidate_population", "candidate_count": 2,
            },
            "financial_simulation_outcome": {"objective_achievement_rate": 1.0},
        })
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "nested" / "evaluation.json"
            stdout = StringIO()
            with patch.object(evaluate, "run_evaluation", return_value=report), \
                    patch.object(evaluate, "CatchMeIfYouCanApiClient", return_value=object()), \
                    redirect_stdout(stdout):
                returned = evaluate.main([
                    "--source-company-id", "1", "--target-company-id", "2",
                    "--amount", "10", "--report-file", str(report_path),
                ])

            output_json = "\n".join(stdout.getvalue().splitlines()[1:])
            file_json = report_path.read_text(encoding="utf-8").rstrip("\n")
            self.assertEqual(report, returned)
            self.assertEqual(output_json, file_json)
            self.assertEqual(report, json.loads(file_json))
            self.assertEqual("MAX_TURNS_REACHED", json.loads(file_json)["episodes"][0]["final_state"]["status"])
            self.assertIn("candidate_opportunities", json.loads(file_json)["episodes"][0])

    def test_cli_report_refuses_existing_file_without_overwrite_before_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "existing.json"
            report_path.write_bytes(b"keep this report")
            with patch.object(evaluate, "run_evaluation") as run_evaluation:
                with self.assertRaises(SystemExit):
                    evaluate.main([
                        "--source-company-id", "1", "--target-company-id", "2",
                        "--amount", "10", "--report-file", str(report_path),
                    ])
            run_evaluation.assert_not_called()
            self.assertEqual(b"keep this report", report_path.read_bytes())

    def test_cli_report_overwrite_requires_explicit_option(self):
        report = evaluate.aggregate_episode_results([], requested_count=0)
        report["episodes"] = []
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "evaluation.json"
            report_path.write_text("old", encoding="utf-8")
            stdout = StringIO()
            with patch.object(evaluate, "run_evaluation", return_value=report), \
                    patch.object(evaluate, "CatchMeIfYouCanApiClient", return_value=object()), \
                    redirect_stdout(stdout):
                evaluate.main([
                    "--source-company-id", "1", "--target-company-id", "2",
                    "--amount", "10", "--report-file", str(report_path),
                    "--overwrite-report",
                ])
            self.assertEqual(report, json.loads(report_path.read_text(encoding="utf-8")))

    def test_cli_does_not_create_report_directories_when_evaluation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "not-created" / "evaluation.json"
            with patch.object(evaluate, "run_evaluation", side_effect=RuntimeError("evaluation failed")), \
                    patch.object(evaluate, "CatchMeIfYouCanApiClient", return_value=object()):
                with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
                    evaluate.main([
                        "--source-company-id", "1", "--target-company-id", "2",
                        "--amount", "10", "--report-file", str(report_path),
                    ])
            self.assertFalse(report_path.parent.exists())

    def test_cli_preserves_existing_report_when_evaluation_validation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "existing.json"
            report_path.write_bytes(b"previous complete report")
            with patch.object(
                evaluate,
                "run_evaluation",
                side_effect=EvaluatorDataError("metric validation failed"),
            ), patch.object(evaluate, "CatchMeIfYouCanApiClient", return_value=object()):
                with self.assertRaisesRegex(EvaluatorDataError, "metric validation failed"):
                    evaluate.main([
                        "--source-company-id", "1", "--target-company-id", "2",
                        "--amount", "10", "--report-file", str(report_path),
                        "--overwrite-report",
                    ])
            self.assertEqual(b"previous complete report", report_path.read_bytes())

    def test_overwrite_report_option_requires_report_file(self):
        with self.assertRaises(SystemExit):
            evaluate._parse_args([
                "--source-company-id", "1", "--target-company-id", "2",
                "--amount", "10", "--overwrite-report",
            ])

    def test_policy_factory_selects_heuristic_and_random_policies(self):
        heuristic = evaluate.build_policy_factory("heuristic")(0)
        self.assertEqual(2, len(heuristic))
        random_policies = evaluate.build_policy_factory("random", seed=7)(0)
        state = {
            "status": "ACTIVE",
            "turn": "FRAUDSTER",
            "positions": [{"id": 1, "amount": "10", "company": {"id": 10}}],
        }
        action = random_policies[0].choose_action(state)
        self.assertIn(action, legal_fraudster_actions(state))

    def test_random_investigator_selection_is_legal_and_seeded(self):
        state = {
            "id": 1,
            "status": "ACTIVE",
            "turn": "INVESTIGATOR",
            "investigatorActionsRemaining": 3,
            "sourceCompany": {"id": 10},
            "targetCompany": {"id": 11},
            "positions": [],
        }
        first = evaluate.build_policy_factory("random", seed=9)(0)[1]
        second = evaluate.build_policy_factory("random", seed=9)(0)[1]
        first_action = first.choose_action(state)
        second_action = second.choose_action(state)
        self.assertEqual(first_action, second_action)
        self.assertIn(first_action, first.legal_actions(state))

    def test_learned_factory_is_read_only_and_requires_checkpoints(self):
        with self.assertRaises(ValueError):
            evaluate.build_policy_factory("learned")
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("fraudster", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)
            factory = evaluate.build_policy_factory(
                "learned",
                fraudster_checkpoint=fraudster_path,
                investigator_checkpoint=investigator_path,
            )
            policies = factory(0)
            before = copy.deepcopy(policies[0].learner._learner.q_values)
            state = {
                "status": "ACTIVE",
                "turn": "FRAUDSTER",
                "positions": [{"id": 1, "amount": "10", "company": {"id": 10}}],
            }
            policies[0].choose_action(state)
            self.assertEqual(before, policies[0].learner._learner.q_values)

    def test_learned_evaluation_does_not_mutate_loaded_q_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("fraudster", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)

            client = ManagedEvaluationClient()
            report = evaluate.run_evaluation(
                    client,
                    scenario_count=1,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    policy_name="learned",
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )
            self.assertEqual(1, report["completed_scenarios"])

    def test_learned_evaluation_fetches_shell_context_for_each_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("fraudster", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)

            client = ManagedEvaluationClient()
            report = evaluate.run_evaluation(
                client, scenario_count=2, source_company_id=1,
                target_company_id=2, amount="10", policy_name="learned",
                fraudster_checkpoint=fraudster_path,
                investigator_checkpoint=investigator_path,
            )

            self.assertEqual([101, 102], client.started_scenarios)
            self.assertEqual([101, 102], client.probed_scenarios)
            self.assertEqual([("run-101", 101), ("run-102", 102)], client.completed_runs)
            self.assertEqual(["run-101", "run-102"], client.continued_runs)
            self.assertEqual(2, report["completed_scenarios"])
            self.assertEqual([101, 102], report["scenario_ids"])
            self.assertEqual("fraud_path_shell_detection", report["fraud_path_detection_metrics"]["metric_scope"])

    def test_learned_evaluation_cancels_mismatched_grant_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("fraudster", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)

            client = ManagedEvaluationClient(mismatch_started_scenario=True)
            report = evaluate.run_evaluation(
                client, scenario_count=1, source_company_id=1,
                target_company_id=2, amount="10", policy_name="learned",
                fraudster_checkpoint=fraudster_path,
                investigator_checkpoint=investigator_path,
            )

            self.assertEqual(1, report["failed_scenarios"])
            self.assertEqual(["run-101"], client.cancelled_runs)
            self.assertIn("mismatched scenario", report["episodes"][0]["error"])

    def test_managed_authorization_denial_fails_episode_and_backend_run_is_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("fraudster", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)
            client = ManagedEvaluationClient(authorization_denied=True)
            report = evaluate.run_evaluation(
                client, scenario_count=1, source_company_id=1,
                target_company_id=2, amount="10", policy_name="learned",
                fraudster_checkpoint=fraudster_path,
                investigator_checkpoint=investigator_path,
            )
            self.assertEqual(1, report["failed_scenarios"])
            self.assertEqual([101], client.probed_scenarios)
            self.assertEqual("FAILED", client.final_statuses["run-101"])

    def test_shell_context_provider_fails_closed_on_denial_or_scenario_mismatch(self):
        class Client:
            def __init__(self, response):
                self.response = response

            def get_fraudster_authorization_probe(self, scenario_id):
                return self.response

        with self.assertRaisesRegex(EvaluatorDataError, "another scenario"):
            evaluate._evaluation_shell_context(Client({"status": "authorized",
                                                        "privateShellCompanyIds": []}), 102, 101)
        with self.assertRaisesRegex(EvaluatorDataError, "authorized scenario shell context"):
            evaluate._evaluation_shell_context(Client({"status": "denied",
                                                        "privateShellCompanyIds": []}), 101, 101)

    def test_managed_evaluation_cleans_up_run_after_poll_exception(self):
        client = ManagedEvaluationClient(poll_error=True)
        with self.assertRaisesRegex(RuntimeError, "poll failed"):
            evaluate._run_managed_learned_scenario(client, 101)
        self.assertEqual(["run-101"], client.cancelled_runs)

    def test_legacy_checkpoint_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            QLearningAgent(seed=1).save(fraudster_path)
            QLearningAgent(seed=2).save(investigator_path)
            with self.assertRaisesRegex(ValueError, "legacy format-1"):
                evaluate.build_policy_factory(
                    "learned",
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )
            factory = evaluate.build_policy_factory(
                "learned",
                fraudster_checkpoint=fraudster_path,
                investigator_checkpoint=investigator_path,
                allow_legacy_checkpoints=True,
            )
            self.assertEqual(2, len(factory(0)))

    def test_checkpoint_role_and_schema_mismatches_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            versioned_learner("investigator", 1).save(fraudster_path)
            versioned_learner("investigator", 2).save(investigator_path)
            with self.assertRaisesRegex(ValueError, "mismatched fields: .*policy_role"):
                evaluate.build_policy_factory(
                    "learned",
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )
            versioned_learner("fraudster", 1).save(fraudster_path)
            bad = versioned_learner("investigator", 2)
            bad.compatibility["legal_action_schema_version"] = "old-schema"
            bad.save(investigator_path)
            with self.assertRaisesRegex(ValueError, "mismatched fields: legal_action_schema_version"):
                evaluate.build_policy_factory(
                    "learned",
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )

    def test_checkpoint_rejects_every_changed_compatibility_field(self):
        mismatches = (
            "policy_role", "state_abstraction_version", "legal_action_schema_version",
            "observation_reward_contract_version", "private_shell_knowledge_features",
        )
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            for field in mismatches:
                fraudster = versioned_learner("fraudster", 1)
                fraudster.compatibility[field] = "incompatible"
                fraudster.save(fraudster_path)
                versioned_learner("investigator", 2).save(investigator_path)
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, field):
                        evaluate.build_policy_factory(
                            "learned",
                            fraudster_checkpoint=fraudster_path,
                            investigator_checkpoint=investigator_path,
                        )

    def test_malformed_checkpoint_compatibility_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            versioned_learner("fraudster", 1).save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["compatibility"] = {"policy_role": "fraudster"}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "compatibility metadata"):
                QLearningAgent.load(path)

    def test_evaluation_inputs_reject_invalid_values_before_client_use(self):
        client = type("Client", (), {
            "create_scenario": lambda self, **kwargs: self.fail("API should not be called")
        })()
        for kwargs in (
            {"source_company_id": 0},
            {"target_company_id": 0},
            {"amount": "0"},
            {"max_actions": 0},
        ):
            values = {
                "scenario_count": 1,
                "source_company_id": 1,
                "target_company_id": 2,
                "amount": "10",
                "max_actions": 20,
            }
            values.update(kwargs)
            with self.assertRaises(ValueError):
                evaluate.run_evaluation(client, **values)

    def test_common_report_fields_include_policy_and_episode_lengths(self):
        report = evaluate.aggregate_episode_results(
            [episode_result(1, objective=True, actions=4)],
            policy_name="random",
        )
        self.assertEqual("random", report["policy_name"])
        self.assertEqual(1.0, report["objective_success_rate"])
        self.assertEqual(4, report["average_episode_length"])
        self.assertEqual(4, report["median_episode_length"])

    def test_detection_report_is_separate_from_episode_outcomes(self):
        report = evaluate.run_evaluation(
            type("Client", (), {})(),
            scenario_count=0,
            source_company_id=1,
            target_company_id=2,
            amount="10",
            detection_metrics=False,
        )
        self.assertIn("financial_simulation_outcome", report)
        self.assertNotIn("detection_metrics", report)

    def test_detection_report_uses_declared_source_target_candidates(self):
        class Client:
            def create_scenario(self, **kwargs):
                return {"id": 10}

        class Candidate:
            def __init__(self, scenario_id, company_id, shell_company, flagged,
                         fraud_path_involved=False):
                self.scenario_id = scenario_id
                self.company_id = company_id
                self.shell_company = shell_company
                self.flagged = flagged
                self.fraud_path_involved = fraud_path_involved

        class Reader:
            def __init__(self):
                self.scenario_ids = None

            def read_candidates(self, scenario_ids):
                self.scenario_ids = list(scenario_ids)
                return [Candidate(10, 1, True, True), Candidate(10, 2, False, False)]

            def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
                self.discovered = (list(scenario_ids), candidate_ids_by_scenario)
                return [Candidate(10, 1, True, True, True),
                        Candidate(10, 2, False, False, True),
                        Candidate(10, 3, True, True, False)]

        reader = Reader()

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            result_collector.update(episode_result(scenario_id))
            result_collector["candidate_opportunities"] = [
                {
                    "scenario_id": scenario_id,
                    "decision_index": 0,
                    "step": 0,
                    "investigator_actions_remaining": 3,
                    "candidate_company_ids": [1, 2, 3, 3],
                },
                {
                    "scenario_id": scenario_id,
                    "decision_index": 1,
                    "step": 1,
                    "investigator_actions_remaining": 2,
                    "candidate_company_ids": [2, 3],
                },
            ]
            result_collector["candidate_opportunities_complete"] = True
            return result_collector["final_state"]

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            report = evaluate.run_evaluation(
                Client(),
                scenario_count=1,
                source_company_id=1,
                target_company_id=2,
                amount="10",
                detection_metrics=True,
                ground_truth_reader=reader,
            )

        self.assertEqual([10], reader.scenario_ids)
        self.assertEqual("scenario source and target companies",
                         report["detection_metrics"]["candidate_population"])
        self.assertEqual("source_target_baseline", report["detection_metrics"]["metric_scope"])
        self.assertEqual(1, report["detection_metrics"]["tp"])
        self.assertEqual(1, report["detection_metrics"]["tn"])
        self.assertEqual(1.0, report["detection_metrics"]["accuracy"])
        self.assertEqual(0.0, report["detection_metrics"]["false_positive_rate"])
        self.assertNotIn("source_destination_identification_accuracy", report["detection_metrics"])
        self.assertNotIn("source_identification_accuracy", report["detection_metrics"])
        self.assertNotIn("destination_identification_accuracy", report["detection_metrics"])
        self.assertNotIn("source_destination_identification_accuracy", report["episodes"][0]["detection_metrics"])
        serialized_report = json.dumps(report)
        self.assertNotIn('"shell_company":', serialized_report)
        self.assertNotIn('"flagCorrect":', serialized_report)
        self.assertEqual("discovered_candidate_population", report["discovered_candidate_metrics"]["metric_scope"])
        self.assertEqual(3, report["discovered_candidate_metrics"]["candidate_count"])
        self.assertEqual(2, report["discovered_candidate_metrics"]["tp"])
        self.assertEqual(1, report["fraud_path_detection_metrics"]["tp"])
        self.assertEqual(1, report["fraud_path_detection_metrics"]["fp"])
        self.assertEqual(1, report["fraud_path_detection_metrics"]["tn"])
        self.assertEqual("fraud_path_shell_detection",
                         report["fraud_path_detection_metrics"]["metric_scope"])
        self.assertIn("origin FRAUDSTER_ACTION",
                      report["fraud_path_detection_metrics"]["label_definition"])
        self.assertEqual("fraud_path_shell_detection",
                         report["episodes"][0]["fraud_path_detection_metrics"]["metric_scope"])
        self.assertEqual(([10], {10: {1, 2, 3}}), reader.discovered)

    def test_posthoc_detection_metrics_reject_missing_ground_truth(self):
        episode = episode_result(10)
        episode.update({
            "candidate_opportunities_complete": True,
            "candidate_opportunities": [],
        })

        class Reader:
            def read_candidates(self, scenario_ids):
                raise EvaluatorDataError("A candidate company is missing a label.")

        with self.assertRaisesRegex(EvaluatorDataError, "missing a label"):
            evaluate.attach_detection_metrics(
                {"episodes": [episode]}, [episode], Reader()
            )

    def test_posthoc_detection_metrics_require_complete_terminal_episodes(self):
        episode = episode_result(10, episode_class="action_limit", objective=None)
        with self.assertRaisesRegex(EvaluatorDataError, "all created episodes to complete"):
            evaluate.attach_detection_metrics({"episodes": [episode]}, [episode], object())

    def test_incomplete_or_malformed_candidate_snapshots_fail_before_ground_truth(self):
        class Client:
            def create_scenario(self, **kwargs):
                return {"id": 10}

        class Reader:
            def __init__(self):
                self.calls = []

            def read_candidates(self, scenario_ids):
                self.calls.append("baseline")
                return []

            def read_discovered_candidates(self, scenario_ids, candidates):
                self.calls.append("discovered")
                return []

        reader = Reader()

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            result_collector.update(episode_result(scenario_id))
            result_collector["candidate_opportunities_complete"] = False

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            with self.assertRaisesRegex(EvaluatorDataError, "missing validated legal flag-candidate"):
                evaluate.run_evaluation(
                    Client(), scenario_count=1, source_company_id=1,
                    target_company_id=2, amount="10", detection_metrics=True,
                    ground_truth_reader=reader,
                )
        self.assertEqual([], reader.calls)

    def test_invalid_terminal_status_is_failed_and_never_queries_ground_truth(self):
        class Client:
            def create_scenario(self, **kwargs):
                return {"id": 10}

        class Reader:
            def __init__(self):
                self.calls = []

            def read_candidates(self, scenario_ids):
                self.calls.append(("baseline", list(scenario_ids)))
                return []

        reader = Reader()

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            result_collector.update(episode_result(scenario_id))
            result_collector["final_state"]["status"] = "BROKEN"

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            with self.assertRaisesRegex(EvaluatorDataError, "all created episodes to complete"):
                report = evaluate.run_evaluation(
                    Client(), scenario_count=1, source_company_id=1,
                    target_company_id=2, amount="10", detection_metrics=True,
                    ground_truth_reader=reader,
                )

        self.assertEqual([], reader.calls)

    def test_run_episode_accepts_only_explicit_terminal_statuses(self):
        from run_episode import run_episode

        class Client:
            def __init__(self, terminal_status):
                self.calls = 0
                self.terminal_status = terminal_status

            def get_scenario(self, scenario_id):
                self.calls += 1
                state = {
                    "id": scenario_id,
                    "status": "ACTIVE" if self.calls == 1 else self.terminal_status,
                    "turn": "INVESTIGATOR",
                    "investigatorActionsRemaining": 3 if self.calls == 1 else 2,
                    "sourceCompany": {"id": 1, "companyName": "source"},
                    "targetCompany": {"id": 2, "companyName": "target"},
                    "positions": [{"id": 3, "company": {"id": 1}, "amount": 1}],
                }
                return state

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return {"directorInvestigation": {"directors": []}}

        for terminal_status in ("COMPLETED", "MAX_TURNS_REACHED"):
            with self.subTest(status=terminal_status):
                result = {}
                state = run_episode(
                    Client(terminal_status), scenario_id=10,
                    max_actions=1, result_collector=result,
                )
                self.assertEqual(terminal_status, state["status"])
                self.assertEqual("completed", result["episode_class"])

    def test_run_episode_rejects_malformed_status_and_marks_episode_failed(self):
        from run_episode import run_episode

        class Client:
            def get_scenario(self, scenario_id):
                return {"id": scenario_id, "status": None}

        result = {}
        with self.assertRaisesRegex(RuntimeError, "Unexpected or missing scenario status"):
            run_episode(Client(), scenario_id=10, result_collector=result)
        self.assertEqual("failed", result["episode_class"])
        self.assertEqual("invalid_scenario_status", result["failure_stage"])

    def test_run_episode_rejects_unknown_terminal_status_after_action(self):
        from run_episode import run_episode

        class Client:
            def __init__(self):
                self.get_calls = 0

            def get_scenario(self, scenario_id):
                self.get_calls += 1
                return {
                    "id": scenario_id,
                    "status": "ACTIVE" if self.get_calls == 1 else "COMPLETED_WITH_WARNING",
                    "turn": "INVESTIGATOR",
                    "investigatorActionsRemaining": 3,
                    "sourceCompany": {"id": 1, "companyName": "source"},
                    "targetCompany": {"id": 2, "companyName": "target"},
                    "positions": [{"id": 3, "company": {"id": 1}, "amount": 1}],
                }

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return {}

        result = {}
        with self.assertRaisesRegex(RuntimeError, "COMPLETED_WITH_WARNING"):
            run_episode(Client(), scenario_id=10, result_collector=result)
        self.assertEqual("failed", result["episode_class"])
        self.assertEqual("invalid_scenario_status", result["failure_stage"])

    def test_runner_captures_decision_time_candidates_discovered_by_directors_and_trace(self):
        from investigator_bot import InvestigatorBot
        from rl_policies import RLInvestigatorPolicy
        from run_episode import run_episode

        scenario_id = 190

        class ScriptedInvestigator(RLInvestigatorPolicy):
            def __init__(self):
                super().__init__(versioned_learner("investigator", 19))
                self.script = [
                    {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 1},
                    {"action_type": "TRACE_TRANSACTION", "transaction_id": 70},
                    {"action_type": "FLAG_COMPANY", "company_id": 4},
                    {"action_type": "FLAG_COMPANY", "company_id": 5},
                ]

            def choose_action(self, state):
                decision = self.script.pop(0)
                self.assert_legal(state, decision)
                return decision

            def assert_legal(self, state, decision):
                if decision not in self.legal_actions(state):
                    raise AssertionError(f"scripted action was illegal: {decision}")

        class ScriptedFraudster:
            def choose_action(self, state):
                return {"action_type": "DIRECT_TRANSFER", "source_position_id": 10,
                        "targets": [{"company_id": 2, "amount": 1}]}

        def scenario(turn="INVESTIGATOR", remaining=3, status="ACTIVE"):
            return {
                "id": scenario_id, "status": status, "turn": turn, "step": 0,
                "investigatorActionsRemaining": remaining,
                "sourceCompany": {"id": 1}, "targetCompany": {"id": 2},
                "positions": [{"id": 10, "company": {"id": 1}, "amount": 10}],
            }

        class Client:
            def __init__(self):
                self.states = [scenario()]
                self.action_count = 0
                self.history_calls = []

            def get_scenario(self, requested_id):
                if requested_id != scenario_id:
                    raise AssertionError("scenario ID changed")
                return self.states.pop(0)

            def get_scenario_transactions(self, requested_id):
                self.history_calls.append(requested_id)
                return [{"id": 70, "scenarioId": scenario_id,
                         "sourceCompany": {"id": 1}, "destinationCompany": {"id": 2},
                         "amount": "1.00"}]

            def submit_investigator_action(self, **kwargs):
                self.action_count += 1
                if self.action_count == 1:
                    response = {"directorInvestigation": {
                        "company": {"id": 1}, "directors": [{"directorId": 9,
                         "associatedCompanies": [{"id": 3}]}]}}
                elif self.action_count == 2:
                    response = {"transactionTrace": {
                        "id": 70, "scenarioId": scenario_id,
                        "sourceCompany": {"id": 4}, "destinationCompany": {"id": 5}}}
                else:
                    response = {}
                if self.action_count == 1:
                    self.states.append(scenario(remaining=2))
                elif self.action_count == 2:
                    self.states.append(scenario(remaining=1))
                elif self.action_count == 3:
                    self.states.append(scenario(turn="FRAUDSTER", remaining=0))
                else:
                    self.states.append(scenario(turn="INVESTIGATOR", remaining=3))
                return response

            def create_fraudster_action(self, **kwargs):
                return {"id": 901}

            def execute_fraudster_action(self, action_id):
                self.states.append(scenario(turn="INVESTIGATOR", remaining=3))

        client = Client()
        # The final scripted flag ends the scenario after four investigator
        # decisions (three actions, one fraudster turn, then another decision).
        original_submit = client.submit_investigator_action

        def submit(**kwargs):
            response = original_submit(**kwargs)
            if client.action_count == 4:
                client.states[-1] = scenario(turn="INVESTIGATOR", remaining=2, status="COMPLETED")
            return response

        client.submit_investigator_action = submit
        # Six authoritative reads: initial state and one refresh after each action.
        client.states.extend([scenario(remaining=2), scenario(remaining=1),
                              scenario(turn="FRAUDSTER", remaining=0),
                              scenario(turn="INVESTIGATOR", remaining=3),
                              scenario(turn="INVESTIGATOR", remaining=2, status="COMPLETED")])
        # Keep the queued states after the initial read; each action appends the
        # next authoritative state to the queue.
        result = {}
        run_episode(
            client, scenario_id=scenario_id, max_actions=10,
            result_collector=result, fraudster_policy=ScriptedFraudster(),
            investigator_policy=ScriptedInvestigator(),
        )
        opportunities = result["candidate_opportunities"]
        self.assertEqual([scenario_id] * 4, [item["scenario_id"] for item in opportunities])
        self.assertEqual([0, 1, 2, 3], [item["decision_index"] for item in opportunities])
        self.assertEqual([1, 2], opportunities[0]["candidate_company_ids"])
        self.assertIn(3, opportunities[1]["candidate_company_ids"])
        self.assertTrue({4, 5}.issubset(opportunities[2]["candidate_company_ids"]))
        self.assertTrue({3, 5}.issubset(opportunities[3]["candidate_company_ids"]))
        # A previously flagged company is no longer a legal flag choice.
        self.assertNotIn(4, opportunities[3]["candidate_company_ids"])
        self.assertTrue(result["candidate_opportunities_complete"])
        self.assertEqual([scenario_id] * 5, client.history_calls)

    def test_runner_excludes_candidates_revealed_only_by_final_action(self):
        from run_episode import run_episode

        class Policy:
            def legal_actions(self, state):
                return [{"action_type": "FLAG_COMPANY", "company_id": 1}]

            def choose_action(self, state):
                return {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 1}

            def sanitize_action_response(self, response, **kwargs):
                return response

            def mark_action_completed(self, decision, response):
                pass

        class Client:
            def __init__(self):
                self.calls = 0

            def get_scenario(self, scenario_id):
                self.calls += 1
                return {
                    "id": scenario_id, "status": "ACTIVE" if self.calls == 1 else "COMPLETED",
                    "turn": "INVESTIGATOR", "investigatorActionsRemaining": 3,
                    "sourceCompany": {"id": 1}, "targetCompany": {"id": 2}, "positions": [],
                }

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return {"directorInvestigation": {"company": {"id": 1}, "directors": [
                    {"directorId": 9, "associatedCompanies": [{"id": 99}]}
                ]}}

        result = {}
        run_episode(Client(), scenario_id=55, max_actions=2,
                    result_collector=result, investigator_policy=Policy())
        self.assertEqual([[1]], [item["candidate_company_ids"] for item in result["candidate_opportunities"]])
        self.assertNotIn(99, result["candidate_opportunities"][0]["candidate_company_ids"])

    def test_learned_decisions_are_repeatable_and_checkpoint_files_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            fraudster = versioned_learner("fraudster", 42)
            investigator = versioned_learner("investigator", 43)
            fraudster.epsilon = 1.0
            investigator.epsilon = 1.0
            fraudster.save(fraudster_path)
            investigator.save(investigator_path)
            saved_bytes = (fraudster_path.read_bytes(), investigator_path.read_bytes())

            def decisions(seed):
                factory = evaluate.build_policy_factory(
                    "learned", seed=seed,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )
                fraud_state = {
                    "id": 1, "status": "ACTIVE", "turn": "FRAUDSTER",
                    "step": 0, "targetAmount": 10,
                    "sourceCompany": {"id": 1}, "targetCompany": {"id": 2},
                    "positions": [{"id": 3, "company": {"id": 1}, "amount": 10}],
                }
                investigator_state = {
                    "id": 1, "status": "ACTIVE", "turn": "INVESTIGATOR",
                    "investigatorActionsRemaining": 3,
                    "sourceCompany": {"id": 1}, "targetCompany": {"id": 2},
                    "positions": [{"id": 3, "company": {"id": 1}, "amount": 10}],
                }
                result = []
                for episode_index in range(4):
                    fraud_policy, investigator_policy = factory(episode_index)
                    result.append((
                        fraud_policy.choose_action(fraud_state),
                        investigator_policy.choose_action(investigator_state),
                    ))
                    self.assertEqual({}, fraud_policy.learner._learner.q_values)
                    self.assertEqual({}, investigator_policy.learner._learner.q_values)
                return result

            self.assertEqual(decisions(101), decisions(101))
            self.assertEqual(saved_bytes, (fraudster_path.read_bytes(), investigator_path.read_bytes()))

    def test_aggregate_uses_explicit_denominators_and_preserves_empty_evidence(self):
        report = evaluate.aggregate_episode_results(
            [
                episode_result(
                    10,
                    objective=True,
                    evidence={
                        "successful_director_investigations": 2,
                        "unique_director_ids_discovered": 3,
                        "unique_connected_company_ids_discovered": 4,
                        "unique_company_director_relationships": 5,
                        "unique_director_company_connections": 6,
                    },
                ),
                episode_result(
                    11,
                    objective=False,
                    evidence={
                        "successful_director_investigations": 0,
                        "unique_director_ids_discovered": 0,
                        "unique_connected_company_ids_discovered": 0,
                        "unique_company_director_relationships": 0,
                        "unique_director_company_connections": 0,
                    },
                ),
                episode_result(12, objective=None, actions=None, evidence=None),
            ],
            requested_count=4,
        )

        self.assertEqual(4, report["requested_episode_count"])
        self.assertEqual(3, report["executed_episode_count"])
        self.assertEqual(2, report["financial_simulation_outcome"]["objective_observed_count"])
        self.assertEqual(0.5, report["financial_simulation_outcome"]["objective_achievement_rate"])
        self.assertEqual(2, report["actions_attempted"]["observed_episode_count"])
        self.assertEqual(2, report["investigator_evidence_aggregate"]["observed_episode_count"])
        self.assertEqual(2, report["investigator_evidence_aggregate"]["successful_director_investigations"])

    def test_evaluation_uses_independent_scenario_ids(self):
        class Client:
            def __init__(self):
                self.created = 0

            def create_scenario(self, **kwargs):
                self.created += 1
                return {"id": 100 + self.created}

        calls = []

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            calls.append(scenario_id)
            result_collector.update(episode_result(scenario_id))
            return result_collector["final_state"]

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            report = evaluate.run_evaluation(
                Client(),
                scenario_count=2,
                source_company_id=1,
                target_company_id=2,
                amount="10",
            )

        self.assertEqual([101, 102], calls)
        self.assertEqual([101, 102], report["scenario_ids"])
        self.assertEqual(2, report["successfully_created_scenarios"])

    def test_creation_failure_can_stop_or_continue(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def create_scenario(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise CatchMeIfYouCanApiError("create failed")
                return {"id": 200 + self.calls}

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            result_collector.update(episode_result(scenario_id))
            return result_collector["final_state"]

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            stopped = evaluate.run_evaluation(
                Client(),
                scenario_count=2,
                source_company_id=1,
                target_company_id=2,
                amount="10",
            )
        self.assertEqual(1, stopped["executed_episode_count"])
        self.assertEqual(1, stopped["failed_scenarios"])

        continuing_client = Client()
        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            continued = evaluate.run_evaluation(
                continuing_client,
                scenario_count=2,
                source_company_id=1,
                target_company_id=2,
                amount="10",
                continue_on_failure=True,
            )
        self.assertEqual(2, continued["executed_episode_count"])
        self.assertEqual(1, continued["successfully_created_scenarios"])
        self.assertEqual(1, continued["failed_scenarios"])

    def test_action_limit_and_failure_classes_are_aggregated_separately(self):
        report = evaluate.aggregate_episode_results(
            [
                episode_result(1, episode_class="action_limit", objective=None, actions=3),
                episode_result(2, episode_class="failed", objective=None, actions=None),
            ]
        )

        self.assertEqual(1, report["action_limit_episodes"])
        self.assertEqual(1, report["failed_scenarios"])
        self.assertEqual(0, report["completed_scenarios"])
        self.assertIsNone(report["financial_simulation_outcome"]["objective_achievement_rate"])
        self.assertEqual(1, report["actions_attempted"]["observed_episode_count"])


if __name__ == "__main__":
    unittest.main()
