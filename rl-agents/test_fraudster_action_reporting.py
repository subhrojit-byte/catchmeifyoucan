import contextlib
import io
import unittest
from copy import deepcopy

import evaluate
from client import CatchMeIfYouCanApiError
from run_episode import FRAUDSTER_ACTION_TYPES, run_episode


SCENARIO_ID = 77


def active_fraudster_scenario():
    return {
        "id": SCENARIO_ID,
        "status": "ACTIVE",
        "turn": "FRAUDSTER",
        "step": 0,
        "investigatorActionsRemaining": 0,
        "sourceCompany": {"id": 1},
        "targetCompany": {"id": 2},
        "positions": [{"id": 9, "company": {"id": 1}, "amount": 100}],
    }


class FraudsterActionReportingTest(unittest.TestCase):
    class Fraudster:
        def __init__(self, action_type):
            self.action_type = action_type

        def choose_action(self, state):
            return {
                "action_type": self.action_type,
                "source_position_id": 9,
                "targets": [],
            }

    class Client:
        def __init__(self, response, *, execution_error=None):
            self.response = response
            self.execution_error = execution_error
            self.state = active_fraudster_scenario()

        def get_scenario(self, scenario_id):
            if scenario_id != SCENARIO_ID:
                raise AssertionError("Unexpected scenario ID")
            return deepcopy(self.state)

        def get_scenario_transactions(self, scenario_id):
            if scenario_id != SCENARIO_ID:
                raise AssertionError("Unexpected scenario ID")
            return []

        def create_fraudster_action(self, **kwargs):
            return dict(self.response)

        def execute_fraudster_action(self, action_id):
            if self.execution_error is not None:
                raise self.execution_error
            self.state["status"] = "MAX_TURNS_REACHED"

    def run_one_fraudster_action(self, action_type, response, *, execution_error=None):
        client = self.Client(response, execution_error=execution_error)
        result = {"scenario_id": SCENARIO_ID, "creation_succeeded": True}
        with contextlib.redirect_stdout(io.StringIO()):
            run_episode(
                client,
                scenario_id=SCENARIO_ID,
                result_collector=result,
                fraudster_policy=self.Fraudster(action_type),
            )
        return result

    def test_per_episode_and_aggregate_counts_use_backend_returned_types(self):
        episodes = [
            self.run_one_fraudster_action(action_type, {"id": i, "actionType": action_type})
            for i, action_type in enumerate(FRAUDSTER_ACTION_TYPES, start=1)
        ]
        self.assertEqual(
            list(FRAUDSTER_ACTION_TYPES),
            [episode["fraudster_action_types"][0] for episode in episodes],
        )
        for episode, action_type in zip(episodes, FRAUDSTER_ACTION_TYPES):
            self.assertEqual(1, episode["fraudster_action_counts"][action_type])
            self.assertEqual(1, episode["fraudster_action_counts"]["successful_action_count"])
        aggregate = evaluate.aggregate_episode_results(episodes)
        for action_type in FRAUDSTER_ACTION_TYPES:
            self.assertEqual(1, aggregate["fraudster_action_counts_aggregate"][action_type])
        self.assertEqual(4, aggregate["fraudster_action_counts_aggregate"]["successful_action_count"])
        self.assertEqual(4, aggregate["fraudster_action_counts_aggregate"]["observed_episode_count"])

    def test_missing_returned_type_is_counted_explicitly(self):
        episode = self.run_one_fraudster_action("WAIT", {"id": 1})
        self.assertEqual([None], episode["fraudster_action_types"])
        self.assertEqual(0, episode["fraudster_action_counts"]["WAIT"])
        self.assertEqual(1, episode["fraudster_action_counts"]["missing_action_type_count"])
        self.assertEqual(1, episode["fraudster_action_counts"]["successful_action_count"])

    def test_count_uses_backend_type_instead_of_policy_choice(self):
        episode = self.run_one_fraudster_action(
            "WAIT", {"id": 1, "actionType": "ROUTE_TRANSFER"}
        )
        self.assertEqual(["ROUTE_TRANSFER"], episode["fraudster_action_types"])
        self.assertEqual(1, episode["fraudster_action_counts"]["ROUTE_TRANSFER"])
        self.assertEqual(0, episode["fraudster_action_counts"]["WAIT"])

    def test_investigator_actions_are_not_added_to_fraudster_action_history(self):
        client = self.Client({"id": 1, "actionType": "DIRECT_TRANSFER"})

        def execute_then_offer_investigator_turn(action_id):
            client.state.update(turn="INVESTIGATOR", investigatorActionsRemaining=3)

        def submit_and_terminate(**kwargs):
            client.state["status"] = "MAX_TURNS_REACHED"
            return {}

        client.execute_fraudster_action = execute_then_offer_investigator_turn
        client.submit_investigator_action = submit_and_terminate

        class Investigator:
            def legal_actions(self, state):
                return [{"action_type": "OBSERVE_COMPANY", "company_id": 1}]

            def choose_action(self, state):
                return {"action_type": "OBSERVE_COMPANY", "company_id": 1}

            def sanitize_action_response(self, response, **kwargs):
                return {}

            def mark_action_completed(self, decision, response):
                pass

            def evidence_summary(self):
                return {}

        result = {"scenario_id": SCENARIO_ID, "creation_succeeded": True}
        with contextlib.redirect_stdout(io.StringIO()):
            run_episode(
                client,
                scenario_id=SCENARIO_ID,
                result_collector=result,
                fraudster_policy=self.Fraudster("DIRECT_TRANSFER"),
                investigator_policy=Investigator(),
            )
        self.assertEqual(["DIRECT_TRANSFER"], result["fraudster_action_types"])
        self.assertEqual(1, result["fraudster_action_counts"]["DIRECT_TRANSFER"])
        self.assertEqual(1, result["fraudster_action_counts"]["successful_action_count"])

    def test_failed_execution_does_not_count_created_but_unexecuted_action(self):
        episode = self.run_one_fraudster_action(
            "SPLIT_TRANSFER",
            {"id": 1, "actionType": "SPLIT_TRANSFER"},
            execution_error=CatchMeIfYouCanApiError("execution rejected"),
        )
        self.assertEqual("failed", episode["episode_class"])
        self.assertEqual([], episode["fraudster_action_types"])
        self.assertEqual(0, episode["fraudster_action_counts"]["SPLIT_TRANSFER"])
        self.assertEqual(0, episode["fraudster_action_counts"]["successful_action_count"])


if __name__ == "__main__":
    unittest.main()
