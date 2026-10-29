from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from q_learning import QLearningAgent, checkpoint_compatibility
from ground_truth import EvaluatorConfigurationError
from rl_policies import RLFraudsterPolicy, RLInvestigatorPolicy
from rl_training import train_existing_investigator_scenario as managed_investigator_trainer
from run_episode import AgentObservationError, run_episode
from run_learned_episode import (
    RoundPauseGate,
    _emit_event,
    main,
    run_fraudster_training_episode,
    run_investigator_training_episode,
    run_learned_episode,
)


class LearnedEpisodeRunnerTest(unittest.TestCase):
    def test_fresh_training_cli_does_not_load_existing_legacy_default_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_default = root / "fraudster-trained-lifecycle-20261024.json"
            legacy_default.write_text(
                '{"compatibility":{"policy_role":"fraudster",'
                '"state_abstraction_version":"fraudster-state-abstraction-v2",'
                '"legal_action_schema_version":"legal-actions-v1"}}',
                encoding="utf-8",
            )
            fraudster_output = root / "fraudster-run.json"
            investigator_output = root / "investigator-run.json"
            result = {
                "episode_completed": True,
                "transition_counts": {"fraudster": 1},
                "fraudster_training_steps": 1,
                "investigator_training_steps": 1,
            }
            with patch("run_learned_episode.DEFAULT_FRAUDSTER_CHECKPOINT", legacy_default):
                with patch("run_learned_episode.run_fraudster_training_episode", return_value=result) as train:
                    with patch.object(QLearningAgent, "load", side_effect=AssertionError("legacy load attempted")):
                        with patch("run_learned_episode._emit_event"):
                            with patch("run_learned_episode.sys.argv", [
                                "run_learned_episode.py", "--scenario-id", "293",
                                "--train-fraudster", "--initialize-fresh",
                                "--fraudster-output-checkpoint", str(fraudster_output),
                                "--investigator-output-checkpoint", str(investigator_output),
                            ]):
                                self.assertEqual(0, main())

            self.assertTrue(legacy_default.is_file())
            train.assert_called_once_with(
                293,
                fraudster_output_checkpoint=fraudster_output,
                investigator_output_checkpoint=investigator_output,
                max_actions=60,
                seed=0,
                initialize_fresh=True,
            )

    def test_progress_events_strip_credential_fields_recursively(self):
        output = StringIO()
        event = {
            "event_type": "action_started",
            "credential": "secret-value",
            "state": {
                "authorizationToken": "secret-value",
                "privateShellCompanyIds": [21],
                "turn": "FRAUDSTER",
            },
        }
        with redirect_stdout(output):
            _emit_event(event)

        emitted = output.getvalue()
        self.assertNotIn("secret-value", emitted)
        self.assertNotIn("credential", emitted)
        self.assertNotIn("authorizationToken", emitted)
        self.assertNotIn("privateShellCompanyIds", emitted)
        self.assertNotIn("[21]", emitted)
        self.assertIn('"turn":"FRAUDSTER"', emitted)

    def test_managed_runner_emits_safe_internal_diagnostic_and_generic_public_error(self):
        error = EvaluatorConfigurationError(
            "Evaluator discovered-candidate lookup failed; verify the separate read-only PostgreSQL configuration.",
            diagnostic={"stage": "fetch", "exception_type": "InsufficientPrivilege", "sqlstate": "42501"},
        )
        emitted = []
        with patch("run_learned_episode.run_investigator_training_episode", side_effect=error):
            with patch("run_learned_episode._emit_event", side_effect=emitted.append):
                result = main([
                    "--scenario-id", "342", "--train-investigator", "--initialize-fresh",
                    "--investigator-output-checkpoint", "unused.json",
                ])

        self.assertEqual(1, result)
        self.assertEqual("runner_diagnostic", emitted[0]["event_type"])
        self.assertEqual(
            {"stage": "fetch", "exception_type": "InsufficientPrivilege", "sqlstate": "42501"},
            emitted[0]["diagnostic"],
        )
        self.assertEqual("runner_error", emitted[1]["event_type"])
        self.assertEqual(str(error), emitted[1]["message"])

    def test_existing_scenario_uses_validated_learned_policies_and_run_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            QLearningAgent(seed=1, compatibility=checkpoint_compatibility("fraudster")).save(fraudster_path)
            QLearningAgent(seed=2, compatibility=checkpoint_compatibility("investigator")).save(investigator_path)

            captured = {}

            def fake_run_episode(client, **kwargs):
                captured["client"] = client
                captured.update(kwargs)
                captured["authorized_shell_ids"] = kwargs[
                    "private_shell_knowledge_provider"
                ](kwargs["scenario_id"])
                captured["event_callback"]({
                    "event_type": "action", "agent": "FRAUDSTER",
                    "scenario_id": kwargs["scenario_id"],
                })
                kwargs["result_collector"].update({
                    "episode_class": "completed",
                    "actions_attempted": 1,
                    "stop_reason": "scenario terminated",
                })
                return {"id": kwargs["scenario_id"], "status": "COMPLETED"}

            emitted = []
            client = type("PrivateClient", (), {
                "get_fraudster_authorization_probe": lambda self, scenario: {
                    "status": "authorized", "privateShellCompanyIds": [21, 22]
                }
            })()
            with patch("run_learned_episode.run_episode", side_effect=fake_run_episode) as runner:
                with patch("run_learned_episode._emit_event", side_effect=emitted.append):
                    result = run_learned_episode(
                        77,
                        client=client,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                        pause_between_rounds=True,
                    )

            self.assertIsInstance(captured["fraudster_policy"], RLFraudsterPolicy)
            self.assertIsInstance(captured["investigator_policy"], RLInvestigatorPolicy)
            self.assertEqual(77, captured["scenario_id"])
            self.assertEqual([21, 22], captured["authorized_shell_ids"])
            self.assertTrue(callable(captured["pause_before_fraudster"]))
            self.assertNotIn("source_company_id", captured)
            self.assertNotIn("target_company_id", captured)
            self.assertEqual("completed", result["episode_class"])
            self.assertEqual(["checkpoint_provenance", "action", "episode_result"],
                             [event["event_type"] for event in emitted])
            self.assertEqual(
                {"fraudster", "investigator"},
                {item["role"] for item in emitted[0]["checkpoints"]},
            )
            self.assertTrue(all(item["compatibility_status"] == "validated"
                                and len(item["sha256"]) == 64
                                for item in emitted[0]["checkpoints"]))
            runner.assert_called_once()

    def test_checkpoint_validation_failure_stops_before_episode_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "wrong-role.json"
            investigator_path = Path(directory) / "investigator.json"
            QLearningAgent(seed=1, compatibility=checkpoint_compatibility("investigator")).save(fraudster_path)
            QLearningAgent(seed=2, compatibility=checkpoint_compatibility("investigator")).save(investigator_path)

            with patch("run_learned_episode.run_episode") as runner:
                with self.assertRaisesRegex(ValueError, "policy_role"):
                    run_learned_episode(
                        77,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                    )
            runner.assert_not_called()

    def test_authorization_denial_stops_before_episode_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            QLearningAgent(seed=1, compatibility=checkpoint_compatibility("fraudster")).save(fraudster_path)
            QLearningAgent(seed=2, compatibility=checkpoint_compatibility("investigator")).save(investigator_path)
            client = type("DeniedClient", (), {
                "get_fraudster_authorization_probe": lambda self, scenario: {"status": "denied"}
            })()
            policy_action_called = []
            def invoke_provider(_client, **kwargs):
                kwargs["private_shell_knowledge_provider"](kwargs["scenario_id"])
                policy_action_called.append(True)

            with patch("run_learned_episode.run_episode", side_effect=invoke_provider) as runner:
                with self.assertRaisesRegex(AgentObservationError, "malformed"):
                    run_learned_episode(77, client=client,
                                        fraudster_checkpoint=fraudster_path,
                                        investigator_checkpoint=investigator_path)
            runner.assert_called_once()
            self.assertEqual([], policy_action_called)

    def test_training_runner_uses_the_authorized_scenario_and_emits_no_private_ids(self):
        captured = {}
        emitted = []

        class Client:
            def get_fraudster_authorization_probe(self, scenario_id):
                captured.setdefault("authorized_scenarios", []).append(scenario_id)
                return {"status": "authorized", "privateShellCompanyIds": [21]}

        def fake_train(client, reader, **kwargs):
            captured["initialize_fresh"] = kwargs["initialize_fresh"]
            captured["input_checkpoints"] = (
                kwargs["fraudster_checkpoint"], kwargs["investigator_checkpoint"]
            )
            ids = kwargs["private_shell_knowledge_provider"](kwargs["scenario_id"])
            captured["policy_private_ids"] = ids
            return {
                "scenario_id": kwargs["scenario_id"],
                "episode_completed": True,
                "terminal_outcome": "MAX_TURNS_REACHED",
                "fraudster_reward": 10.0,
                "transition_counts": {"fraudster": 1, "investigator": 1},
                "fraudster_training_steps": 1,
                "investigator_training_steps": 1,
                "fraudster_checkpoint": str(kwargs["fraudster_output_checkpoint"]),
                "investigator_checkpoint": str(kwargs["investigator_output_checkpoint"]),
            }

        with patch("run_learned_episode.train_existing_scenario", side_effect=fake_train):
            with patch("run_learned_episode._emit_event", side_effect=emitted.append):
                result = run_fraudster_training_episode(
                    77,
                    client=Client(),
                    ground_truth_reader=object(),
                    fraudster_output_checkpoint="fraudster-output.json",
                    investigator_output_checkpoint="investigator-output.json",
                    initialize_fresh=True,
                )

        self.assertEqual([77], captured["authorized_scenarios"])
        self.assertTrue(captured["initialize_fresh"])
        self.assertEqual((None, None), captured["input_checkpoints"])
        self.assertEqual([21], captured["policy_private_ids"])
        self.assertEqual("MAX_TURNS_REACHED", emitted[-1]["final_state"]["status"])
        self.assertNotIn("privateShellCompanyIds", repr(emitted))
        self.assertEqual("MAX_TURNS_REACHED", result["terminal_outcome"])

    def test_investigator_training_uses_scenario_authorization_for_coverage_opponent(self):
        authorized = []
        emitted = []
        captured = {}

        class Client:
            def get_fraudster_authorization_probe(self, scenario_id):
                authorized.append(scenario_id)
                return {"status": "authorized", "privateShellCompanyIds": [31]}

        def fake_train(client, reader, **kwargs):
            captured["trainer_kwargs"] = kwargs
            ids = kwargs["private_shell_knowledge_provider"](kwargs["scenario_id"])
            self.assertEqual([31], ids)
            return {
                "scenario_id": kwargs["scenario_id"],
                "episode_completed": True,
                "terminal_outcome": "MAX_TURNS_REACHED",
                "actions_attempted": 5,
                "transition_counts": {"fraudster": 0, "investigator": 2},
                "investigator_training_steps": 2,
                "fraudster_action_type_counts": {"ROUTE_TRANSFER": 1},
                "shell_path_transfer_confirmed": True,
                "path_positive_candidate_count": 1,
                "path_negative_candidate_count": 2,
                "investigator_checkpoint": str(kwargs["investigator_output_checkpoint"]),
            }

        with patch("run_learned_episode.train_existing_investigator_scenario",
                   side_effect=fake_train):
            with patch("run_learned_episode._emit_event", side_effect=emitted.append):
                result = run_investigator_training_episode(
                    88, investigator_checkpoint=None,
                    investigator_output_checkpoint="investigator-out.json",
                    client=Client(), ground_truth_reader=object(), initialize_fresh=True,
                )

        self.assertEqual([88], authorized)
        inspect.signature(managed_investigator_trainer).bind(
            Client(), object(), **captured["trainer_kwargs"]
        )
        self.assertNotIn("ensure_shell_path", captured["trainer_kwargs"])
        self.assertTrue(result["shell_path_transfer_confirmed"])
        self.assertEqual(1, emitted[0]["path_positive_candidate_count"])
        self.assertNotIn("privateShellCompanyIds", repr(emitted))

    def test_round_pause_gate_waits_for_continue_in_the_same_process(self):
        emitted = []
        gate = RoundPauseGate(emitted.append)
        with patch("run_learned_episode.sys.stdin", StringIO("CONTINUE\n")):
            gate(77, {"id": 77, "status": "ACTIVE", "turn": "FRAUDSTER"})
        self.assertEqual(["round_paused", "round_resumed"], [e["event_type"] for e in emitted])
        self.assertEqual(1, emitted[0]["round_number"])
        self.assertEqual(77, emitted[0]["scenario_id"])

    def test_round_pause_gate_fails_closed_when_continue_input_is_missing(self):
        gate = RoundPauseGate(lambda event: None)
        with patch("run_learned_episode.sys.stdin", StringIO("")):
            with self.assertRaisesRegex(RuntimeError, "cancelled while paused"):
                gate(77, {"id": 77, "status": "ACTIVE", "turn": "FRAUDSTER"})

    def test_episode_pauses_only_after_investigator_phase_before_next_fraudster_action(self):
        order = []

        class Client:
            def __init__(self):
                self.state = {
                    "id": 78, "status": "ACTIVE", "turn": "FRAUDSTER", "step": 0,
                    "investigatorActionsRemaining": 3,
                    "positions": [{"id": 9, "company": {"id": 1}, "amount": 100}],
                    "sourceCompany": {"id": 1}, "targetCompany": {"id": 2},
                }
                self.next_action_id = 0

            def get_scenario(self, scenario_id):
                self.assert_scenario(scenario_id)
                return deepcopy(self.state)

            def get_scenario_transactions(self, scenario_id):
                self.assert_scenario(scenario_id)
                return []

            @staticmethod
            def assert_scenario(scenario_id):
                if scenario_id != 78:
                    raise AssertionError("runner changed scenario ID")

            def create_fraudster_action(self, **kwargs):
                self.next_action_id += 1
                return {"id": self.next_action_id}

            def execute_fraudster_action(self, action_id):
                self.state["turn"] = "INVESTIGATOR"
                self.state["investigatorActionsRemaining"] = 3
                self.state["step"] += 1

            def submit_investigator_action(self, **kwargs):
                self.state["investigatorActionsRemaining"] -= 1
                if self.state["investigatorActionsRemaining"] == 0:
                    self.state["turn"] = "FRAUDSTER"
                return {}

        class Fraudster:
            def choose_action(self, state):
                order.append("fraudster")
                return {"action_type": "WAIT", "source_position_id": 9, "targets": []}

        class Investigator:
            def choose_action(self, state):
                order.append("investigator")
                return {"action_type": "OBSERVE_COMPANY", "company_id": 1}

            def sanitize_action_response(self, response, **kwargs):
                return {}

            def mark_action_completed(self, action, response):
                pass

            def evidence_summary(self):
                return {}

        def pause(scenario_id, state):
            order.append("pause")
            self.assertEqual(78, scenario_id)
            self.assertEqual("FRAUDSTER", state["turn"])
            self.assertEqual(0, state["investigatorActionsRemaining"])

        knowledge_fetches = []
        with self.assertRaisesRegex(RuntimeError, "did not terminate"):
            run_episode(
                Client(), scenario_id=78, max_actions=5,
                fraudster_policy=Fraudster(), investigator_policy=Investigator(),
                pause_before_fraudster=pause,
                private_shell_knowledge_provider=lambda scenario: (
                    knowledge_fetches.append(scenario) or []
                ),
            )
        self.assertEqual(
            ["fraudster", "investigator", "investigator", "investigator", "pause", "fraudster"],
            order,
        )
        self.assertEqual([78, 78], knowledge_fetches)

    def test_human_fraudster_pause_refreshes_backend_state_before_investigator_decision(self):
        calls = []

        class Client:
            def __init__(self):
                self.state = {
                    "id": 79, "status": "ACTIVE", "turn": "FRAUDSTER", "step": 0,
                    "investigatorActionsRemaining": 3,
                    "positions": [{"id": 9, "company": {"id": 1}, "amount": 100}],
                    "sourceCompany": {"id": 1}, "targetCompany": {"id": 2},
                }

            def get_scenario(self, scenario_id):
                self.assert_scenario(scenario_id)
                return deepcopy(self.state)

            def get_scenario_transactions(self, scenario_id):
                self.assert_scenario(scenario_id)
                return []

            @staticmethod
            def assert_scenario(scenario_id):
                if scenario_id != 79:
                    raise AssertionError("runner changed scenario ID")

            def submit_investigator_action(self, **kwargs):
                calls.append(("investigator", kwargs["action_type"]))
                self.state["status"] = "COMPLETED"
                return {"actionType": kwargs["action_type"]}

        class Investigator:
            def choose_action(self, state):
                if state["turn"] != "INVESTIGATOR":
                    raise AssertionError("investigator received a stale scenario turn")
                calls.append(("choose", "INVESTIGATOR"))
                return {"action_type": "OBSERVE_COMPANY", "company_id": 1}

            def sanitize_action_response(self, response, **kwargs):
                return response

            def mark_action_completed(self, action, response):
                pass

            def evidence_summary(self):
                return {}

        client = Client()

        def human_move(scenario_id, state):
            self.assertEqual(79, scenario_id)
            self.assertEqual("FRAUDSTER", state["turn"])
            calls.append(("pause", "FRAUDSTER"))
            client.state["turn"] = "INVESTIGATOR"

        with patch("run_episode.build_agent_observation", side_effect=lambda _client, _id, _state, role, **_: {"turn": role}):
            final = run_episode(
                client, scenario_id=79, max_actions=3,
                investigator_policy=Investigator(),
                pause_before_fraudster=human_move,
                human_controlled_fraudster=True,
            )

        self.assertEqual("COMPLETED", final["status"])
        self.assertEqual(
            [("pause", "FRAUDSTER"), ("choose", "INVESTIGATOR"), ("investigator", "OBSERVE_COMPANY")],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
