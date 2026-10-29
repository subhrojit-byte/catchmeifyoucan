import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ground_truth import EvaluatorDataError
from fraudster_bot import FraudsterBot
from q_learning import QLearningAgent, checkpoint_compatibility
from rl_training import (RLTrainingRunner, investigator_terminal_reward, train_existing_scenario,
                         train_existing_investigator_scenario)


SCENARIO_ID = 42


def _assert_no_hidden_labels(value):
    if isinstance(value, dict):
        if any(key in value for key in (
                "shellCompany", "flagCorrect", "fraudPathInvolved",
                "fraud_path_involved", "pathShellCompany")):
            raise AssertionError("A hidden evaluator label reached a live policy state.")
        for child in value.values():
            _assert_no_hidden_labels(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_hidden_labels(child)


class RecordingLearner:
    discount_factor = 0.5

    def __init__(self):
        self.updates = []

    def update(self, state, action, reward, next_state, next_actions, *, done=False):
        self.updates.append({
            "state": state,
            "action": action,
            "reward": reward,
            "next_state": next_state,
            "next_actions": tuple(next_actions),
            "done": done,
        })


class FakeClient:
    def __init__(self, *, scenario_id=SCENARIO_ID, flag_on_first_investigator_action=False):
        self.events = []
        self.scenario_id = scenario_id
        self.flag_on_first_investigator_action = flag_on_first_investigator_action
        self.state = {
            "id": scenario_id,
            "status": "ACTIVE",
            "turn": "FRAUDSTER",
            "step": 0,
            "targetAmount": "10",
            "financialObjectiveAchieved": False,
            "investigatorActionsRemaining": 0,
            "sourceCompany": {"id": 1},
            "targetCompany": {"id": 2},
            "positions": [
                {"id": 10, "company": {"id": 1}, "amount": "10"},
                {"id": 20, "company": {"id": 2}, "amount": "0"},
            ],
        }
        self.history = []
        self.pending_action = None
        self.next_action_id = 1
        self.investigator_actions_in_phase = 0

    def create_scenario(self, **kwargs):
        self.events.append(("create", self.scenario_id))
        return {"id": self.scenario_id}

    def get_scenario(self, scenario_id):
        self.events.append(("scenario", scenario_id))
        return copy.deepcopy(self.state)

    def get_scenario_transactions(self, scenario_id):
        self.events.append(("history", scenario_id))
        history = copy.deepcopy(self.history)
        for transaction in history:
            # These are deliberately present in the raw endpoint response. The
            # existing sanitizer must keep them out of policy observations.
            transaction["shellCompany"] = True
            transaction["flagCorrect"] = True
        return history

    def create_fraudster_action(self, *, scenario_id, action_type,
                                source_position_id, targets=None):
        self.events.append(("create_fraudster_action", scenario_id))
        self.pending_action = {
            "id": self.next_action_id,
            "scenario_id": scenario_id,
            "source_position_id": source_position_id,
            "action_type": action_type,
            "targets": copy.deepcopy(targets),
        }
        self.next_action_id += 1
        return {"id": self.pending_action["id"]}

    def execute_fraudster_action(self, action_id):
        self.events.append(("execute_fraudster_action", self.scenario_id))
        self.state["step"] += 1
        self.state["turn"] = "INVESTIGATOR"
        self.state["investigatorActionsRemaining"] = 3
        self.state["financialObjectiveAchieved"] = True
        self.investigator_actions_in_phase = 0
        targets = self.pending_action.get("targets") or []
        destination_id = (
            targets[0].get("destinationCompanyId")
            if targets and isinstance(targets[0], dict) else 2
        )
        destination_company = {"id": destination_id}
        self.history.append({
            "id": 100 + action_id,
            "sourceCompany": {"id": 1},
            "destinationCompany": destination_company,
            "amount": "10",
            "origin": "FRAUDSTER_ACTION",
            "scenarioId": self.scenario_id,
        })
        if destination_id not in {1, 2} and not any(
                (item.get("company") or {}).get("id") == destination_id
                for item in self.state["positions"]):
            self.state["positions"].append({
                "id": 30, "company": destination_company, "amount": "10",
            })

    def submit_investigator_action(self, *, scenario_id, action_type,
                                   company_id=None, transaction_id=None):
        self.events.append(("investigator_action", scenario_id))
        self.state["investigatorActionsRemaining"] -= 1
        self.investigator_actions_in_phase += 1
        if action_type == "FLAG_COMPANY":
            self.state["status"] = "COMPLETED"
        elif self.state["investigatorActionsRemaining"] == 0:
            if self.state["step"] >= 2:
                self.state["status"] = "MAX_TURNS_REACHED"
            else:
                self.state["turn"] = "FRAUDSTER"
        return {"status": self.state["status"]}

    def get_eligible_intermediate_companies(self, company_id):
        return [3] if company_id == 1 else []

    def get_company(self, company_id):
        return {
            "id": company_id, "companyName": "Authorized shell intermediary",
            "ageInYears": 2, "numberOfEmployees": 5,
            "annualRevenue": "1000", "address": "Public address",
        }


class FraudsterPolicySpy:
    def __init__(self, client, reader):
        self.client = client
        self.reader = reader
        self.learner = RecordingLearner()
        self.states = []
        self.decision_event_indexes = []

    def choose_action(self, state):
        if self.reader.calls or self.reader.correct_flag_calls:
            raise AssertionError("Evaluator data was queried before a live decision.")
        _assert_no_hidden_labels(state)
        self.states.append(copy.deepcopy(state))
        self.client.events.append(("fraudster_decision", state["id"]))
        self.decision_event_indexes.append(len(self.client.events) - 1)
        return {"action_type": "WAIT", "source_position_id": 10, "targets": []}


class InvestigatorPolicySpy:
    class Fallback:
        @staticmethod
        def sanitize_action_response(response, **kwargs):
            return {}

    def __init__(self, client, reader, *, flag_first=False, action_sequence=None):
        self.client = client
        self.reader = reader
        self.learner = RecordingLearner()
        self.fallback = self.Fallback()
        self.flag_first = flag_first
        self.action_sequence = action_sequence
        self.states = []
        self.completed = []

    def state_key(self, state):
        return (state["step"], state["investigatorActionsRemaining"])

    def choose_action(self, state):
        if self.reader.calls or self.reader.correct_flag_calls:
            raise AssertionError("Evaluator data was queried before a live decision.")
        _assert_no_hidden_labels(state)
        self.states.append(copy.deepcopy(state))
        if self.action_sequence is not None:
            return dict(self.action_sequence[len(self.completed)])
        if self.flag_first and not self.completed:
            return {"action_type": "FLAG_COMPANY", "company_id": 2}
        return {"action_type": "OBSERVE_COMPANY", "company_id": 2}

    def mark_action_completed(self, action, response):
        self.completed.append(action)

    def legal_actions(self, state):
        if state["status"] != "ACTIVE" or state["investigatorActionsRemaining"] <= 0:
            return []
        return [
            {"action_type": action_type, "company_id": company_id}
            for company_id in (1, 2)
            for action_type in ("OBSERVE_COMPANY", "FLAG_COMPANY")
        ]


class GroundTruthReaderSpy:
    def __init__(self, client, *, shell_company, flagged, correctly_flagged=False,
                 shell_company_ids=None):
        self.client = client
        self.shell_company = shell_company
        self.flagged = flagged
        self.correctly_flagged = correctly_flagged
        self.shell_company_ids = shell_company_ids
        self.calls = 0
        self.correct_flag_calls = 0
        self.status_at_read = []
        self.captured_candidate_ids = None

    def read_correct_flag_outcomes(self, scenario_ids):
        self.correct_flag_calls += 1
        self.status_at_read.append(self.client.state["status"])
        self.client.events.append(("ground_truth_correct_flags", tuple(scenario_ids)))
        return {scenario_id: self.correctly_flagged for scenario_id in scenario_ids}

    def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
        self.calls += 1
        self.status_at_read.append(self.client.state["status"])
        self.captured_candidate_ids = {
            scenario_id: sorted(company_ids)
            for scenario_id, company_ids in candidate_ids_by_scenario.items()
        }
        self.client.events.append(("ground_truth_discovered", tuple(scenario_ids)))
        decisions = []
        for scenario_id, company_ids in candidate_ids_by_scenario.items():
            path_company_ids = set()
            for transaction in self.client.history:
                if transaction.get("origin") != "FRAUDSTER_ACTION":
                    continue
                path_company_ids.add(transaction["sourceCompany"]["id"])
                path_company_ids.add(transaction["destinationCompany"]["id"])
            for index, company_id in enumerate(sorted(company_ids)):
                shell_company = (
                    company_id in self.shell_company_ids
                    if self.shell_company_ids is not None
                    else self.shell_company if index == 0 else not self.shell_company
                )
                flagged = self.flagged if index == 0 else False
                decisions.append(SimpleNamespace(
                    scenario_id=scenario_id,
                    company_id=company_id,
                    shell_company=shell_company,
                    flagged=flagged,
                    fraud_path_involved=(
                        company_id in path_company_ids
                        if self.shell_company_ids is not None else shell_company
                    ),
                ))
        return decisions


class RLTrainingRunnerTest(unittest.TestCase):
    def _policies(self, client, reader, *, flag_first=False):
        return (
            FraudsterPolicySpy(client, reader),
            InvestigatorPolicySpy(client, reader, flag_first=flag_first),
        )

    def test_two_turns_refresh_same_scenario_state_and_history_before_fraudster_decisions(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(client, shell_company=False, flagged=False)
        fraudster, investigator = self._policies(client, reader)

        result = RLTrainingRunner(client, reader).run_episode(
            source_company_id=1,
            target_company_id=2,
            amount="10",
            fraudster=fraudster,
            investigator=investigator,
            max_actions=8,
            private_shell_knowledge_provider=lambda _scenario_id: [],
        )

        self.assertEqual("MAX_TURNS_REACHED", result["terminal_outcome"])
        self.assertEqual(2, result["transition_counts"]["fraudster"])
        self.assertEqual(6, result["transition_counts"]["investigator"])
        self.assertEqual([0, 1], [len(state["transactionHistory"]) for state in fraudster.states])
        self.assertTrue(all(state["id"] == SCENARIO_ID for state in fraudster.states))
        self.assertTrue(all(
            item["scenarioId"] == SCENARIO_ID
            for state in fraudster.states
            for item in state["transactionHistory"]
        ))

        first_decision, second_decision = fraudster.decision_event_indexes
        events_before_second = client.events[:second_decision]
        self.assertIn(("scenario", SCENARIO_ID), events_before_second[first_decision + 1:])
        self.assertEqual(("history", SCENARIO_ID), client.events[second_decision - 1])
        self.assertTrue(all(event[1] == SCENARIO_ID for event in client.events
                            if event[0] in {"scenario", "history", "investigator_action"}))

        self.assertEqual(2, len(fraudster.learner.updates))
        self.assertEqual([5.0, 10.0], [update["reward"] for update in fraudster.learner.updates])
        self.assertTrue(all(update["done"] for update in fraudster.learner.updates))
        self.assertEqual(6, len(investigator.learner.updates))
        self.assertTrue(all(update["done"] for update in investigator.learner.updates))
        self.assertEqual(1, reader.calls)
        self.assertEqual(1, reader.correct_flag_calls)
        self.assertEqual(["MAX_TURNS_REACHED", "MAX_TURNS_REACHED"], reader.status_at_read)
        self.assertEqual(-1.0, result["investigator_training_reward"])

    def test_detection_updates_both_agents_once_and_reads_labels_only_after_terminal(self):
        client = FakeClient(flag_on_first_investigator_action=True)
        reader = GroundTruthReaderSpy(
            client, shell_company=True, flagged=True, correctly_flagged=True
        )
        fraudster, investigator = self._policies(client, reader, flag_first=True)

        result = RLTrainingRunner(client, reader).run_episode(
            source_company_id=1,
            target_company_id=2,
            amount="10",
            fraudster=fraudster,
            investigator=investigator,
            max_actions=4,
            private_shell_knowledge_provider=lambda _scenario_id: [],
        )

        self.assertEqual("COMPLETED", result["terminal_outcome"])
        self.assertEqual(1, result["transition_counts"]["fraudster"])
        self.assertEqual(1, result["transition_counts"]["investigator"])
        self.assertEqual(1, len(fraudster.learner.updates))
        self.assertEqual(-10.0, fraudster.learner.updates[0]["reward"])
        self.assertTrue(fraudster.learner.updates[0]["done"])
        self.assertEqual(1, len(investigator.learner.updates))
        self.assertEqual(1.0, investigator.learner.updates[0]["reward"])
        self.assertTrue(investigator.learner.updates[0]["done"])
        self.assertEqual(1, reader.calls)
        self.assertEqual(1, reader.correct_flag_calls)
        self.assertEqual(["COMPLETED", "COMPLETED"], reader.status_at_read)
        self.assertEqual(("ground_truth_discovered", (SCENARIO_ID,)), client.events[-1])
        self.assertEqual({SCENARIO_ID: [1, 2]}, reader.captured_candidate_ids)
        for state in fraudster.states + investigator.states:
            _assert_no_hidden_labels(state)

    def test_unrelated_shell_flag_is_false_positive_for_fraud_path_reward(self):
        candidates = [
            SimpleNamespace(shell_company=True, fraud_path_involved=True, flagged=True),
            SimpleNamespace(shell_company=True, fraud_path_involved=False, flagged=True),
            SimpleNamespace(shell_company=False, fraud_path_involved=True, flagged=False),
        ]
        self.assertEqual(0.0, investigator_terminal_reward(candidates))

    def test_completed_scenario_with_incorrect_flag_is_rejected_without_terminal_updates(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(
            client, shell_company=False, flagged=True, correctly_flagged=False
        )
        fraudster, investigator = self._policies(client, reader)
        investigator.action_sequence = [
            {"action_type": "OBSERVE_COMPANY", "company_id": 1},
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 1},
            {"action_type": "FLAG_COMPANY", "company_id": 1},
        ]

        with self.assertRaisesRegex(EvaluatorDataError, "lacks validated correct-flag"):
            RLTrainingRunner(client, reader).run_episode(
                source_company_id=1,
                target_company_id=2,
                amount="10",
                fraudster=fraudster,
                investigator=investigator,
                max_actions=4,
                private_shell_knowledge_provider=lambda _scenario_id: [],
            )

        self.assertTrue(client.state["financialObjectiveAchieved"])
        self.assertEqual("COMPLETED", client.state["status"])
        self.assertEqual(3, len(investigator.completed))
        self.assertEqual(1, reader.correct_flag_calls)
        self.assertEqual(0, reader.calls)
        self.assertEqual(["COMPLETED"], reader.status_at_read)
        self.assertEqual([], fraudster.learner.updates)
        self.assertEqual([], investigator.learner.updates)

    def test_missing_private_shell_provider_fails_before_scenario_creation(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(client, shell_company=False, flagged=False)
        fraudster, investigator = self._policies(client, reader)

        with self.assertRaisesRegex(EvaluatorDataError, "authorized private shell-knowledge provider"):
            RLTrainingRunner(client, reader).run_episode(
                source_company_id=1,
                target_company_id=2,
                amount="10",
                fraudster=fraudster,
                investigator=investigator,
            )

        self.assertEqual([], client.events)

    def test_investigator_only_episode_uses_non_rl_opponent_and_never_requests_private_context(self):
        client = FakeClient(flag_on_first_investigator_action=True)
        reader = GroundTruthReaderSpy(
            client, shell_company=True, flagged=True, correctly_flagged=True
        )
        investigator = InvestigatorPolicySpy(client, reader, flag_first=True)

        result = RLTrainingRunner(client, reader).run_episode(
            source_company_id=1,
            target_company_id=2,
            amount="10",
            fraudster=FraudsterBot(),
            investigator=investigator,
            max_actions=4,
            train_fraudster=False,
        )

        self.assertEqual("COMPLETED", result["terminal_outcome"])
        self.assertIsNone(result["fraudster_reward"])
        self.assertEqual(0, result["transition_counts"]["fraudster"])
        self.assertEqual(1.0, result["investigator_training_reward"])
        self.assertEqual(0, reader.correct_flag_calls)
        self.assertEqual(1, reader.calls)
        self.assertEqual({SCENARIO_ID: [1, 2]}, reader.captured_candidate_ids)
        self.assertTrue(investigator.learner.updates)
        for state in investigator.states:
            _assert_no_hidden_labels(state)

    def test_shell_path_coverage_executes_legal_route_and_labels_persisted_endpoints(self):
        client = FakeClient(flag_on_first_investigator_action=True)
        class RouteCandidatePolicy(InvestigatorPolicySpy):
            def legal_actions(self, state):
                ids = {1, 2}
                ids.update((position.get("company") or {}).get("id")
                           for position in state.get("positions", []))
                return [
                    {"action_type": action_type, "company_id": company_id}
                    for company_id in sorted(ids)
                    for action_type in ("OBSERVE_COMPANY", "FLAG_COMPANY")
                ]

        policy = RouteCandidatePolicy(
            client, SimpleNamespace(calls=0, correct_flag_calls=0), flag_first=True
        )

        class PathReader:
            calls = 0
            correct_flag_calls = 0

            def read_discovered_candidates(self, scenario_ids, candidate_ids):
                self.calls += 1
                self.labels = []
                path_company_ids = set()
                for transaction in client.history:
                    if transaction.get("origin") != "FRAUDSTER_ACTION":
                        continue
                    path_company_ids.add(transaction["sourceCompany"]["id"])
                    path_company_ids.add(transaction["destinationCompany"]["id"])
                for scenario_id, company_ids in candidate_ids.items():
                    for company_id in company_ids:
                        self.labels.append(SimpleNamespace(
                            scenario_id=scenario_id,
                            company_id=company_id,
                            shell_company=company_id == 3,
                            fraud_path_involved=company_id in path_company_ids,
                            flagged=False,
                        ))
                return self.labels

        reader = PathReader()
        result = RLTrainingRunner(client, reader).run_episode(
            source_company_id=1, target_company_id=2, amount="10",
            fraudster=FraudsterBot(), investigator=policy, max_actions=4,
            train_fraudster=False,
            private_shell_knowledge_provider=lambda scenario_id: [3],
            ensure_shell_path=True,
        )

        route_action = next(
            event for event in client.events if event[0] == "create_fraudster_action"
        )
        persisted_shell_edges = [
            transaction for transaction in client.history
            if transaction["origin"] == "FRAUDSTER_ACTION"
            and transaction["destinationCompany"]["id"] == 3
        ]
        self.assertEqual(SCENARIO_ID, route_action[1])
        self.assertEqual(1, len(persisted_shell_edges))
        self.assertEqual("ROUTE_TRANSFER", client.pending_action["action_type"])
        self.assertEqual(3, persisted_shell_edges[0]["destinationCompany"]["id"])
        self.assertEqual(1, result["fraudster_action_type_counts"]["ROUTE_TRANSFER"])
        self.assertEqual(1, result["path_positive_candidate_count"])
        self.assertEqual(2, result["path_negative_candidate_count"])
        self.assertEqual({1, 2, 3}, set(reader.labels[i].company_id for i in range(3)))
        labels_by_company = {label.company_id: label for label in reader.labels}
        self.assertTrue(labels_by_company[3].fraud_path_involved)
        self.assertFalse(labels_by_company[2].fraud_path_involved)

    def test_existing_scenario_training_updates_compatible_checkpoints_and_is_run_scoped(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(
            client, shell_company=True, flagged=True, correctly_flagged=True
        )
        requested_scenarios = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fraudster_input = root / "fraudster-input.json"
            investigator_input = root / "investigator-input.json"
            fraudster_output = root / "fraudster-output.json"
            investigator_output = root / "investigator-output.json"
            QLearningAgent.for_role("fraudster", seed=2).save(fraudster_input)
            QLearningAgent.for_role("investigator", seed=3).save(investigator_input)

            result = train_existing_scenario(
                client,
                reader,
                scenario_id=SCENARIO_ID,
                max_actions=8,
                seed=5,
                fraudster_checkpoint=fraudster_input,
                investigator_checkpoint=investigator_input,
                fraudster_output_checkpoint=fraudster_output,
                investigator_output_checkpoint=investigator_output,
                private_shell_knowledge_provider=lambda scenario_id: (
                    requested_scenarios.append(scenario_id) or []
                ),
            )

            self.assertTrue(result["episode_completed"])
            self.assertGreater(result["transition_counts"]["fraudster"], 0)
            self.assertEqual(SCENARIO_ID, result["scenario_id"])
            self.assertEqual(
                [SCENARIO_ID] * (result["transition_counts"]["fraudster"] * 2),
                requested_scenarios,
            )
            self.assertFalse(any(event[0] == "create" for event in client.events))
            trained_fraudster = QLearningAgent.load(fraudster_output)
            trained_investigator = QLearningAgent.load(investigator_output)
            self.assertEqual(checkpoint_compatibility("fraudster"), trained_fraudster.compatibility)
            self.assertEqual(checkpoint_compatibility("investigator"), trained_investigator.compatibility)
            self.assertGreater(trained_fraudster.training_steps, 0)
            self.assertGreater(trained_investigator.training_steps, 0)
            self.assertEqual(0, QLearningAgent.load(fraudster_input).training_steps)
            self.assertEqual(0, QLearningAgent.load(investigator_input).training_steps)

    def test_existing_scenario_training_rejects_incompatible_checkpoint_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fraudster_input = root / "fraudster-input.json"
            investigator_input = root / "investigator-input.json"
            fraudster_output = root / "fraudster-output.json"
            investigator_output = root / "investigator-output.json"
            bad_compatibility = checkpoint_compatibility("fraudster")
            bad_compatibility["state_abstraction_version"] = "old-fraudster-state"
            QLearningAgent(compatibility=bad_compatibility).save(fraudster_input)
            QLearningAgent.for_role("investigator").save(investigator_input)
            client = FakeClient()
            reader = GroundTruthReaderSpy(client, shell_company=False, flagged=False)

            with self.assertRaisesRegex(ValueError, "incompatible"):
                train_existing_scenario(
                    client,
                    reader,
                    scenario_id=SCENARIO_ID,
                    max_actions=8,
                    seed=5,
                    fraudster_checkpoint=fraudster_input,
                    investigator_checkpoint=investigator_input,
                    fraudster_output_checkpoint=fraudster_output,
                    investigator_output_checkpoint=investigator_output,
                    private_shell_knowledge_provider=lambda _scenario_id: [],
                )

            self.assertFalse(fraudster_output.exists())
            self.assertFalse(investigator_output.exists())
            self.assertEqual([], client.events)

    def test_managed_fresh_training_writes_current_compatibility_after_updates(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(
            client, shell_company=True, flagged=True, correctly_flagged=True
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fraudster_output = root / "fraudster-fresh.json"
            investigator_output = root / "investigator-fresh.json"
            result = train_existing_scenario(
                client,
                reader,
                scenario_id=SCENARIO_ID,
                max_actions=8,
                seed=17,
                fraudster_checkpoint=None,
                investigator_checkpoint=None,
                fraudster_output_checkpoint=fraudster_output,
                investigator_output_checkpoint=investigator_output,
                private_shell_knowledge_provider=lambda _scenario_id: [],
                initialize_fresh=True,
            )

            fraudster = QLearningAgent.load(fraudster_output)
            investigator = QLearningAgent.load(investigator_output)
            self.assertGreater(result["transition_counts"]["fraudster"], 0)
            self.assertGreater(fraudster.training_steps, 0)
            self.assertGreater(investigator.training_steps, 0)
            self.assertEqual(checkpoint_compatibility("fraudster"), fraudster.compatibility)
            self.assertEqual(checkpoint_compatibility("investigator"), investigator.compatibility)
            self.assertEqual(
                "application_managed_fresh_existing_scenario",
                fraudster.metadata["training_provenance"]["training_mode"],
            )

    def test_failed_terminal_ground_truth_does_not_write_training_checkpoints(self):
        class MissingLabels(GroundTruthReaderSpy):
            def read_correct_flag_outcomes(self, scenario_ids):
                return {scenario_id: True for scenario_id in scenario_ids}

            def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
                raise EvaluatorDataError("ground truth unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fraudster_input = root / "fraudster-input.json"
            investigator_input = root / "investigator-input.json"
            fraudster_output = root / "fraudster-output.json"
            investigator_output = root / "investigator-output.json"
            QLearningAgent.for_role("fraudster").save(fraudster_input)
            QLearningAgent.for_role("investigator").save(investigator_input)
            client = FakeClient()
            reader = MissingLabels(client, shell_company=False, flagged=False)

            with self.assertRaisesRegex(EvaluatorDataError, "ground truth unavailable"):
                train_existing_scenario(
                    client,
                    reader,
                    scenario_id=SCENARIO_ID,
                    max_actions=8,
                    seed=5,
                    fraudster_checkpoint=fraudster_input,
                    investigator_checkpoint=investigator_input,
                    fraudster_output_checkpoint=fraudster_output,
                    investigator_output_checkpoint=investigator_output,
                    private_shell_knowledge_provider=lambda _scenario_id: [],
                )

            self.assertFalse(fraudster_output.exists())
            self.assertFalse(investigator_output.exists())

    def test_output_collision_preserves_existing_file_and_rolls_back_partial_checkpoint(self):
        client = FakeClient()
        reader = GroundTruthReaderSpy(
            client, shell_company=True, flagged=True, correctly_flagged=True
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fraudster_input = root / "fraudster-input.json"
            investigator_input = root / "investigator-input.json"
            fraudster_output = root / "fraudster-output.json"
            investigator_output = root / "investigator-output.json"
            QLearningAgent.for_role("fraudster").save(fraudster_input)
            QLearningAgent.for_role("investigator").save(investigator_input)
            investigator_output.write_text("pre-existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                train_existing_scenario(
                    client,
                    reader,
                    scenario_id=SCENARIO_ID,
                    max_actions=8,
                    seed=5,
                    fraudster_checkpoint=fraudster_input,
                    investigator_checkpoint=investigator_input,
                    fraudster_output_checkpoint=fraudster_output,
                    investigator_output_checkpoint=investigator_output,
                    private_shell_knowledge_provider=lambda _scenario_id: [],
                )

            self.assertFalse(fraudster_output.exists())
            self.assertEqual("pre-existing", investigator_output.read_text(encoding="utf-8"))

    def test_managed_investigator_fresh_then_resume_preserves_learning_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "investigator-first.json"
            second = root / "investigator-second.json"
            for scenario_id, source in ((42, first), (43, second)):
                # The managed API returns the requested scenario ID in its
                # scenario payload; keep the fixture faithful when exercising
                # a second scenario on resume.
                client = FakeClient(scenario_id=scenario_id)
                reader = GroundTruthReaderSpy(client, shell_company=True, flagged=True,
                                          correctly_flagged=True, shell_company_ids={3})
                result = train_existing_investigator_scenario(
                    client, reader, scenario_id=scenario_id, max_actions=8, seed=10,
                    investigator_checkpoint=None if scenario_id == 42 else first,
                    investigator_output_checkpoint=source,
                    private_shell_knowledge_provider=lambda _scenario_id: [3],
                    initialize_fresh=scenario_id == 42,
                )
                self.assertTrue(result["episode_completed"])
                self.assertGreater(result["investigator_training_steps"], 0)
                self.assertEqual(1, reader.calls)  # queried only after terminal
                self.assertEqual(["COMPLETED"], reader.status_at_read)
                self.assertEqual(0, reader.correct_flag_calls)
            learner = QLearningAgent.load(second)
            original = QLearningAgent.load(first)
            self.assertEqual(checkpoint_compatibility("investigator"), learner.compatibility)
            self.assertGreater(learner.training_steps, original.training_steps)
            self.assertEqual((original.learning_rate, original.discount_factor, original.epsilon),
                             (learner.learning_rate, learner.discount_factor, learner.epsilon))
            self.assertTrue(set(original.q_values).issubset(learner.q_values))
            self.assertEqual("application_managed_investigator_resume_existing_scenario",
                             learner.metadata["training_provenance"]["training_mode"])
            episode_provenance = learner.metadata["training_provenance"]["episode_results"][0]
            self.assertTrue(episode_provenance["shell_path_transfer_confirmed"])
            self.assertGreaterEqual(
                episode_provenance["fraudster_action_type_counts"]["ROUTE_TRANSFER"], 1
            )
            self.assertEqual(1, episode_provenance["path_positive_candidate_count"])
            self.assertEqual(2, episode_provenance["path_negative_candidate_count"])

    def test_investigator_candidate_capture_is_pre_decision_deduplicated_and_excludes_late_candidates(self):
        class FinalActionRevealsClient(FakeClient):
            def submit_investigator_action(self, **kwargs):
                response = super().submit_investigator_action(**kwargs)
                if kwargs["action_type"] == "FLAG_COMPANY":
                    # Company 3 becomes available only after the final action.
                    self.state["step"] = 2
                return response

        class CandidateTimingPolicy(InvestigatorPolicySpy):
            def legal_actions(self, state):
                if state["step"] == 1:
                    # Duplicate legal entries must count once.
                    return [
                        {"action_type": "FLAG_COMPANY", "company_id": 1},
                        {"action_type": "FLAG_COMPANY", "company_id": 1},
                        {"action_type": "FLAG_COMPANY", "company_id": 2},
                    ]
                return [{"action_type": "FLAG_COMPANY", "company_id": 3}]

        client = FinalActionRevealsClient(flag_on_first_investigator_action=True)
        reader = GroundTruthReaderSpy(client, shell_company=True, flagged=True)
        investigator = CandidateTimingPolicy(client, reader, flag_first=True)
        result = RLTrainingRunner(client, reader).run_episode(
            source_company_id=1,
            target_company_id=2,
            amount="10",
            fraudster=FraudsterBot(),
            investigator=investigator,
            max_actions=4,
            train_fraudster=False,
        )

        self.assertTrue(result["episode_completed"])
        self.assertEqual({SCENARIO_ID: [1, 2]}, reader.captured_candidate_ids)
        self.assertEqual(1, len(investigator.learner.updates))

    def test_managed_investigator_rejects_v1_and_unmanaged_resume_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad.json"
            out = root / "out.json"
            compatibility = checkpoint_compatibility("investigator")
            compatibility["state_abstraction_version"] = "state-abstraction-v1"
            QLearningAgent(compatibility=compatibility, training_steps=1).save(bad)
            client = FakeClient()
            reader = GroundTruthReaderSpy(client, shell_company=False, flagged=False)
            with self.assertRaisesRegex(ValueError, "incompatible"):
                train_existing_investigator_scenario(
                    client, reader, scenario_id=42, max_actions=8, seed=1,
                    investigator_checkpoint=bad, investigator_output_checkpoint=out,
                )
            self.assertFalse(out.exists())

    def test_managed_investigator_rejects_previous_reward_contract_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "out.json"
            client = FakeClient()
            reader = GroundTruthReaderSpy(client, shell_company=True, flagged=True)

            for old_version in (
                    "observation-reward-contract-v3", "observation-reward-contract-v1"):
                with self.subTest(version=old_version):
                    bad = root / f"{old_version}.json"
                    compatibility = checkpoint_compatibility("investigator")
                    compatibility["observation_reward_contract_version"] = old_version
                    QLearningAgent(compatibility=compatibility, training_steps=1).save(bad)
                    with self.assertRaisesRegex(ValueError, "incompatible"):
                        train_existing_investigator_scenario(
                            client, reader, scenario_id=42, max_actions=8, seed=1,
                            investigator_checkpoint=bad, investigator_output_checkpoint=out,
                        )

            self.assertFalse(out.exists())

    def test_investigator_empty_or_single_class_population_skips_updates_and_checkpoint(self):
        class SingleClassReader(GroundTruthReaderSpy):
            def __init__(self, client, label):
                super().__init__(client, shell_company=label, flagged=False)
                self.label = label

            def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
                self.calls += 1
                self.status_at_read.append(self.client.state["status"])
                candidates = [
                    SimpleNamespace(
                        scenario_id=scenario_id,
                        company_id=company_id,
                        shell_company=self.label,
                        flagged=False,
                        fraud_path_involved=self.label,
                    )
                    for scenario_id, company_ids in candidate_ids_by_scenario.items()
                    for company_id in sorted(company_ids)
                ]
                return candidates

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label in (True, False):
                output = root / f"investigator-{label}.json"
                client = FakeClient(flag_on_first_investigator_action=True)
                reader = SingleClassReader(client, label)

                with self.assertRaisesRegex(
                        EvaluatorDataError,
                        "at least one path-involved shell and one non-positive"):
                    train_existing_investigator_scenario(
                        client, reader, scenario_id=42, max_actions=8, seed=1,
                        investigator_checkpoint=None,
                        investigator_output_checkpoint=output,
                        private_shell_knowledge_provider=lambda _scenario_id: [3],
                        initialize_fresh=True,
                    )

                self.assertFalse(output.exists())
                self.assertEqual(1, reader.calls)
                self.assertEqual(["COMPLETED"], reader.status_at_read)

        class EmptyPopulationClient(FakeClient):
            def submit_investigator_action(self, **kwargs):
                response = super().submit_investigator_action(**kwargs)
                self.state["status"] = "COMPLETED"
                return response

        class NoFlagPolicy(InvestigatorPolicySpy):
            def legal_actions(self, state):
                return []

        class EmptyReader(GroundTruthReaderSpy):
            def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
                self.calls += 1
                self.status_at_read.append(self.client.state["status"])
                self.captured_candidate_ids = candidate_ids_by_scenario
                return []

        client = EmptyPopulationClient()
        reader = EmptyReader(client, shell_company=False, flagged=False)
        investigator = NoFlagPolicy(client, reader)
        with self.assertRaisesRegex(
                EvaluatorDataError,
                "at least one path-involved shell and one non-positive"):
            RLTrainingRunner(client, reader).run_episode(
                source_company_id=1, target_company_id=2, amount="10",
                fraudster=FraudsterBot(), investigator=investigator,
                max_actions=4, train_fraudster=False,
            )
        self.assertEqual([], investigator.learner.updates)
        self.assertEqual({SCENARIO_ID: set()}, reader.captured_candidate_ids)

    def test_failed_investigator_episode_writes_no_output(self):
        class MissingLabels(GroundTruthReaderSpy):
            def read_discovered_candidates(self, scenario_ids, candidate_ids_by_scenario):
                self.status_at_read.append(self.client.state["status"])
                raise EvaluatorDataError("post-terminal labels unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "investigator.json"
            client = FakeClient(flag_on_first_investigator_action=True)
            reader = MissingLabels(client, shell_company=True, flagged=True,
                                   correctly_flagged=True)
            with self.assertRaisesRegex(EvaluatorDataError, "post-terminal labels unavailable"):
                train_existing_investigator_scenario(
                    client, reader, scenario_id=42, max_actions=8, seed=1,
                    investigator_checkpoint=None, investigator_output_checkpoint=out,
                    private_shell_knowledge_provider=lambda _scenario_id: [3],
                    initialize_fresh=True,
                )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
