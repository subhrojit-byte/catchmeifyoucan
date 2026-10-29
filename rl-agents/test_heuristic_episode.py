from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from fraudster_bot import FraudsterBot
from investigator_bot import InvestigatorBot
from run_heuristic_episode import main, run_heuristic_search


class HeuristicEpisodeRunnerTest(unittest.TestCase):
    def test_uses_existing_bots_and_shared_episode_runner_without_private_provider(self):
        captured = {}

        def fake_run_episode(client, **kwargs):
            captured["client"] = client
            captured.update(kwargs)
            kwargs["event_callback"]({
                "event_type": "action",
                "agent": "FRAUDSTER",
                "state": {
                    "status": "ACTIVE",
                    "privateShellCompanyIds": [999],
                    "authorizationToken": "sensitive",
                },
            })
            kwargs["result_collector"].update({
                "scenario_id": kwargs["scenario_id"],
                "episode_class": "completed",
                "actions_attempted": 1,
                "stop_reason": "scenario terminated",
            })
            return {"id": kwargs["scenario_id"], "status": "COMPLETED"}

        output = StringIO()
        client = object()
        with patch("run_heuristic_episode.run_episode", side_effect=fake_run_episode) as runner:
            with redirect_stdout(output):
                result = run_heuristic_search(77, client=client, max_actions=35)

        runner.assert_called_once()
        self.assertIs(captured["client"], client)
        self.assertEqual(77, captured["scenario_id"])
        self.assertEqual(35, captured["max_actions"])
        self.assertIsInstance(captured["fraudster_policy"], FraudsterBot)
        self.assertIsInstance(captured["investigator_policy"], InvestigatorBot)
        self.assertNotIn("private_shell_knowledge_provider", captured)
        self.assertEqual(77, result["scenario_id"])
        metadata_event = next(
            json.loads(line.removeprefix("CATCHME_AGENT_EVENT "))
            for line in output.getvalue().splitlines()
            if line.startswith("CATCHME_AGENT_EVENT ")
            and '"heuristic_policy_metadata"' in line
        )
        policies = {item["policy"]: item["configuration"]
                    for item in metadata_event["policies"]}
        self.assertEqual("code rules in rl-agents/fraudster_bot.py",
                         policies["FraudsterBot"]["source"])
        self.assertEqual([], policies["FraudsterBot"]["parameters"])
        self.assertIn("DIRECT_TRANSFER", " ".join(policies["FraudsterBot"]["selection_rules"]))
        self.assertEqual("code defaults in rl-agents/investigator_bot.py",
                         policies["InvestigatorBot"]["source"])
        reported = {item["name"]: item["value"]
                    for item in policies["InvestigatorBot"]["parameters"]}
        self.assertEqual(5, reported["YOUNG_COMPANY_MAX_AGE_YEARS"])
        self.assertEqual("2000000", reported["HIGH_REVENUE_PER_EMPLOYEE"])
        self.assertEqual(4, reported["SUSPICION_THRESHOLD"])
        self.assertTrue(policies["InvestigatorBot"]["selection_rules"])
        self.assertNotIn("privateShellCompanyIds", output.getvalue())
        self.assertNotIn("sensitive", output.getvalue())

    def test_cli_does_not_accept_rl_checkpoint_arguments(self):
        with patch("run_heuristic_episode.run_heuristic_search") as run:
            with self.assertRaises(SystemExit):
                main(["--scenario-id", "77", "--fraudster-checkpoint", "unused.json"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
