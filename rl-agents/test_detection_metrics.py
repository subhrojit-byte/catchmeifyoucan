import unittest
from unittest.mock import patch

from detection_metrics import calculate_detection_metrics
from ground_truth import (
    EvaluatorConfigurationError,
    EvaluatorDataError,
    PostgresGroundTruthReader,
)
import evaluate


class DetectionMetricsTest(unittest.TestCase):
    def test_flagged_shell_source_or_target_is_a_true_positive(self):
        metrics = calculate_detection_metrics([
            {"scenario_id": 8, "company_id": 1, "shell_company": True, "flagged": True},
            {"scenario_id": 8, "company_id": 2, "shell_company": False, "flagged": False},
        ])
        self.assertEqual((1, 0, 1, 0), tuple(
            metrics[key] for key in ("tp", "fp", "tn", "fn")
        ))

    def test_all_positive_predictions(self):
        metrics = calculate_detection_metrics([
            {"shell_company": True, "flagged": True},
            {"shell_company": True, "flagged": True},
        ])
        self.assertEqual((2, 0, 0, 0), tuple(metrics[key] for key in ("tp", "fp", "tn", "fn")))
        self.assertEqual(1.0, metrics["precision"])
        self.assertEqual(1.0, metrics["recall"])
        self.assertEqual(1.0, metrics["f1"])
        self.assertEqual(1.0, metrics["accuracy"])
        self.assertIsNone(metrics["false_positive_rate"])

    def test_all_negative_predictions(self):
        metrics = calculate_detection_metrics([
            {"shell_company": False, "flagged": False},
            {"shell_company": False, "flagged": False},
        ])
        self.assertEqual((0, 0, 2, 0), tuple(metrics[key] for key in ("tp", "fp", "tn", "fn")))
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])
        self.assertIsNone(metrics["f1"])
        self.assertEqual(1.0, metrics["accuracy"])
        self.assertEqual(0.0, metrics["false_positive_rate"])

    def test_no_predictions_reports_false_negatives_and_true_negatives(self):
        metrics = calculate_detection_metrics([
            {"shell_company": True, "flagged": False},
            {"shell_company": False, "flagged": False},
        ])
        self.assertEqual((0, 0, 1, 1), tuple(metrics[key] for key in ("tp", "fp", "tn", "fn")))
        self.assertIsNone(metrics["precision"])
        self.assertEqual(0.0, metrics["recall"])
        self.assertEqual(0.0, metrics["f1"])

    def test_empty_population_is_explicitly_empty(self):
        metrics = calculate_detection_metrics([])
        self.assertEqual(0, metrics["candidate_count"])
        self.assertEqual(0, metrics["flagged_decision_count"])
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])
        self.assertIsNone(metrics["f1"])

    def test_multiple_records_use_aggregate_confusion_counts(self):
        metrics = calculate_detection_metrics([
            {"shell_company": True, "flagged": True},
            {"shell_company": True, "flagged": False},
            {"shell_company": False, "flagged": True},
            {"shell_company": False, "flagged": False},
        ])
        self.assertEqual((1, 1, 1, 1), tuple(
            metrics[key] for key in ("tp", "fp", "tn", "fn")
        ))
        self.assertEqual(0.5, metrics["precision"])
        self.assertEqual(0.5, metrics["recall"])
        self.assertEqual(0.5, metrics["f1"])
        self.assertEqual(0.5, metrics["accuracy"])
        self.assertEqual(0.5, metrics["false_positive_rate"])

    def test_zero_denominators_are_none_and_missing_ground_truth_is_rejected(self):
        metrics = calculate_detection_metrics([])
        self.assertIsNone(metrics["accuracy"])
        self.assertIsNone(metrics["false_positive_rate"])
        false_positive_only = calculate_detection_metrics([
            {"shell_company": False, "flagged": True},
        ])
        self.assertEqual(0.0, false_positive_only["f1"])
        self.assertEqual(1.0, false_positive_only["false_positive_rate"])
        with self.assertRaisesRegex(ValueError, "boolean labels and decisions"):
            calculate_detection_metrics([{"flagged": False}])

    def test_non_boolean_evaluator_data_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_detection_metrics([{"shell_company": None, "flagged": False}])

    def test_missing_label_is_evaluator_data_error(self):
        with self.assertRaises(EvaluatorDataError):
            PostgresGroundTruthReader._require_label(None)

    def test_missing_evaluator_configuration_is_explicit(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(EvaluatorConfigurationError):
                PostgresGroundTruthReader.from_environment()

    def test_source_target_metrics_ignore_out_of_population_flag_decisions(self):
        class Cursor:
            def __init__(self):
                self.fetchall_calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, params=None):
                pass

            def fetchall(self):
                self.fetchall_calls += 1
                if self.fetchall_calls == 1:
                    return [(8, 1, True), (8, 2, False)]
                # Company 3 represents a valid persisted investigator target
                # outside the source/target baseline population. The duplicate
                # source flag models duplicate historical rows before DISTINCT.
                return [(8, 1), (8, 1), (8, 3)]

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def close(self):
                pass

        connection = Connection()
        with patch.object(
                PostgresGroundTruthReader,
                "_load_connect",
                return_value=lambda database_url: connection,
        ):
            candidates = PostgresGroundTruthReader("test").read_candidates([8])

        self.assertEqual([(1, True), (2, False)], [
            (candidate.company_id, candidate.flagged)
            for candidate in candidates
        ])
        metrics = calculate_detection_metrics([
            {"shell_company": candidate.shell_company, "flagged": candidate.flagged}
            for candidate in candidates
        ])
        self.assertEqual(1.0, metrics["precision"])
        # Company 3's persisted flag is outside the source/target baseline;
        # it is not smuggled into that population by the flags query.
        self.assertEqual(2, metrics["candidate_count"])
        self.assertEqual(1, metrics["flagged_decision_count"])

    def test_detection_mode_rejects_incomplete_episode_data(self):
        class Reader:
            def read_candidates(self, scenario_ids):
                return []

        class Client:
            def create_scenario(self, **kwargs):
                return {"id": 10}

        def fake_run_episode(client, *, scenario_id, max_actions, result_collector):
            result_collector.update({
                "scenario_id": scenario_id,
                "episode_class": "action_limit",
                "creation_succeeded": True,
            })

        with patch.object(evaluate, "run_episode", side_effect=fake_run_episode):
            with self.assertRaises(EvaluatorDataError):
                evaluate.run_evaluation(
                    Client(),
                    scenario_count=1,
                    source_company_id=1,
                    target_company_id=2,
                    amount="10",
                    detection_metrics=True,
                    ground_truth_reader=Reader(),
                )


if __name__ == "__main__":
    unittest.main()
