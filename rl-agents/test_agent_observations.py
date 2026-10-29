import unittest

import rl_training
import run_episode
from run_episode import AgentObservationError, build_agent_observation


def scenario_state(scenario_id=41):
    company = {
        "id": 101,
        "companyName": "Visible Co",
        "annualRevenue": "2500000.00",
        "numberOfEmployees": 5,
        "shellCompany": True,
        "flagCorrect": True,
        "evaluatorLabel": "hidden",
    }
    return {
        "id": scenario_id,
        "status": "ACTIVE",
        "turn": "FRAUDSTER",
        "step": 0,
        "investigatorActionsRemaining": 0,
        "targetAmount": "100.00",
        "financialObjectiveAchieved": False,
        "sourceCompany": dict(company),
        "targetCompany": {"id": 102, "companyName": "Target"},
        "positions": [{
            "id": 7,
            "company": dict(company),
            "amount": "100.00",
            "shellCompany": True,
            "flagCorrect": True,
        }],
        "shellCompany": True,
        "flagCorrect": True,
        "groundTruth": {"shellCompany": True, "flagCorrect": True},
    }


def transaction(scenario_id=41):
    company = {
        "id": 101,
        "companyName": "Visible Co",
        "annualRevenue": "2500000.00",
        "shellCompany": True,
        "flagCorrect": True,
    }
    return {
        "id": 501,
        "scenarioId": scenario_id,
        "sourceCompany": dict(company),
        "destinationCompany": {"id": 102, "companyName": "Target"},
        "amount": "12.50",
        "origin": "BACKGROUND",
        "channel": "BANK_TRANSFER",
        "shellCompany": True,
        "flagCorrect": True,
        "labels": {"shellCompany": True},
    }


_DEFAULT_HISTORY = object()


class Client:
    def __init__(self, history=_DEFAULT_HISTORY, error=None):
        self.history = [transaction()] if history is _DEFAULT_HISTORY else history
        self.error = error

    def get_scenario_transactions(self, scenario_id):
        if self.error is not None:
            raise self.error
        return self.history

    def get_eligible_intermediate_companies(self, company_id):
        return [103]

    def get_company(self, company_id):
        return {"id": company_id, "companyName": "Publicly described company", "ageInYears": 1}


class AgentObservationTest(unittest.TestCase):
    def test_training_and_live_paths_share_role_observations(self):
        self.assertIs(rl_training.build_agent_observation, run_episode.build_agent_observation)
        for role in ("FRAUDSTER", "INVESTIGATOR"):
            with self.subTest(role=role):
                live = run_episode.build_agent_observation(
                    Client(), 41, scenario_state(), role=role
                )
                training = rl_training.build_agent_observation(
                    Client(), 41, scenario_state(), role=role
                )
                self.assertEqual(live, training)
                self.assertEqual(41, live["transactionHistory"][0]["scenarioId"])

    def test_authorized_private_shell_knowledge_is_fraudster_only(self):
        observations = run_episode.build_agent_observations(
            Client(), 41, scenario_state(), private_shell_company_ids=[103]
        )
        self.assertEqual([103], observations["FRAUDSTER"]["privateShellCompanyIds"])
        self.assertNotIn("privateShellCompanyIds", observations["INVESTIGATOR"])
        self.assertNotIn("eligibleIntermediateCompanyIds", observations["INVESTIGATOR"])
        self.assertNotIn("shellCompany", observations["FRAUDSTER"])
        self.assertNotIn("shellCompany", observations["INVESTIGATOR"])
        self.assertNotIn("flagCorrect", observations["FRAUDSTER"])
        self.assertNotIn("flagCorrect", observations["INVESTIGATOR"])
        self.assertEqual("Publicly described company",
                         observations["FRAUDSTER"]["eligibleIntermediaries"][0]["companyName"])
        self.assertNotIn("fraudsterRunCredential", observations["FRAUDSTER"])
        self.assertNotIn("fraudsterRunCredential", observations["INVESTIGATOR"])
        self.assertNotIn("runId", observations["INVESTIGATOR"])

    def test_private_shell_ids_must_be_validated_scenario_intermediaries(self):
        with self.assertRaisesRegex(AgentObservationError, "outside validated"):
            run_episode.build_agent_observation(
                Client(), 41, scenario_state(), role="FRAUDSTER",
                private_shell_company_ids=[999],
            )

    def test_investigator_projection_discards_private_ids(self):
        raw_state = scenario_state()
        raw_state["fraudPathInvolved"] = True
        raw_state["pathShellCompany"] = True
        investigator = run_episode.build_agent_observation(
            Client(), 41, raw_state, role="INVESTIGATOR",
            private_shell_company_ids=[103],
        )
        self.assertNotIn("privateShellCompanyIds", investigator)
        self.assertNotIn("fraudPathInvolved", investigator)
        self.assertNotIn("pathShellCompany", investigator)

    def test_history_is_scenario_scoped_and_cross_scenario_data_fails_closed(self):
        valid = build_agent_observation(
            Client([transaction(41)]), 41, scenario_state(), role="INVESTIGATOR"
        )
        self.assertEqual([501], [item["id"] for item in valid["transactionHistory"]])

        with self.assertRaisesRegex(AgentObservationError, "another scenario"):
            build_agent_observation(
                Client([transaction(41), transaction(42)]),
                41,
                scenario_state(),
                role="INVESTIGATOR",
            )

    def test_history_fetch_errors_are_consistent_for_both_roles(self):
        for role in ("FRAUDSTER", "INVESTIGATOR"):
            with self.subTest(role=role):
                with self.assertRaisesRegex(AgentObservationError, "Unable to fetch"):
                    build_agent_observation(
                        Client(error=OSError("unavailable")),
                        41,
                        scenario_state(),
                        role=role,
                    )

    def test_malformed_required_history_fails_consistently_for_training_and_live(self):
        invalid_amount = transaction()
        invalid_amount["amount"] = "NaN"
        malformed_histories = [None, {"not": "a list"}, ["not a transaction"],
                               [{"id": 0, "scenarioId": 41}],
                               [transaction(42)], [transaction(True)],
                               [invalid_amount]]
        for history in malformed_histories:
            with self.subTest(history=history):
                results = []
                for builder in (run_episode.build_agent_observation,
                                rl_training.build_agent_observation):
                    with self.assertRaises(AgentObservationError) as raised:
                        builder(Client(history), 41, scenario_state(), role="FRAUDSTER")
                    results.append(str(raised.exception))
                self.assertEqual(results[0], results[1])

    def test_boolean_scenario_ids_are_not_accepted_as_integer_ids(self):
        malformed_scenario = scenario_state()
        malformed_scenario["id"] = True
        with self.assertRaisesRegex(AgentObservationError, "ID is missing or mismatched"):
            build_agent_observation(
                Client([transaction(1)]), 1, malformed_scenario, role="FRAUDSTER"
            )

    def test_hidden_and_unknown_labels_are_removed_at_all_nested_levels(self):
        clean_state = scenario_state()
        contaminated_state = scenario_state()
        clean_state["sourceCompany"].pop("shellCompany")
        clean_state["sourceCompany"].pop("flagCorrect")
        clean_state["sourceCompany"].pop("evaluatorLabel")
        clean_state["positions"][0]["company"].pop("shellCompany")
        clean_state["positions"][0]["company"].pop("flagCorrect")
        clean_state["positions"][0]["company"].pop("evaluatorLabel")
        clean_state["positions"][0].pop("shellCompany")
        clean_state["positions"][0].pop("flagCorrect")
        clean_state.pop("shellCompany")
        clean_state.pop("flagCorrect")
        clean_state.pop("groundTruth")

        clean_history = [transaction()]
        for item in (clean_history[0],):
            item.pop("shellCompany")
            item.pop("flagCorrect")
            item.pop("labels")
            item["sourceCompany"].pop("shellCompany")
            item["sourceCompany"].pop("flagCorrect")
        clean = build_agent_observation(
            Client(clean_history), 41, clean_state, role="INVESTIGATOR"
        )
        contaminated = build_agent_observation(
            Client([transaction()]), 41, contaminated_state, role="INVESTIGATOR"
        )
        self.assertEqual(clean, contaminated)

        def assert_no_hidden(value):
            if isinstance(value, dict):
                self.assertNotIn("shellCompany", value)
                self.assertNotIn("flagCorrect", value)
                self.assertNotIn("groundTruth", value)
                self.assertNotIn("evaluatorLabel", value)
                for nested in value.values():
                    assert_no_hidden(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_no_hidden(nested)

        assert_no_hidden(contaminated)


if __name__ == "__main__":
    unittest.main()
