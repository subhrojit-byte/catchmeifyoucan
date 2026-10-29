import unittest
from unittest.mock import patch

import run_episode as runner
from client import CatchMeIfYouCanApiError
from fraudster_bot import FraudsterBot
from investigator_bot import (
    HIGH_REVENUE_PER_EMPLOYEE,
    SUSPICION_THRESHOLD,
    InvestigatorBot,
    InvestigatorPolicyError,
    extract_risk_features,
    score_risk_features,
)


def scenario_state(turn="INVESTIGATOR", scenario_id=1):
    company = lambda company_id: {
        "id": company_id,
        "companyName": f"Company {company_id}",
        "industry": "Industry",
        "address": "Address",
        "ageInYears": 10,
        "registrationDate": "2020-01-01",
        "annualRevenue": 100,
        "numberOfEmployees": 10,
    }
    return {
        "id": scenario_id,
        "status": "ACTIVE",
        "turn": turn,
        "investigatorActionsRemaining": 3,
        "sourceCompany": company(303),
        "targetCompany": company(304),
        "positions": [{"id": 1, "company": company(303), "amount": 100}],
    }


def director_response(company_id, connected_ids=()):
    return {
        "directorInvestigation": {
            "company": {"id": company_id, "companyName": f"Company {company_id}"},
            "directors": [
                {
                    "directorId": 7,
                    "directorName": "Director",
                    "shellCompany": True,
                    "associatedCompanies": [
                        {
                            "id": connected_id,
                            "companyName": f"Company {connected_id}",
                            "industry": "Industry",
                        }
                        for connected_id in connected_ids
                    ],
                }
            ],
        },
        "flagCorrect": True,
    }


def director_response_with_relationships(company_id, directors):
    return {
        "directorInvestigation": {
            "company": {"id": company_id, "companyName": f"Company {company_id}"},
            "directors": directors,
        },
        "shellCompany": True,
        "flagCorrect": True,
        "unexpectedGroundTruth": "hidden",
    }


def scored_company(company_id, *, address="Shared Address"):
    return {
        "id": company_id,
        "companyName": f"Company {company_id}",
        "address": address,
        "ageInYears": 3,
        "annualRevenue": 3000000,
        "numberOfEmployees": 1,
    }


def scored_director_response(company_id=303, connected_id=305, *, address="Shared Address"):
    return {
        "directorInvestigation": {
            "company": scored_company(company_id, address=address),
            "directors": [
                {
                    "directorId": 7,
                    "directorName": "Director 7",
                    "associatedCompanies": [
                        scored_company(company_id, address=address),
                        scored_company(connected_id, address=address),
                    ],
                }
            ],
        }
    }


def transaction_trace_response(transaction_id=700, scenario_id=1):
    return {
        "actionType": "TRACE_TRANSACTION",
        "scenarioId": scenario_id,
        "transactionTrace": {
            "id": transaction_id,
            "sourceCompany": scored_company(303),
            "destinationCompany": scored_company(304),
            "amount": "25.00",
            "timestamp": "2025-01-01T00:00:00",
            "description": "background",
            "channel": "BANK_TRANSFER",
            "origin": "BACKGROUND",
            "scenarioId": scenario_id,
            "fraudActionId": None,
            "shellCompany": True,
            "flagCorrect": False,
        },
        "shellCompany": True,
        "flagCorrect": False,
    }


def transaction_history(scenario_id=1):
    return [
        {
            "id": 700,
            "sourceCompany": scored_company(303),
            "destinationCompany": scored_company(304),
            "amount": "25.00",
            "timestamp": "2025-01-01T00:00:00",
            "channel": "BANK_TRANSFER",
            "origin": "BACKGROUND",
            "scenarioId": scenario_id,
            "fraudActionId": None,
            "shellCompany": True,
            "flagCorrect": False,
        }
    ]


class InvestigatorBotTest(unittest.TestCase):
    def test_each_risk_feature_has_a_named_deterministic_contribution(self):
        features = extract_risk_features(
            {
                "ageInYears": 3,
                "annualRevenue": 3000000,
                "numberOfEmployees": 1,
            },
            shared_address=True,
            reused_director=True,
        )

        self.assertTrue(features.young_company)
        self.assertTrue(features.high_revenue_per_employee)
        self.assertTrue(features.shared_address)
        self.assertTrue(features.reused_director)
        self.assertEqual(SUSPICION_THRESHOLD + 1, score_risk_features(features))
        self.assertEqual(HIGH_REVENUE_PER_EMPLOYEE, 2000000)

    def test_missing_malformed_zero_and_negative_values_are_safe(self):
        features = extract_risk_features(
            {
                "ageInYears": -1,
                "annualRevenue": "not-a-number",
                "numberOfEmployees": 0,
            },
            shared_address=False,
            reused_director=False,
        )

        self.assertFalse(features.young_company)
        self.assertFalse(features.high_revenue_per_employee)
        self.assertEqual(0, score_risk_features(features))

    def test_source_or_target_role_alone_never_causes_a_flag(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response({
                "directorInvestigation": {
                    "company": scored_company(303, address="Unique Address"),
                    "directors": [],
                }
            }),
        )

        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            bot.choose_action(scenario_state()),
        )

    def test_shared_director_or_address_alone_does_not_cause_a_flag(self):
        bot = InvestigatorBot()
        response = {
            "directorInvestigation": {
                "company": {
                    "id": 303,
                    "address": "Shared Address",
                    "ageInYears": 20,
                    "annualRevenue": 100000,
                    "numberOfEmployees": 20,
                },
                "directors": [
                    {
                        "directorId": 7,
                        "directorName": "Director 7",
                        "associatedCompanies": [
                            {"id": 303, "address": "Shared Address"},
                            {"id": 305, "address": "Shared Address"},
                        ],
                    }
                ],
            }
        }
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response(response),
        )

        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            bot.choose_action(scenario_state()),
        )

    def test_sufficient_combined_evidence_triggers_flag(self):
        bot = InvestigatorBot()
        decision = {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303}
        bot.mark_action_completed(decision, bot.sanitize_action_response(scored_director_response()))

        self.assertEqual(
            {"action_type": "FLAG_COMPANY", "company_id": 303},
            bot.choose_action(scenario_state()),
        )

    def test_insufficient_evidence_continues_investigation(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response({
                "directorInvestigation": {
                    "company": {
                        "id": 303,
                        "ageInYears": 3,
                        "annualRevenue": 3000000,
                        "numberOfEmployees": 1,
                        "address": "Unique Address",
                    },
                    "directors": [],
                }
            }),
        )

        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            bot.choose_action(scenario_state()),
        )

    def test_flagged_company_is_not_selected_again(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response(scored_director_response()),
        )
        flag = bot.choose_action(scenario_state())
        bot.mark_action_completed(flag, {})

        self.assertNotIn(303, [company_id for company_id, _ in bot._rank_flag_candidates()])

    def test_equal_scores_use_company_id_tie_breaking(self):
        bot = InvestigatorBot()
        for company_id in (305, 306):
            bot._director_evidence[company_id] = {
                "company": scored_company(company_id, address=f"Unique {company_id}"),
                "directors": [],
            }

        ranked = bot._rank_flag_candidates()
        self.assertEqual([305, 306], [company_id for company_id, _ in ranked])

    def test_hidden_fields_do_not_change_score_or_selected_action(self):
        permitted = scored_company(303)
        hidden = {
            **permitted,
            "shellCompany": True,
            "flagCorrect": True,
            "flagCorrectness": True,
        }
        self.assertEqual(
            extract_risk_features(permitted),
            extract_risk_features(hidden),
        )

        clean_bot = InvestigatorBot()
        hidden_bot = InvestigatorBot()
        clean_response = {
            "directorInvestigation": {
                "company": permitted,
                "directors": [],
            }
        }
        hidden_response = {
            "directorInvestigation": {
                "company": hidden,
                "directors": [],
                "shellCompany": False,
                "flagCorrect": False,
                "flagCorrectness": False,
            },
            "shellCompany": False,
            "flagCorrect": False,
            "flagCorrectness": False,
        }
        decision = {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303}
        clean_bot.mark_action_completed(decision, clean_bot.sanitize_action_response(clean_response))
        hidden_bot.mark_action_completed(decision, hidden_bot.sanitize_action_response(hidden_response))

        self.assertEqual(clean_bot._rank_flag_candidates(), hidden_bot._rank_flag_candidates())
        self.assertEqual(clean_bot.choose_action(scenario_state()), hidden_bot.choose_action(scenario_state()))

    def test_runner_populates_structured_action_limit_result_without_parsing_logs(self):
        class Client:
            def get_scenario(self, scenario_id):
                return scenario_state(scenario_id=scenario_id)

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return director_response(kwargs["company_id"], [305])

        result = {}
        with self.assertRaises(RuntimeError):
            runner.run_episode(
                Client(), scenario_id=41, max_actions=1, result_collector=result
            )

        self.assertEqual(41, result["scenario_id"])
        self.assertEqual(303, result["initial_source_company_id"])
        self.assertEqual(304, result["initial_target_company_id"])
        self.assertEqual(1, result["actions_attempted"])
        self.assertEqual("action limit reached", result["stop_reason"])
        self.assertEqual("action_limit", result["episode_class"])
        self.assertEqual(1, result["investigator_evidence"]["successful_director_investigations"])

    def test_runner_returns_when_scenario_completes_on_last_allowed_action(self):
        class Client:
            def __init__(self):
                self.get_calls = 0

            def get_scenario(self, scenario_id):
                self.get_calls += 1
                state = scenario_state(scenario_id=scenario_id)
                if self.get_calls == 2:
                    state["status"] = "COMPLETED"
                    state["investigatorActionsRemaining"] = 0
                return state

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return director_response(kwargs["company_id"], [305])

        result = {}
        returned_state = runner.run_episode(
            Client(), scenario_id=41, max_actions=1, result_collector=result
        )

        self.assertEqual("COMPLETED", returned_state["status"])
        self.assertEqual(1, result["actions_attempted"])
        self.assertEqual("scenario terminated", result["stop_reason"])
        self.assertEqual("completed", result["episode_class"])
        self.assertEqual(returned_state, result["final_state"])

    def test_runner_structured_result_has_no_new_evidence_after_refresh_failure(self):
        class Client:
            def __init__(self):
                self.get_calls = 0

            def get_scenario(self, scenario_id):
                self.get_calls += 1
                if self.get_calls == 2:
                    raise CatchMeIfYouCanApiError("refresh failed")
                return scenario_state(scenario_id=scenario_id)

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return director_response(kwargs["company_id"], [305])

        result = {}
        returned_state = runner.run_episode(
            Client(), scenario_id=41, max_actions=1, result_collector=result
        )

        self.assertEqual("ACTIVE", returned_state["status"])
        self.assertIsNone(result["final_state"])
        self.assertEqual("authoritative_refresh_failed", result["stop_reason"])
        self.assertIsNone(result["investigator_evidence"])

    def test_connected_candidate_ranking_prefers_distinct_directors(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(
                303,
                [
                    {"directorId": 7, "associatedCompanies": [{"id": 305}, {"id": 306}]},
                    {"directorId": 8, "associatedCompanies": [{"id": 305}]},
                ],
            ),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response_with_relationships(304, []),
        )

        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 305},
            bot.choose_action({**scenario_state(), "sourceCompany": {"id": 303}, "targetCompany": {"id": 304}}),
        )

    def test_connected_candidate_ranking_deduplicates_directors_and_excludes_investigated(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(
                303,
                [
                    {"directorId": 7, "associatedCompanies": [{"id": 304}, {"id": 305}]},
                    {"directorId": 7, "associatedCompanies": [{"id": 304}, {"id": 305}]},
                    {"directorId": 8, "associatedCompanies": [{"id": 304}]},
                ],
            ),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response_with_relationships(304, []),
        )

        self.assertEqual([305], bot._rank_connected_company_candidates())

    def test_connected_candidate_ranking_breaks_ties_by_company_id(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(
                303,
                [
                    {"directorId": 7, "associatedCompanies": [{"id": 306}, {"id": 305}]},
                ],
            ),
        )

        self.assertEqual([305, 306], bot._rank_connected_company_candidates())

    def test_source_and_target_investigations_keep_priority_over_connected_candidates(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response(303, [305, 306]),
        )

        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            bot.choose_action(scenario_state()),
        )

    def test_empty_and_invalid_director_evidence_produces_no_candidates(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(
                303,
                [
                    {"directorId": None, "associatedCompanies": [{"id": 305}]},
                    {"directorId": 7, "associatedCompanies": [{"id": None}, {}]},
                ],
            ),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response_with_relationships(304, []),
        )

        self.assertEqual([], bot._rank_connected_company_candidates())

    def test_hidden_and_arbitrary_fields_do_not_affect_candidate_ranking(self):
        bot = InvestigatorBot()
        response = director_response_with_relationships(
            303,
            [
                {
                    "directorId": 7,
                    "shellCompany": True,
                    "arbitraryRisk": 999,
                    "associatedCompanies": [
                        {"id": 305, "shellCompany": True, "flagCorrect": True}
                    ],
                }
            ],
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response(response),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response(304, []),
        )

        self.assertEqual([305], bot._rank_connected_company_candidates())

    def test_evidence_summary_deduplicates_ids_and_relationships(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(
                303,
                [
                    {
                        "directorId": 7,
                        "directorName": "Director 7",
                        "associatedCompanies": [{"id": 304}, {"id": 305}],
                    },
                    {
                        "directorId": 7,
                        "directorName": "Director 7",
                        "associatedCompanies": [{"id": 304}],
                    },
                ],
            ),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response_with_relationships(
                304,
                [
                    {
                        "directorId": 7,
                        "directorName": "Director 7",
                        "associatedCompanies": [{"id": 303}, {"id": 305}],
                    },
                    {
                        "directorId": 8,
                        "directorName": "Director 8",
                        "associatedCompanies": [{"id": 305}],
                    },
                ],
            ),
        )

        self.assertEqual(
            {
                "successful_director_investigations": 2,
                "investigated_company_ids": [303, 304],
                "unique_director_ids_discovered": 2,
                "unique_connected_company_ids_discovered": 3,
                "unique_company_director_relationships": 3,
                "unique_director_company_connections": 4,
            },
            bot.evidence_summary(),
        )

    def test_evidence_summary_ignores_empty_and_missing_ids(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            director_response_with_relationships(303, []),
        )
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            director_response_with_relationships(
                304,
                [
                    {
                        "directorId": None,
                        "directorName": "Unknown",
                        "associatedCompanies": [{"id": None}, {}],
                    },
                    {
                        "directorId": 9,
                        "directorName": "Director 9",
                        "associatedCompanies": [{"id": 306}, {"name": "No ID"}],
                    },
                ],
            ),
        )

        summary = bot.evidence_summary()
        self.assertEqual([303, 304], summary["investigated_company_ids"])
        self.assertEqual(1, summary["unique_director_ids_discovered"])
        self.assertEqual(1, summary["unique_connected_company_ids_discovered"])
        self.assertEqual(1, summary["unique_company_director_relationships"])
        self.assertEqual(1, summary["unique_director_company_connections"])

    def test_evidence_summary_and_sanitized_memory_exclude_hidden_fields(self):
        bot = InvestigatorBot()
        response = director_response_with_relationships(
            303,
            [
                {
                    "directorId": 7,
                    "directorName": "Director 7",
                    "shellCompany": True,
                    "associatedCompanies": [
                        {"id": 304, "shellCompany": True, "flagCorrect": False}
                    ],
                }
            ],
        )
        sanitized = bot.sanitize_action_response(response)
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            sanitized,
        )

        self.assertNotIn("shellCompany", sanitized)
        self.assertNotIn("flagCorrect", sanitized)
        self.assertNotIn("unexpectedGroundTruth", sanitized)
        self.assertNotIn("shellCompany", bot._director_evidence[303]["directors"][0])
        self.assertNotIn("flagCorrect", bot._director_evidence[303])
        self.assertNotIn("unexpectedGroundTruth", bot.evidence_summary())

    def test_flag_correct_response_is_not_retained_in_policy_memory(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "FLAG_COMPANY", "company_id": 303},
            {"actionType": "FLAG_COMPANY", "flagCorrect": True},
        )

        self.assertEqual(set(), bot._completed_actions)
        self.assertEqual({303}, bot._flagged_company_ids)
        self.assertEqual({}, bot._director_evidence)
        self.assertNotIn("flagCorrect", bot.evidence_summary())

    def test_observation_evidence_is_retained_only_as_whitelisted_company_data(self):
        bot = InvestigatorBot()
        response = {
            "observation": {
                **scored_company(303),
                "shellCompany": True,
                "flagCorrect": False,
                "unexpected": "hidden",
            },
            "shellCompany": True,
        }

        bot.mark_action_completed(
            {"action_type": "OBSERVE_COMPANY", "company_id": 303},
            bot.sanitize_action_response(response),
        )

        self.assertEqual(303, bot.observation_evidence[303]["company"]["id"])
        self.assertNotIn("shellCompany", bot.observation_evidence[303]["company"])
        self.assertNotIn("flagCorrect", bot.observation_evidence[303]["company"])
        self.assertNotIn("unexpected", bot.observation_evidence[303]["company"])

    def test_trace_evidence_requires_matching_transaction_and_scenario(self):
        bot = InvestigatorBot()
        sanitized = bot.sanitize_action_response(
            transaction_trace_response(),
            scenario_id=1,
            expected_transaction_id=700,
        )
        bot.mark_action_completed(
            {"action_type": "TRACE_TRANSACTION", "transaction_id": 700},
            sanitized,
        )

        self.assertEqual("BACKGROUND", bot.trace_evidence[700]["origin"])
        self.assertEqual(303, bot.trace_evidence[700]["sourceCompany"]["id"])
        self.assertNotIn("shellCompany", bot.trace_evidence[700])
        self.assertNotIn("flagCorrect", bot.trace_evidence[700])

        mismatched = bot.sanitize_action_response(
            transaction_trace_response(transaction_id=701, scenario_id=2),
            scenario_id=1,
            expected_transaction_id=701,
        )
        self.assertNotIn("transactionTrace", mismatched)

    def test_malformed_or_other_scenario_history_is_rejected(self):
        self.assertIsNone(
            InvestigatorBot.sanitize_transaction_history(
                [{"id": 700, "scenarioId": 2}], 1
            )
        )
        self.assertIsNone(
            InvestigatorBot.sanitize_transaction_history(
                [transaction_history(1)[0], "malformed"], 1
            )
        )
        accepted = InvestigatorBot.sanitize_transaction_history(
            transaction_history(1), 1
        )
        self.assertEqual([700], [item["id"] for item in accepted])
        self.assertNotIn("shellCompany", accepted[0])
        self.assertNotIn("shellCompany", accepted[0]["sourceCompany"])

    def test_history_fetch_failure_preserves_confirmed_bot_evidence(self):
        bot = InvestigatorBot()
        bot.mark_action_completed(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            bot.sanitize_action_response(scored_director_response()),
        )
        before = bot.evidence_summary()

        class HistoryFailureClient:
            def get_scenario_transactions(self, scenario_id):
                raise CatchMeIfYouCanApiError("history unavailable")

        state = scenario_state()
        with self.assertRaisesRegex(RuntimeError, "Unable to fetch validated"):
            runner._with_scenario_transaction_history(HistoryFailureClient(), 1, state)
        self.assertEqual(before, bot.evidence_summary())

    def test_runner_retains_observation_only_after_authoritative_refresh(self):
        bot = InvestigatorBot()
        bot.choose_action = lambda state: {
            "action_type": "OBSERVE_COMPANY",
            "company_id": 303,
        }

        class Client:
            def get_scenario(self, scenario_id):
                return scenario_state()

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                return {"observation": scored_company(kwargs["company_id"])}

        with patch.object(runner, "InvestigatorBot", return_value=bot):
            with self.assertRaises(RuntimeError):
                runner.run_episode(Client(), scenario_id=1, max_actions=1)

        self.assertIn(303, bot.observation_evidence)

    def test_runner_attaches_only_valid_scenario_history_to_policy_state(self):
        captured = {}
        bot = InvestigatorBot()

        def choose_action(state):
            captured.update(state)
            return {"action_type": "OBSERVE_COMPANY", "company_id": 303}

        bot.choose_action = choose_action

        class Client:
            def __init__(self, history):
                self.history = history

            def get_scenario(self, scenario_id):
                return scenario_state()

            def get_scenario_transactions(self, scenario_id):
                return self.history

            def submit_investigator_action(self, **kwargs):
                return {"observation": scored_company(kwargs["company_id"])}

        with patch.object(runner, "InvestigatorBot", return_value=bot):
            with self.assertRaises(RuntimeError):
                runner.run_episode(
                    Client(transaction_history(1)), scenario_id=1, max_actions=1
                )

        self.assertEqual([700], [item["id"] for item in captured["transactionHistory"]])
        self.assertNotIn("shellCompany", captured["transactionHistory"][0])

        invalid_captured = {}
        invalid_bot = InvestigatorBot()
        invalid_bot.choose_action = lambda state: (
            invalid_captured.update(state)
            or {"action_type": "OBSERVE_COMPANY", "company_id": 303}
        )
        with patch.object(runner, "InvestigatorBot", return_value=invalid_bot):
            with self.assertRaises(RuntimeError):
                runner.run_episode(
                    Client(transaction_history(2)), scenario_id=1, max_actions=1
                )
        self.assertNotIn("transactionHistory", invalid_captured)

    def test_successful_director_evidence_drives_new_investigation(self):
        bot = InvestigatorBot()
        state = scenario_state()

        source_decision = bot.choose_action(state)
        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 303},
            source_decision,
        )
        bot.mark_action_completed(source_decision, director_response(303, [304, 305]))
        self.assertEqual(7, bot._director_evidence[303]["directors"][0]["directorId"])
        self.assertEqual({304, 305}, bot._director_evidence[303]["connectedCompanyIds"])
        self.assertNotIn("shellCompany", bot._director_evidence[303]["directors"][0])
        self.assertNotIn("flagCorrect", bot._director_evidence[303])

        target_decision = bot.choose_action(state)
        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 304},
            target_decision,
        )
        bot.mark_action_completed(target_decision, director_response(304, [303]))

        next_decision = bot.choose_action(state)
        self.assertEqual(
            {"action_type": "INVESTIGATE_DIRECTORS", "company_id": 305},
            next_decision,
        )

    def test_unconfirmed_action_is_not_recorded(self):
        bot = InvestigatorBot()
        state = scenario_state()
        decision = bot.choose_action(state)

        # A failed submission or state refresh does not call mark_action_completed.
        self.assertEqual(decision, bot.choose_action(state))

    def test_redundant_observation_is_not_selected_when_no_new_evidence_exists(self):
        bot = InvestigatorBot()
        state = scenario_state()
        source = bot.choose_action(state)
        bot.mark_action_completed(source, director_response(303, [304]))
        target = bot.choose_action(state)
        bot.mark_action_completed(target, director_response(304, [303]))

        with self.assertRaises(InvestigatorPolicyError):
            bot.choose_action(state)

    def test_runner_records_only_after_authoritative_refresh(self):
        bot = InvestigatorBot()

        class Client:
            def __init__(self, refresh_fails=False, submit_fails=False):
                self.refresh_fails = refresh_fails
                self.submit_fails = submit_fails
                self.get_calls = 0
                self.submit_calls = 0

            def get_scenario(self, scenario_id):
                self.get_calls += 1
                if self.refresh_fails and self.get_calls == 2:
                    raise CatchMeIfYouCanApiError("refresh failed")
                return scenario_state()

            def get_scenario_transactions(self, scenario_id):
                return []

            def submit_investigator_action(self, **kwargs):
                self.submit_calls += 1
                if self.submit_fails:
                    raise CatchMeIfYouCanApiError("submission failed")
                return director_response(kwargs["company_id"], [304])

        client = Client()
        with patch.object(runner, "InvestigatorBot", return_value=bot):
            with self.assertRaises(RuntimeError):
                runner.run_episode(client, scenario_id=1, max_actions=1)
        self.assertIn(("INVESTIGATE_DIRECTORS", 303), bot._completed_actions)
        self.assertIn(304, bot._director_evidence[303]["connectedCompanyIds"])

        failed_bot = InvestigatorBot()
        failed_client = Client(refresh_fails=True)
        with patch.object(runner, "InvestigatorBot", return_value=failed_bot):
            runner.run_episode(failed_client, scenario_id=1, max_actions=1)
        self.assertNotIn(("INVESTIGATE_DIRECTORS", 303), failed_bot._completed_actions)
        self.assertEqual({}, failed_bot._director_evidence)
        self.assertEqual({}, failed_bot.observation_evidence)
        self.assertEqual({}, failed_bot.trace_evidence)
        self.assertEqual([], failed_bot._rank_connected_company_candidates())

        rejected_bot = InvestigatorBot()
        rejected_client = Client(submit_fails=True)
        with patch.object(runner, "InvestigatorBot", return_value=rejected_bot):
            rejected_state = runner.run_episode(rejected_client, scenario_id=1, max_actions=1)
        self.assertEqual("ACTIVE", rejected_state["status"])
        self.assertEqual(1, rejected_client.submit_calls)
        self.assertNotIn(("INVESTIGATE_DIRECTORS", 303), rejected_bot._completed_actions)
        self.assertEqual([], rejected_bot._rank_connected_company_candidates())
        self.assertEqual({}, rejected_bot.observation_evidence)
        self.assertEqual({}, rejected_bot.trace_evidence)

    def test_fraudster_policy_contract_is_unchanged(self):
        decision = FraudsterBot().choose_action(scenario_state(turn="FRAUDSTER"))
        self.assertEqual("DIRECT_TRANSFER", decision["action_type"])
        self.assertEqual(1, decision["source_position_id"])


if __name__ == "__main__":
    unittest.main()
