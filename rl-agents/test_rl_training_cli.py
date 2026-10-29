import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rl_training
from ground_truth import EvaluatorDataError
from q_learning import QLearningAgent
from q_learning import checkpoint_compatibility
from state_abstraction import INVESTIGATOR_STATE_ABSTRACTION_VERSION, LEGAL_ACTION_SCHEMA_VERSION


class TrainingCliTest(unittest.TestCase):
    def _train(self, *args, **kwargs):
        # Paired unit tests use a stub representing the trusted run context.
        # Production CLI intentionally has no such scenario-bound provider.
        kwargs.setdefault("private_shell_knowledge_provider", lambda _scenario_id: [])
        return rl_training.train(*args, **kwargs)

    def _paths(self, directory):
        return Path(directory) / "fraudster.json", Path(directory) / "investigator.json"

    def test_investigator_only_training_saves_compatible_checkpoint_without_rl_fraudster(self):
        from fraudster_bot import FraudsterBot

        class FakeRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, *, fraudster, investigator, **kwargs):
                self_seen = isinstance(fraudster, FraudsterBot)
                if not self_seen or kwargs.get("train_fraudster") is not False:
                    raise AssertionError("Investigator-only training must use the declared baseline opponent.")
                investigator.learner.update("investigator-state", "investigator-action", 1, None, done=True)
                return {
                    "scenario_id": 100,
                    "episode_completed": True,
                    "financial_objective_achieved": True,
                    "fraudster_reward": None,
                    "investigator_training_reward": 1.0,
                    "fraudster_action_type_counts": {},
                    "shell_path_transfer_confirmed": False,
                    "path_positive_candidate_count": 0,
                    "path_negative_candidate_count": 0,
                    "transition_counts": {"fraudster": 0, "investigator": 1},
                }

        with tempfile.TemporaryDirectory() as directory:
            _, investigator_path = self._paths(directory)
            with patch.object(rl_training, "RLTrainingRunner", FakeRunner):
                report = self._train(
                    object(), object(), episodes=1, source_company_id=1,
                    target_company_id=2, amount="10", max_actions=4, seed=7,
                    fraudster_checkpoint=None, investigator_checkpoint=investigator_path,
                    investigator_only=True,
                )

            payload = json.loads(investigator_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint_compatibility("investigator"), payload["compatibility"])
            self.assertEqual("investigator_only", payload["metadata"]["training_provenance"]["training_mode"])
            self.assertIn("non-RL baseline", payload["metadata"]["training_provenance"]["fraudster_opponent"])
            self.assertIsNone(report["fraudster_checkpoint"])
            self.assertEqual(0, report["fraudster_transition_count"])
            self.assertEqual(1, report["investigator_transition_count"])

    def test_paired_training_fails_closed_without_authorized_private_context(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            with patch.object(rl_training, "RLTrainingRunner") as runner:
                with self.assertRaisesRegex(ValueError, "authorized private shell context"):
                    rl_training.train(
                        object(), object(), episodes=1, source_company_id=1,
                        target_company_id=2, amount="10", max_actions=4, seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                    )
            runner.assert_not_called()

    def test_training_updates_both_roles_and_saves_role_metadata(self):
        class FakeRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, *, fraudster, investigator, **kwargs):
                fraudster.learner.update("fraud-state", "fraud-action", 2, None, done=True)
                investigator.learner.update("investigator-state", "investigator-action", 1, None, done=True)
                return {
                    "scenario_id": 100,
                    "episode_completed": True,
                    "financial_objective_achieved": True,
                    "fraudster_reward": 10.0,
                    "investigator_training_reward": 1.0,
                    "fraudster_action_type_counts": {"ROUTE_TRANSFER": 1},
                    "shell_path_transfer_confirmed": True,
                    "path_positive_candidate_count": 1,
                    "path_negative_candidate_count": 1,
                    "transition_counts": {"fraudster": 1, "investigator": 1},
                }

        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            with patch.object(rl_training, "RLTrainingRunner", FakeRunner):
                report = self._train(
                    object(),
                    object(),
                    episodes=2,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10.00",
                    max_actions=4,
                    seed=7,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )

            fraudster_payload = json.loads(fraudster_path.read_text(encoding="utf-8"))
            investigator_payload = json.loads(investigator_path.read_text(encoding="utf-8"))
            self.assertEqual("fraudster", fraudster_payload["compatibility"]["policy_role"])
            self.assertEqual("investigator", investigator_payload["compatibility"]["policy_role"])
            for payload in (fraudster_payload, investigator_payload):
                self.assertEqual(
                    checkpoint_compatibility(payload["compatibility"]["policy_role"])["state_abstraction_version"],
                    payload["compatibility"]["state_abstraction_version"],
                )
                self.assertEqual(
                    LEGAL_ACTION_SCHEMA_VERSION,
                    payload["compatibility"]["legal_action_schema_version"],
                )
            self.assertEqual(2, report["completed_episode_count"])
            self.assertEqual(2, report["fraudster_transition_count"])
            self.assertEqual(2, report["investigator_transition_count"])
            self.assertTrue(fraudster_payload["q_values"])
            self.assertTrue(investigator_payload["q_values"])

    def test_existing_checkpoints_are_rejected_without_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            fraudster_path.write_text("existing", encoding="utf-8")
            with patch.object(rl_training, "RLTrainingRunner") as runner:
                with self.assertRaises(FileExistsError):
                    self._train(
                        object(),
                        object(),
                        episodes=1,
                        source_company_id=1,
                        target_company_id=2,
                        amount="10",
                        max_actions=4,
                        seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                    )
            runner.assert_not_called()

    def test_resume_preserves_existing_values_hyperparameters_and_steps(self):
        class FakeRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, *, fraudster, investigator, **kwargs):
                fraudster.learner.update("new-fraud", "action", 2, None, done=True)
                investigator.learner.update("new-investigator", "action", 1, None, done=True)
                return {
                    "scenario_id": 101,
                    "episode_completed": True,
                    "financial_objective_achieved": True,
                    "fraudster_reward": 10.0,
                    "investigator_training_reward": 1.0,
                    "fraudster_action_type_counts": {"ROUTE_TRANSFER": 1},
                    "shell_path_transfer_confirmed": True,
                    "path_positive_candidate_count": 1,
                    "path_negative_candidate_count": 1,
                    "transition_counts": {"fraudster": 1, "investigator": 1},
                }

        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            fraudster = QLearningAgent.for_role(
                "fraudster", learning_rate=0.25, discount_factor=0.8, epsilon=0.3, seed=11
            )
            investigator = QLearningAgent.for_role(
                "investigator", learning_rate=0.35, discount_factor=0.7, epsilon=0.4, seed=12
            )
            fraudster.update("old-fraud", "old-action", 4, None, done=True)
            investigator.update("old-investigator", "old-action", 5, None, done=True)
            fraudster.save(fraudster_path)
            investigator.save(investigator_path)

            with patch.object(rl_training, "RLTrainingRunner", FakeRunner):
                self._train(
                    object(),
                    object(),
                    episodes=1,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    max_actions=4,
                    seed=999,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                    overwrite_checkpoints=True,
                    resume=True,
                )

            loaded_fraudster = QLearningAgent.load(fraudster_path)
            loaded_investigator = QLearningAgent.load(investigator_path)
            self.assertEqual(0.25, loaded_fraudster.learning_rate)
            self.assertEqual(0.8, loaded_fraudster.discount_factor)
            self.assertEqual(0.3, loaded_fraudster.epsilon)
            self.assertEqual(11, loaded_fraudster.seed)
            self.assertEqual(2, loaded_fraudster.training_steps)
            self.assertEqual(1.0, loaded_fraudster.q_values['"old-fraud"']['"old-action"'])
            self.assertEqual(0.35, loaded_investigator.learning_rate)
            self.assertEqual(0.7, loaded_investigator.discount_factor)
            self.assertEqual(0.4, loaded_investigator.epsilon)
            self.assertEqual(12, loaded_investigator.seed)
            self.assertEqual(2, loaded_investigator.training_steps)
            self.assertEqual(1.75, loaded_investigator.q_values['"old-investigator"']['"old-action"'])

    def test_resume_rejects_role_mismatch_before_episode_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            QLearningAgent.for_role("investigator").save(fraudster_path)
            QLearningAgent.for_role("investigator").save(investigator_path)
            with patch.object(rl_training, "RLTrainingRunner") as runner:
                with self.assertRaisesRegex(ValueError, "fraudster resume checkpoint"):
                    self._train(
                        object(),
                        object(),
                        episodes=1,
                        source_company_id=1,
                        target_company_id=2,
                        amount="10",
                        max_actions=4,
                        seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                        overwrite_checkpoints=True,
                        resume=True,
                    )
            runner.assert_not_called()

    def test_resume_rejects_fraudster_v1_and_preserves_current_investigator_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            incompatible_metadata = checkpoint_compatibility("fraudster")
            incompatible_metadata["state_abstraction_version"] = "state-abstraction-v1"
            old_fraudster = QLearningAgent(
                compatibility=incompatible_metadata,
            )
            old_fraudster.update("old-state", "old-action", 3, None, done=True)
            old_fraudster.save(fraudster_path)

            investigator = QLearningAgent.for_role("investigator", seed=7)
            investigator.update("investigator-state", "observe", 1, None, done=True)
            investigator.save(investigator_path)
            investigator_before = investigator_path.read_bytes()

            with patch.object(rl_training, "RLTrainingRunner") as runner:
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    self._train(
                        object(),
                        object(),
                        episodes=1,
                        source_company_id=1,
                        target_company_id=2,
                        amount="10",
                        max_actions=4,
                        seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                        overwrite_checkpoints=True,
                        resume=True,
                    )
            runner.assert_not_called()

            loaded_investigator = QLearningAgent.load(investigator_path)
            self.assertEqual("investigator", loaded_investigator.compatibility["policy_role"])
            self.assertEqual(
                INVESTIGATOR_STATE_ABSTRACTION_VERSION,
                loaded_investigator.compatibility["state_abstraction_version"],
            )
            self.assertEqual(investigator_before, investigator_path.read_bytes())

    def test_resume_rejects_missing_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            QLearningAgent.for_role("fraudster").save(fraudster_path)
            with self.assertRaisesRegex(FileNotFoundError, "Resume checkpoint does not exist"):
                self._train(
                    object(),
                    object(),
                    episodes=1,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    max_actions=4,
                    seed=0,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                    overwrite_checkpoints=True,
                    resume=True,
                )

    def test_resume_requires_explicit_overwrite_for_existing_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            QLearningAgent.for_role("fraudster").save(fraudster_path)
            QLearningAgent.for_role("investigator").save(investigator_path)
            with self.assertRaisesRegex(ValueError, "overwrite_checkpoints"):
                self._train(
                    object(),
                    object(),
                    episodes=1,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    max_actions=4,
                    seed=0,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                    resume=True,
                )

    def test_each_episode_gets_fresh_investigator_memory_but_shared_learners(self):
        policies = []

        class FakeRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, *, fraudster, investigator, **kwargs):
                policies.append((fraudster, investigator))
                fraudster.learner.update("fraud", len(policies), 1, None, done=True)
                investigator.learner.update("investigator", len(policies), 1, None, done=True)
                if len(policies) == 1:
                    investigator.mark_action_completed(
                        {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 99},
                        {"directorInvestigation": {
                            "directors": [{"directorId": 7, "associatedCompanies": [{"id": 100}]}]
                        }},
                    )
                    if 100 not in investigator._candidate_company_ids({
                            "sourceCompany": {"id": 1},
                            "targetCompany": {"id": 2},
                            "positions": [],
                    }):
                        raise AssertionError("Episode 1 discovery was not retained within its episode")
                else:
                    current_state = {
                        "status": "ACTIVE",
                        "turn": "INVESTIGATOR",
                        "investigatorActionsRemaining": 3,
                        "sourceCompany": {"id": 1},
                        "targetCompany": {"id": 2},
                        "positions": [],
                    }
                    if any(action.get("company_id") == 100
                           for action in investigator.legal_actions(current_state)):
                        raise AssertionError("Episode 1 discovery leaked into Episode 2")
                return {
                    "scenario_id": len(policies),
                    "episode_completed": True,
                    "financial_objective_achieved": False,
                    "fraudster_reward": -10.0,
                    "investigator_training_reward": 0.0,
                    "fraudster_action_type_counts": {"ROUTE_TRANSFER": 1},
                    "shell_path_transfer_confirmed": True,
                    "path_positive_candidate_count": 1,
                    "path_negative_candidate_count": 1,
                    "transition_counts": {"fraudster": 1, "investigator": 1},
                }

        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            with patch.object(rl_training, "RLTrainingRunner", FakeRunner):
                self._train(
                    object(),
                    object(),
                    episodes=2,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    max_actions=4,
                    seed=3,
                    fraudster_checkpoint=fraudster_path,
                    investigator_checkpoint=investigator_path,
                )

        self.assertEqual(2, len(policies))
        self.assertIsNot(policies[0][1], policies[1][1])
        self.assertIs(policies[0][0].learner, policies[1][0].learner)
        self.assertIs(policies[0][1].learner, policies[1][1].learner)
        self.assertEqual(2, policies[0][0].learner.training_steps)
        self.assertEqual(2, policies[0][1].learner.training_steps)

    def test_failed_episode_does_not_save_checkpoints(self):
        class FailingRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, **kwargs):
                raise EvaluatorDataError("episode incomplete")

        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            with patch.object(rl_training, "RLTrainingRunner", FailingRunner):
                with self.assertRaises(EvaluatorDataError):
                    self._train(
                        object(),
                        object(),
                        episodes=1,
                        source_company_id=1,
                        target_company_id=2,
                        amount="10",
                        max_actions=4,
                        seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                    )
            self.assertFalse(fraudster_path.exists())
            self.assertFalse(investigator_path.exists())

    def test_failed_training_preserves_existing_checkpoint_contents(self):
        class FailingRunner:
            def __init__(self, client, ground_truth_reader):
                pass

            def run_episode(self, **kwargs):
                raise EvaluatorDataError("episode incomplete")

        with tempfile.TemporaryDirectory() as directory:
            fraudster_path, investigator_path = self._paths(directory)
            fraudster_path.write_text("old fraudster", encoding="utf-8")
            investigator_path.write_text("old investigator", encoding="utf-8")
            with patch.object(rl_training, "RLTrainingRunner", FailingRunner):
                with self.assertRaises(EvaluatorDataError):
                    self._train(
                        object(),
                        object(),
                        episodes=1,
                        source_company_id=1,
                        target_company_id=2,
                        amount="10",
                        max_actions=4,
                        seed=0,
                        fraudster_checkpoint=fraudster_path,
                        investigator_checkpoint=investigator_path,
                        overwrite_checkpoints=True,
                    )
            self.assertEqual("old fraudster", fraudster_path.read_text(encoding="utf-8"))
            self.assertEqual("old investigator", investigator_path.read_text(encoding="utf-8"))

    def test_cli_rejects_invalid_local_arguments_before_reader_creation(self):
        with patch.object(rl_training.PostgresGroundTruthReader, "from_environment") as reader:
            result = rl_training.main([
                "--episodes", "0",
                "--source-company-id", "1",
                "--target-company-id", "2",
                "--amount", "10",
                "--fraudster-checkpoint", "fraudster.json",
                "--investigator-checkpoint", "investigator.json",
            ])
        self.assertEqual(1, result)
        reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
