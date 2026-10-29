import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fraudster_bot import FraudsterPolicyError
from ground_truth import EvaluatorDataError
from investigator_bot import InvestigatorPolicyError
from q_learning import QLearningAgent, checkpoint_compatibility
from rl_policies import RLFraudsterPolicy, RLInvestigatorPolicy
from rl_training import (
    FRAUDSTER_OBJECTIVE_REWARD,
    FRAUDSTER_DETECTION_PENALTY,
    FRAUDSTER_EVASION_REWARD,
    Transition,
    apply_delayed_terminal_reward,
    fraudster_terminal_reward,
    investigator_terminal_reward,
)
from run_episode import with_required_scenario_transaction_history
from state_abstraction import (
    INVESTIGATOR_STATE_ABSTRACTION_VERSION,
    LEGAL_ACTION_SCHEMA_VERSION,
    STATE_ABSTRACTION_VERSION,
    fraudster_state_key,
    investigator_state_key,
    legal_fraudster_actions,
    legal_investigator_actions,
)


def state(turn="FRAUDSTER"):
    company = lambda identifier: {"id": identifier, "ageInYears": 4, "annualRevenue": 100, "numberOfEmployees": 2}
    return {
        "id": 1, "status": "ACTIVE", "turn": turn, "step": 0,
        "targetAmount": "100", "financialObjectiveAchieved": False,
        "investigatorActionsRemaining": 3,
        "sourceCompany": company(10), "targetCompany": company(11),
        "positions": [{"id": 20, "company": company(10), "amount": "100"}],
    }


def traced_transaction(transaction_id=700, scenario_id=1):
    return {
        "id": transaction_id,
        "sourceCompany": {"id": 10},
        "destinationCompany": {"id": 12},
        "amount": "25.00",
        "origin": "BACKGROUND",
        "scenarioId": scenario_id,
    }


class RLFoundationTest(unittest.TestCase):
    def test_role_specific_policy_save_paths_write_compatibility_metadata(self):
        fraudster = QLearningAgent(seed=1)
        RLFraudsterPolicy(fraudster)
        investigator = QLearningAgent(seed=2)
        RLInvestigatorPolicy(investigator)
        with tempfile.TemporaryDirectory() as directory:
            fraudster_path = Path(directory) / "fraudster.json"
            investigator_path = Path(directory) / "investigator.json"
            fraudster.save(fraudster_path)
            investigator.save(investigator_path)
            self.assertEqual(
                "fraudster", json.loads(fraudster_path.read_text())["compatibility"]["policy_role"]
            )
            self.assertEqual(
                "investigator", json.loads(investigator_path.read_text())["compatibility"]["policy_role"]
            )

    def test_role_mismatch_cannot_be_silently_swapped(self):
        learner = QLearningAgent.for_role("investigator")
        with self.assertRaises(ValueError):
            RLFraudsterPolicy(learner)

    def test_state_schema_version_changes_only_for_fraudster_checkpoint(self):
        self.assertEqual(
            "state-abstraction-v3",
            checkpoint_compatibility("investigator")["state_abstraction_version"],
        )
        self.assertEqual("state-abstraction-v3", INVESTIGATOR_STATE_ABSTRACTION_VERSION)
        self.assertEqual(
            "fraudster-state-abstraction-v4",
            checkpoint_compatibility("fraudster")["state_abstraction_version"],
        )
        self.assertEqual("legal-actions-v2", LEGAL_ACTION_SCHEMA_VERSION)
        self.assertEqual("fraudster-state-abstraction-v4", STATE_ABSTRACTION_VERSION)

    def test_old_investigator_state_checkpoint_is_rejected(self):
        learner = QLearningAgent.for_role("investigator")
        learner.compatibility["state_abstraction_version"] = "state-abstraction-v2"
        with self.assertRaisesRegex(ValueError, "compatibility metadata"):
            RLInvestigatorPolicy(learner)

    def test_investigator_route_state_distinguishes_public_intermediary_paths(self):
        def company(company_id, *, employees, revenue):
            return {
                "id": company_id,
                "ageInYears": 8,
                "numberOfEmployees": employees,
                "annualRevenue": revenue,
                "address": "Public business address",
            }

        def route(intermediary_id, *, employees, revenue, amount="50"):
            source = company(303, employees=100, revenue=1000000)
            intermediary = company(
                intermediary_id, employees=employees, revenue=revenue
            )
            target = company(304, employees=500, revenue=20000000)
            observation = state("INVESTIGATOR")
            observation.update({
                "sourceCompany": source,
                "targetCompany": target,
                "targetAmount": "100",
                "positions": [{"id": 20, "company": source, "amount": "0"}],
                "transactionHistory": [
                    {
                        "id": 701,
                        "scenarioId": 1,
                        "origin": "FRAUDSTER_ACTION",
                        "amount": amount,
                        "sourceCompany": source,
                        "destinationCompany": intermediary,
                    },
                    {
                        "id": 702,
                        "scenarioId": 1,
                        "origin": "FRAUDSTER_ACTION",
                        "amount": amount,
                        "sourceCompany": intermediary,
                        "destinationCompany": target,
                    },
                ],
            })
            return observation

        pioneer_route = route(305, employees=10, revenue=250000)
        united_route = route(306, employees=500, revenue=20000000)
        self.assertNotEqual(
            investigator_state_key(pioneer_route),
            investigator_state_key(united_route),
        )

    def test_investigator_route_state_includes_bounded_amount_patterns(self):
        observation = state("INVESTIGATOR")
        source = {"id": 303, "ageInYears": 5, "numberOfEmployees": 10}
        intermediary = {"id": 305, "ageInYears": 8, "numberOfEmployees": 20}
        target = {"id": 304, "ageInYears": 15, "numberOfEmployees": 100}
        observation.update({
            "sourceCompany": source,
            "targetCompany": target,
            "targetAmount": "100",
        })

        def history(amount):
            return [
                {"id": 1, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                 "amount": amount, "sourceCompany": source,
                 "destinationCompany": intermediary},
                {"id": 2, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                 "amount": amount, "sourceCompany": intermediary,
                 "destinationCompany": target},
            ]

        half_transfers = json.loads(json.dumps(observation))
        quarter_transfers = json.loads(json.dumps(observation))
        half_transfers["transactionHistory"] = history("50")
        quarter_transfers["transactionHistory"] = history("25")
        self.assertNotEqual(
            investigator_state_key(half_transfers),
            investigator_state_key(quarter_transfers),
        )

    def test_investigator_route_state_is_deterministic_and_ignores_hidden_labels(self):
        observation = state("INVESTIGATOR")
        source = {"id": 10, "ageInYears": 5, "annualRevenue": 100000}
        intermediary = {"id": 12, "ageInYears": 8, "numberOfEmployees": 20}
        target = {"id": 11, "ageInYears": 15, "annualRevenue": 2000000}
        observation.update({
            "sourceCompany": source,
            "targetCompany": target,
            "targetAmount": "100",
            "transactionHistory": [
                {"id": 700, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                 "amount": "50", "sourceCompany": source,
                 "destinationCompany": intermediary},
                {"id": 701, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                 "amount": "50", "sourceCompany": intermediary,
                 "destinationCompany": target},
            ],
        })
        expected = investigator_state_key(observation)
        self.assertEqual(expected, investigator_state_key(observation))

        changed = json.loads(json.dumps(observation))
        changed["shellCompany"] = True
        changed["flagCorrect"] = True
        changed["privateShellCompanyIds"] = [12]
        for transaction in changed["transactionHistory"]:
            transaction["shellCompany"] = True
            transaction["flagCorrect"] = False
            for endpoint in (transaction["sourceCompany"],
                             transaction["destinationCompany"]):
                endpoint["shellCompany"] = True
                endpoint["flagCorrect"] = False
        self.assertEqual(expected, investigator_state_key(changed))

        reversed_history = json.loads(json.dumps(observation))
        reversed_history["transactionHistory"].reverse()
        self.assertEqual(expected, investigator_state_key(reversed_history))

    def test_investigator_route_state_handles_missing_and_empty_history(self):
        missing = state("INVESTIGATOR")
        empty = json.loads(json.dumps(missing))
        empty["transactionHistory"] = []
        malformed = json.loads(json.dumps(missing))
        malformed["transactionHistory"] = None
        self.assertEqual(investigator_state_key(missing), investigator_state_key(empty))
        self.assertEqual(investigator_state_key(missing), investigator_state_key(malformed))

    def test_state_abstraction_ignores_ids_raw_amounts_and_hidden_fields(self):
        original = state()
        changed = json.loads(json.dumps(original))
        changed["sourceCompany"]["id"] = 999999
        changed["sourceCompany"]["shellCompany"] = True
        changed["positions"][0]["amount"] = "75"
        changed["flagCorrect"] = True
        self.assertEqual(fraudster_state_key(original), fraudster_state_key(changed))
        changed["positions"][0]["amount"] = "100"
        self.assertEqual(fraudster_state_key(original), fraudster_state_key(changed))

    def test_fraudster_state_uses_bounded_history_features_without_raw_ids(self):
        original = state()
        original["transactionHistory"] = [traced_transaction()]
        changed = json.loads(json.dumps(original))
        changed["transactionHistory"][0]["id"] = 99999
        changed["transactionHistory"][0]["sourceCompany"]["id"] = 55
        self.assertEqual(fraudster_state_key(original), fraudster_state_key(changed))
        changed["transactionHistory"][0]["amount"] = "80"
        self.assertNotEqual(fraudster_state_key(original), fraudster_state_key(changed))

    def test_fraudster_private_shell_knowledge_is_explicit_and_affects_state(self):
        original = state()
        original["privateShellCompanyIds"] = []
        known = json.loads(json.dumps(original))
        known["privateShellCompanyIds"] = [12]
        self.assertNotEqual(fraudster_state_key(original), fraudster_state_key(known))
        self.assertEqual(fraudster_state_key(known), fraudster_state_key(known))

    def test_training_history_refresh_is_scenario_scoped_and_sanitized(self):
        transaction = traced_transaction()
        transaction["shellCompany"] = True
        transaction["flagCorrect"] = True

        class Client:
            def get_scenario_transactions(self, scenario_id):
                self.requested_scenario_id = scenario_id
                transaction["scenarioId"] = scenario_id
                return [transaction]

        client = Client()
        refreshed = with_required_scenario_transaction_history(client, 1, state())
        self.assertEqual(1, client.requested_scenario_id)
        self.assertEqual(1, refreshed["transactionHistory"][0]["scenarioId"])
        self.assertNotIn("shellCompany", refreshed["transactionHistory"][0])
        self.assertNotIn("flagCorrect", refreshed["transactionHistory"][0])

    def test_detection_is_negative_and_evasion_is_separate_from_objective(self):
        caught = [Transition("s", {"action_type": "FLAG_COMPANY"}, None, ())]
        self.assertEqual(FRAUDSTER_DETECTION_PENALTY, fraudster_terminal_reward(
            {"status": "COMPLETED", "financialObjectiveAchieved": True},
            caught,
            correctly_flagged=True,
        ))
        self.assertEqual(FRAUDSTER_EVASION_REWARD, fraudster_terminal_reward(
            {"status": "MAX_TURNS_REACHED", "financialObjectiveAchieved": False},
            [],
            correctly_flagged=False,
        ))
        self.assertEqual(FRAUDSTER_EVASION_REWARD + FRAUDSTER_OBJECTIVE_REWARD,
                         fraudster_terminal_reward(
                             {"status": "MAX_TURNS_REACHED", "financialObjectiveAchieved": True},
                             [],
                             correctly_flagged=False,
                         ))

    def test_terminal_reward_rejects_inconsistent_status_and_evaluator_evidence(self):
        flag = [Transition("s", {"action_type": "FLAG_COMPANY"}, None, ())]
        with self.assertRaises(EvaluatorDataError):
            fraudster_terminal_reward(
                {"status": "COMPLETED", "financialObjectiveAchieved": True},
                flag,
                correctly_flagged=False,
            )
        with self.assertRaises(EvaluatorDataError):
            fraudster_terminal_reward(
                {"status": "MAX_TURNS_REACHED", "financialObjectiveAchieved": False},
                [],
                correctly_flagged=True,
            )
        with self.assertRaises(EvaluatorDataError):
            fraudster_terminal_reward(
                {"status": "CANCELLED", "financialObjectiveAchieved": False},
                [],
                correctly_flagged=False,
            )
    def test_legal_action_filters_obey_turn_budget_and_candidate_population(self):
        self.assertEqual(2, len(legal_fraudster_actions(state())))
        self.assertEqual([], legal_fraudster_actions(state("INVESTIGATOR")))
        at_destination = state()
        at_destination["positions"] = [
            {"id": 21, "company": {"id": 11}, "amount": "100"}
        ]
        self.assertEqual([{"action_type": "WAIT", "source_position_id": 21, "targets": []}],
                         legal_fraudster_actions(at_destination))

    def test_route_and_split_actions_use_only_supplied_eligible_ids(self):
        observation = state()
        observation["eligibleIntermediateCompanyIds"] = {"10": [12, 13, 11, 10, "999", True]}
        observation["eligibleIntermediaries"] = [{"id": 12}, {"id": 13}]
        actions = legal_fraudster_actions(observation)
        routes = [item for item in actions if item["action_type"] == "ROUTE_TRANSFER"]
        splits = [item for item in actions if item["action_type"] == "SPLIT_TRANSFER"]
        self.assertEqual([12, 13], [item["targets"][0]["destinationCompanyId"] for item in routes])
        self.assertEqual(1, len(splits))
        self.assertEqual(Decimal("100"), sum(
            (Decimal(t["amount"]) for t in splits[0]["targets"]), Decimal(0)
        ))
        missing = state()
        self.assertFalse(any(item["action_type"] in {"ROUTE_TRANSFER", "SPLIT_TRANSFER"}
                             for item in legal_fraudster_actions(missing)))
        empty = state()
        empty["eligibleIntermediateCompanyIds"] = {"10": []}
        empty["eligibleIntermediaries"] = []
        self.assertFalse(any(item["action_type"] in {"ROUTE_TRANSFER", "SPLIT_TRANSFER"}
                             for item in legal_fraudster_actions(empty)))
        observation["eligibleIntermediateCompanyIds"] = {"10": [999]}
        observation["eligibleIntermediaries"] = []
        self.assertFalse(any(item["action_type"] in {"ROUTE_TRANSFER", "SPLIT_TRANSFER"}
                             for item in legal_fraudster_actions(observation)))
        investigator_state = state("INVESTIGATOR")
        actions = legal_investigator_actions(investigator_state)
        self.assertTrue(actions)
        self.assertTrue(all(action.get("company_id") in {10, 11} for action in actions if "company_id" in action))
        investigator_state["investigatorActionsRemaining"] = 0
        self.assertEqual([], legal_investigator_actions(investigator_state))

    def test_legal_actions_include_positions_and_confirmed_discoveries(self):
        investigator_state = state("INVESTIGATOR")
        investigator_state["positions"].append(
            {"id": 21, "company": {"id": 12}, "amount": "5"}
        )
        actions = legal_investigator_actions(
            investigator_state,
            candidate_company_ids={13},
            observed_company_ids={13},
        )
        company_ids = {
            action["company_id"] for action in actions if "company_id" in action
        }
        self.assertEqual({10, 11, 12, 13}, company_ids)

    def test_trace_actions_require_current_scenario_history_ids(self):
        investigator_state = state("INVESTIGATOR")
        investigator_state["transactionHistory"] = [traced_transaction()]
        actions = legal_investigator_actions(
            investigator_state,
            trace_transaction_ids=[700],
        )
        self.assertIn({"action_type": "TRACE_TRANSACTION", "transaction_id": 700}, actions)
        self.assertNotIn(
            {"action_type": "TRACE_TRANSACTION", "transaction_id": 701}, actions
        )

    def test_duplicate_trace_and_flag_actions_are_excluded(self):
        investigator_state = state("INVESTIGATOR")
        investigator_state["transactionHistory"] = [traced_transaction()]
        actions = legal_investigator_actions(
            investigator_state,
            completed_actions={
                ("TRACE_TRANSACTION", 700),
                ("FLAG_COMPANY", 10),
            },
            trace_transaction_ids=[700],
        )
        self.assertNotIn(
            {"action_type": "TRACE_TRANSACTION", "transaction_id": 700}, actions
        )
        self.assertNotIn(
            {"action_type": "FLAG_COMPANY", "company_id": 10}, actions
        )

    def test_rl_policy_adds_director_and_trace_endpoints_only_after_confirmation(self):
        policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        investigator_state = state("INVESTIGATOR")
        investigator_state["transactionHistory"] = [traced_transaction()]

        before = legal_investigator_actions(
            investigator_state,
            trace_transaction_ids=[700],
        )
        self.assertNotIn({"action_type": "FLAG_COMPANY", "company_id": 12}, before)

        policy.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 10},
            {"directorInvestigation": {
                "directors": [{"associatedCompanies": [{"id": 13}]}]
            }},
        )
        policy.mark_action_completed(
            {"action_type": "TRACE_TRANSACTION", "transaction_id": 700},
            {"transactionTrace": traced_transaction()},
        )
        actions = legal_investigator_actions(
            investigator_state,
            completed_actions=policy.completed_actions,
            candidate_company_ids=policy._candidate_company_ids(investigator_state),
            observed_company_ids=policy._observed_company_ids_for_state(investigator_state),
            trace_transaction_ids=[700],
        )
        self.assertIn({"action_type": "FLAG_COMPANY", "company_id": 13}, actions)
        self.assertIn({"action_type": "FLAG_COMPANY", "company_id": 12}, actions)

    def test_unconfirmed_actions_remain_retryable(self):
        policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        investigator_state = state("INVESTIGATOR")
        investigator_state["transactionHistory"] = [traced_transaction()]
        actions = legal_investigator_actions(
            investigator_state,
            trace_transaction_ids=[700],
        )
        self.assertIn(
            {"action_type": "TRACE_TRANSACTION", "transaction_id": 700}, actions
        )
        self.assertNotIn(("TRACE_TRANSACTION", 700), policy.completed_actions)

    def test_epsilon_zero_is_deterministic_and_seeded_exploration_repeats(self):
        greedy = QLearningAgent(epsilon=0, seed=1)
        greedy.update(("s",), "b", 2, None, done=True)
        greedy.update(("s",), "a", 1, None, done=True)
        self.assertEqual("b", greedy.select_action(("s",), ["a", "b"]))
        first = QLearningAgent(epsilon=1, seed=7)
        second = QLearningAgent(epsilon=1, seed=7)
        actions = ["a", "b", "c"]
        self.assertEqual([first.select_action("s", actions) for _ in range(5)],
                         [second.select_action("s", actions) for _ in range(5)])

    def test_q_learning_update(self):
        learner = QLearningAgent(learning_rate=0.5, discount_factor=0)
        value = learner.update("s", "a", 4, None, done=True)
        self.assertEqual(2, value)
        self.assertEqual(1, learner.training_steps)

    def test_non_terminal_update_bootstraps_once_from_legal_next_actions(self):
        learner = QLearningAgent(learning_rate=1, discount_factor=0.5)
        learner.update("next", "best", 8, None, done=True)
        value = learner.update("current", "move", 2, "next", ["best"])
        self.assertEqual(6, value)

    def test_terminal_update_never_bootstraps_from_next_state(self):
        learner = QLearningAgent(learning_rate=1, discount_factor=0.5)
        learner.update("next", "best", 100, None, done=True)
        value = learner.update("terminal", "move", 3, "next", ["best"], done=True)
        self.assertEqual(3, value)

    def test_delayed_reward_handles_empty_and_single_transition(self):
        learner = QLearningAgent(learning_rate=1, discount_factor=0.5)
        apply_delayed_terminal_reward(learner, [], FRAUDSTER_OBJECTIVE_REWARD)
        self.assertEqual({}, learner.q_values)
        apply_delayed_terminal_reward(
            learner,
            [Transition("only", "action", None, ())],
            FRAUDSTER_OBJECTIVE_REWARD,
        )
        self.assertEqual(
            FRAUDSTER_OBJECTIVE_REWARD,
            learner.q_values['"only"']['"action"'],
        )

    def test_delayed_terminal_reward_propagates_discounted_credit_once(self):
        learner = QLearningAgent(learning_rate=1, discount_factor=0.5)
        transitions = [Transition("s0", "a0", "s1", ()), Transition("s1", "a1", "terminal", ())]
        apply_delayed_terminal_reward(learner, transitions, FRAUDSTER_OBJECTIVE_REWARD)
        self.assertEqual(FRAUDSTER_OBJECTIVE_REWARD, learner.q_values['"s1"']['"a1"'])
        self.assertEqual(FRAUDSTER_OBJECTIVE_REWARD * 0.5, learner.q_values['"s0"']['"a0"'])

    def test_investigator_state_separates_observable_evidence(self):
        investigator = state("INVESTIGATOR")
        with_history = json.loads(json.dumps(investigator))
        with_history["transactionHistory"] = [traced_transaction()]
        base_key = investigator_state_key(investigator)
        evidence_key = investigator_state_key(
            with_history,
            investigated_company_ids={10, 11},
            candidate_company_ids={10, 11, 12},
            observed_company_ids={10, 11, 12},
            discovered_director_ids={50},
            director_relationships={(50, 10), (50, 12)},
        )
        self.assertNotEqual(base_key, evidence_key)
        self.assertEqual(evidence_key, investigator_state_key(
            with_history,
            investigated_company_ids={10, 11},
            candidate_company_ids={10, 11, 12},
            observed_company_ids={10, 11, 12},
            discovered_director_ids={50},
            director_relationships={(50, 10), (50, 12)},
        ))

    def test_investigator_state_ignores_hidden_fields_in_history(self):
        original = state("INVESTIGATOR")
        original["transactionHistory"] = [traced_transaction()]
        changed = json.loads(json.dumps(original))
        changed["transactionHistory"][0]["shellCompany"] = True
        changed["transactionHistory"][0]["flagCorrect"] = False
        changed["transactionHistory"][0]["fraudPathInvolved"] = True
        changed["transactionHistory"][0]["pathShellCompany"] = True
        self.assertEqual(investigator_state_key(original), investigator_state_key(changed))

    def test_investigator_state_encodes_public_transaction_routes_and_amounts(self):
        def route(intermediary_id, age, amount):
            observation = state("INVESTIGATOR")
            intermediary = {
                "id": intermediary_id, "ageInYears": age,
                "annualRevenue": 1000, "numberOfEmployees": 1,
            }
            observation["transactionHistory"] = [
                {
                    "id": 701, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                    "sourceCompany": observation["sourceCompany"],
                    "destinationCompany": intermediary, "amount": amount,
                },
                {
                    "id": 702, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                    "sourceCompany": intermediary,
                    "destinationCompany": observation["targetCompany"], "amount": amount,
                },
            ]
            return observation

        pioneer_route = route(12, 1, "50")
        united_route = route(13, 30, "50")
        self.assertNotEqual(
            investigator_state_key(pioneer_route), investigator_state_key(united_route)
        )
        self.assertNotEqual(
            investigator_state_key(pioneer_route),
            investigator_state_key(route(12, 1, "25")),
        )

    def test_investigator_transaction_route_features_are_deterministic_and_public_only(self):
        observation = state("INVESTIGATOR")
        intermediary = {
            "id": 12, "ageInYears": 1, "annualRevenue": 1000,
            "numberOfEmployees": 1,
        }
        observation["transactionHistory"] = [
            {
                "id": 701, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                "sourceCompany": observation["sourceCompany"],
                "destinationCompany": intermediary, "amount": "50",
            },
            {
                "id": 702, "scenarioId": 1, "origin": "FRAUDSTER_ACTION",
                "sourceCompany": intermediary,
                "destinationCompany": observation["targetCompany"], "amount": "50",
            },
        ]
        expected = investigator_state_key(observation)
        self.assertEqual(expected, investigator_state_key(observation))
        observation["transactionHistory"].reverse()
        self.assertEqual(expected, investigator_state_key(observation))

        hidden = json.loads(json.dumps(observation))
        for transaction in hidden["transactionHistory"]:
            transaction["shellCompany"] = True
            transaction["flagCorrect"] = False
            transaction["privateShellCompanyIds"] = [12]
        hidden["privateShellCompanyIds"] = [12]
        self.assertEqual(expected, investigator_state_key(hidden))
        self.assertNotIn("12", repr(investigator_state_key(observation)))

    def test_investigator_state_handles_missing_and_empty_transaction_history(self):
        observation = state("INVESTIGATOR")
        missing = investigator_state_key(observation)
        observation["transactionHistory"] = []
        self.assertEqual(missing, investigator_state_key(observation))
        observation["transactionHistory"] = None
        self.assertEqual(missing, investigator_state_key(observation))

    def test_investigator_state_changes_with_public_company_evidence(self):
        original = state("INVESTIGATOR")
        changed = json.loads(json.dumps(original))
        changed["sourceCompany"].update({
            "ageInYears": 0, "numberOfEmployees": 0,
            "annualRevenue": "2500000", "address": "17 Example Road, Unit 4",
        })
        self.assertNotEqual(
            investigator_state_key(original), investigator_state_key(changed)
        )

    def test_investigator_evidence_profiles_generalize_across_company_ids(self):
        first = state("INVESTIGATOR")
        second = json.loads(json.dumps(first))
        second["id"] = 99
        second["sourceCompany"]["id"] = 910
        second["targetCompany"]["id"] = 911
        second["positions"][0]["company"]["id"] = 910
        self.assertEqual(investigator_state_key(first), investigator_state_key(second))

        policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        first_action = {"action_type": "FLAG_COMPANY", "company_id": 10}
        second_action = {"action_type": "FLAG_COMPANY", "company_id": 910}
        self.assertEqual(
            policy.learning_action(first, first_action),
            policy.learning_action(second, second_action),
        )

    def test_investigator_hidden_labels_and_private_ids_cannot_change_state(self):
        original = state("INVESTIGATOR")
        changed = json.loads(json.dumps(original))
        for company in (changed["sourceCompany"], changed["targetCompany"],
                        changed["positions"][0]["company"]):
            company["shellCompany"] = True
            company["flagCorrect"] = True
        changed["privateShellCompanyIds"] = [10, 11, 999]
        changed["shellCompany"] = True
        changed["flagCorrect"] = True
        changed["fraudPathInvolved"] = True
        changed["pathShellCompany"] = True
        self.assertEqual(investigator_state_key(original), investigator_state_key(changed))
        self.assertEqual(
            legal_investigator_actions(original), legal_investigator_actions(changed)
        )
        original_policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0, seed=9))
        changed_policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0, seed=9))
        self.assertEqual(
            original_policy.choose_action(original), changed_policy.choose_action(changed)
        )

    def test_investigator_policy_diagnostics_are_id_free_and_report_tie_break(self):
        policy = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        observation = state("INVESTIGATOR")
        observation["privateShellCompanyIds"] = [10]
        observation["shellCompany"] = True
        observation["flagCorrect"] = True
        observation["fraudPathInvolved"] = True
        observation["pathShellCompany"] = True
        action = policy.choose_action(observation)
        diagnostic = policy.last_decision_diagnostics
        self.assertEqual("OBSERVE_COMPANY", action["action_type"])
        self.assertEqual("greedy", diagnostic["selection_mode"])
        self.assertEqual("first_legal_max_q", diagnostic["tie_breaking"])
        self.assertTrue(diagnostic["legal_alternatives"])
        serialized = json.dumps(diagnostic, sort_keys=True)
        self.assertNotIn("company_id", serialized)
        self.assertNotIn("shellCompany", serialized)
        self.assertNotIn("flagCorrect", serialized)
        self.assertNotIn("privateShellCompanyIds", serialized)
        self.assertNotIn("fraudPathInvolved", serialized)
        self.assertNotIn("pathShellCompany", serialized)

    def test_old_investigator_state_checkpoint_is_rejected(self):
        learner = QLearningAgent.for_role("investigator")
        learner.compatibility["state_abstraction_version"] = "state-abstraction-v2"
        with self.assertRaisesRegex(ValueError, "compatibility metadata"):
            RLInvestigatorPolicy(learner)

    def test_policy_persistence(self):
        learner = QLearningAgent(seed=9, metadata={"agent": "fraudster", "version": 1})
        learner.update("state", "action", 3, None, done=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            learner.save(path)
            loaded = QLearningAgent.load(path)
        self.assertEqual(learner.q_values, loaded.q_values)
        self.assertEqual(learner.training_steps, loaded.training_steps)
        self.assertEqual(9, loaded.seed)
        self.assertEqual(learner.metadata, loaded.metadata)

    def test_save_new_never_overwrites_existing_checkpoint(self):
        learner = QLearningAgent.for_role("fraudster", seed=9)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing-policy.json"
            path.write_text("preserve me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                learner.save_new(path)
            self.assertEqual("preserve me", path.read_text(encoding="utf-8"))

    def test_legacy_three_field_checkpoint_metadata_is_rejected_explicitly(self):
        legacy_metadata = {
            "policy_role": "fraudster",
            "state_abstraction_version": "fraudster-state-abstraction-v2",
            "legal_action_schema_version": "legal-actions-v1",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-three-field.json"
            QLearningAgent.for_role("fraudster").save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["compatibility"] = legacy_metadata
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError,
                    "observation_reward_contract_version, private_shell_knowledge_features"):
                QLearningAgent.load(path)

    def test_current_role_metadata_contains_all_required_compatibility_fields(self):
        required = {
            "policy_role",
            "state_abstraction_version",
            "legal_action_schema_version",
            "observation_reward_contract_version",
            "private_shell_knowledge_features",
        }
        fraudster = QLearningAgent.for_role("fraudster")
        investigator = QLearningAgent.for_role("investigator")
        self.assertEqual(required, set(fraudster.compatibility))
        self.assertEqual(required, set(investigator.compatibility))
        self.assertEqual(
            "run-authorized-shell-intermediary-ids-v1",
            fraudster.compatibility["private_shell_knowledge_features"],
        )
        self.assertEqual(
            "investigator-fraud-path-reward-contract-v1",
            investigator.compatibility["observation_reward_contract_version"],
        )

    def test_malformed_checkpoint_is_rejected_without_partial_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-policy.json"
            path.write_text(json.dumps({
                "format": 1,
                "learning_rate": 0.1,
                "discount_factor": 0.95,
                "epsilon": 0.1,
                "seed": 1,
                "training_steps": 0,
                "metadata": {},
                "q_values": {"state": {"action": "not-a-number"}},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Q-values must be numeric"):
                QLearningAgent.load(path)

    def test_investigator_legal_actions_are_shared_with_policy(self):
        investigator = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        investigator_state = state("INVESTIGATOR")
        self.assertEqual(
            investigator.legal_actions(investigator_state),
            investigator.legal_actions(investigator_state),
        )
        actions = investigator.legal_actions(investigator_state)
        self.assertEqual({10, 11}, {
            action["company_id"] for action in actions
            if action["action_type"] == "FLAG_COMPANY"
        })

    def test_adapters_preserve_turn_and_budget_constraints(self):
        fraud = RLFraudsterPolicy(QLearningAgent(epsilon=0))
        self.assertEqual("DIRECT_TRANSFER", fraud.choose_action(state())["action_type"])
        with self.assertRaises(FraudsterPolicyError):
            fraud.choose_action(state("INVESTIGATOR"))
        investigator = RLInvestigatorPolicy(QLearningAgent(epsilon=0))
        self.assertIn(investigator.choose_action(state("INVESTIGATOR"))["company_id"], {10, 11})
        exhausted = state("INVESTIGATOR")
        exhausted["investigatorActionsRemaining"] = 0
        with self.assertRaises(InvestigatorPolicyError):
            investigator.choose_action(exhausted)

    def test_evaluator_reward_is_separate_and_delayed(self):
        candidates = [
            type("Candidate", (), {
                "shell_company": True, "fraud_path_involved": True, "flagged": True
            })(),
            type("Candidate", (), {
                "shell_company": False, "fraud_path_involved": False, "flagged": False
            })(),
        ]
        self.assertEqual(1.0, investigator_terminal_reward(candidates))
        self.assertFalse("shell_company" in investigator_state_key(state("INVESTIGATOR")))

    def test_hidden_fields_do_not_change_rl_action_selection(self):
        learner = QLearningAgent(epsilon=0)
        policy = RLFraudsterPolicy(learner)
        original = state()
        changed = json.loads(json.dumps(original))
        changed["shellCompany"] = True
        changed["flagCorrect"] = False
        self.assertEqual(policy.choose_action(original), policy.choose_action(changed))


if __name__ == "__main__":
    unittest.main()
