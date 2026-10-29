import unittest
from unittest.mock import patch

from ground_truth import EvaluatorConfigurationError, EvaluatorDataError, PostgresGroundTruthReader


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.fake_cursor = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


class SequencedConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.cursors = []
        self.closed = False

    def cursor(self):
        cursor = FakeCursor(self.responses.pop(0))
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


class DiagnosticFailure(Exception):
    sqlstate = "42501"


class FailureWithoutSqlstate(Exception):
    pass


class FailingCursor(FakeCursor):
    def __init__(self, *, execute_failure=None, fetch_failure=False):
        super().__init__([])
        self.execute_failure = execute_failure
        self.fetch_failure = fetch_failure

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        if self.execute_failure is not None and self.execute_failure(statement):
            raise DiagnosticFailure("sensitive database detail must not escape")

    def fetchall(self):
        if self.fetch_failure:
            raise DiagnosticFailure("sensitive fetch detail must not escape")
        return [(190,)]


class FailingConnection:
    def __init__(self, cursor_factory):
        self.cursor_factory = cursor_factory
        self.closed = False

    def cursor(self):
        return self.cursor_factory()

    def close(self):
        self.closed = True


class GroundTruthReaderTest(unittest.TestCase):
    def test_discovered_candidate_reader_is_read_only_terminal_and_deduplicates_pairs(self):
        connection = SequencedConnection([
            [(190,)],
            [(190, 1, True, True, True), (190, 3, False, False, False)],
        ])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ) as load_connect:
            rows = reader.read_discovered_candidates(
                [190], {190: [1, 3, 1, 3]}
            )

        self.assertEqual([(1, True, True, True), (3, False, False, False)], [
            (row.company_id, row.shell_company, row.flagged, row.fraud_path_involved)
            for row in rows
        ])
        load_connect.assert_called_once_with()
        self.assertEqual("SET TRANSACTION READ ONLY", connection.cursors[0].statements[0][0])
        terminal_sql, terminal_params = connection.cursors[0].statements[1]
        self.assertIn("status IN ('COMPLETED', 'MAX_TURNS_REACHED')", terminal_sql)
        self.assertEqual([190], terminal_params)
        label_sql, label_params = connection.cursors[1].statements[0]
        self.assertIn("WITH candidates(scenario_id, company_id) AS (VALUES", label_sql)
        self.assertIn("companies.shell_company", label_sql)
        self.assertIn("actions.action_type = 'FLAG_COMPANY'", label_sql)
        self.assertIn("transfers.origin = 'FRAUDSTER_ACTION'", label_sql)
        self.assertIn("transfers.source_company_id = candidates.company_id", label_sql)
        self.assertIn("transfers.destination_company_id = candidates.company_id", label_sql)
        self.assertEqual([190, 1, 190, 3], label_params)
        self.assertTrue(connection.closed)

    def test_path_membership_covers_direct_multihop_and_split_legs_not_unrelated_shells(self):
        # Rows model candidates encountered on a direct leg (1 -> 2), a
        # multi-hop route (1 -> 3 -> 2), split legs (1 -> 4 and 1 -> 5),
        # and unrelated company 6. The SQL membership is company-endpoint
        # based, so each participating company is included once.
        connection = SequencedConnection([
            [(190,)],
            [
                (190, 1, True, True, True),
                (190, 2, False, False, True),
                (190, 3, True, False, True),
                (190, 4, True, False, True),
                (190, 5, False, False, True),
                (190, 6, True, True, False),
            ],
        ])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            rows = reader.read_discovered_candidates([190], {190: [1, 2, 3, 4, 5, 6]})

        self.assertEqual(
            {1: (True, True), 2: (False, True), 3: (True, True),
             4: (True, True), 5: (False, True), 6: (True, False)},
            {row.company_id: (row.shell_company, row.fraud_path_involved) for row in rows},
        )

    def test_discovered_candidates_reject_nonterminal_before_label_query(self):
        connection = SequencedConnection([[]])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            with self.assertRaises(EvaluatorDataError) as raised:
                reader.read_discovered_candidates([190], {190: [1]})
        self.assertEqual(
            "Every discovered-candidate scenario must have a valid terminal status.",
            str(raised.exception),
        )
        self.assertEqual(1, len(connection.cursors))
        self.assertTrue(connection.closed)

    def test_discovered_candidate_database_failures_have_safe_stage_diagnostics(self):
        cases = (
            ("connection_open", None),
            ("read_only_transaction_setup", lambda statement: statement == "SET TRANSACTION READ ONLY"),
            ("terminal_status_query", lambda statement: "FROM fraud_scenarios" in statement),
            ("discovered_candidate_query", lambda statement: statement.lstrip().startswith("WITH candidates")),
            ("fetch", None),
        )
        for expected_stage, execute_failure in cases:
            with self.subTest(stage=expected_stage):
                reader = PostgresGroundTruthReader("postgresql://evaluator")
                if expected_stage == "connection_open":
                    connect = lambda _url: (_ for _ in ()).throw(DiagnosticFailure("private URL/detail"))
                else:
                    cursors = [
                        FailingCursor(
                            execute_failure=execute_failure,
                            fetch_failure=expected_stage == "fetch",
                        ),
                        FailingCursor(execute_failure=execute_failure),
                    ]
                    connection = FailingConnection(lambda: cursors.pop(0))
                    connect = lambda _url: connection
                with patch.object(PostgresGroundTruthReader, "_load_connect", return_value=connect):
                    with self.assertRaises(EvaluatorConfigurationError) as raised:
                        reader.read_discovered_candidates([190], {190: [1]})

                error = raised.exception
                self.assertEqual(
                    "Evaluator discovered-candidate lookup failed; verify the separate read-only PostgreSQL configuration.",
                    str(error),
                )
                self.assertEqual(
                    {"stage": expected_stage, "exception_type": "DiagnosticFailure", "sqlstate": "42501"},
                    error.diagnostic,
                )
                self.assertNotIn("private URL", str(error))
                self.assertNotIn("sensitive", str(error))
                self.assertIsInstance(error.__cause__, DiagnosticFailure)

    def test_database_diagnostic_omits_unavailable_or_untrusted_sqlstate(self):
        diagnostic = PostgresGroundTruthReader._safe_database_diagnostic(
            FailureWithoutSqlstate("private error detail"), "fetch"
        )
        self.assertEqual(
            {"stage": "fetch", "exception_type": "FailureWithoutSqlstate", "sqlstate": "unavailable"},
            diagnostic,
        )

    def test_discovered_candidates_reject_missing_labels_and_invalid_inputs(self):
        connection = SequencedConnection([[(190,)], []])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            with self.assertRaisesRegex(EvaluatorDataError, "missing its scenario or ground-truth"):
                reader.read_discovered_candidates([190], {190: [7]})
        with self.assertRaisesRegex(EvaluatorDataError, "Duplicate scenario"):
            reader.read_discovered_candidates([190, 190], {190: []})
        with self.assertRaisesRegex(EvaluatorDataError, "positive integers"):
            reader.read_discovered_candidates([190], {190: [True]})

    def test_empty_discovered_population_still_validates_terminal_and_skips_label_query(self):
        connection = SequencedConnection([[(190,)]])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            self.assertEqual([], reader.read_discovered_candidates([190], {190: []}))
        self.assertEqual(1, len(connection.cursors))

    def test_nonterminal_database_scenario_is_rejected_before_flag_lookup(self):
        connection = FakeConnection([])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            with self.assertRaisesRegex(EvaluatorDataError, "terminal source/target"):
                reader.read_candidates([190])

        self.assertEqual(2, len(connection.fake_cursor.statements))
        query, parameters = connection.fake_cursor.statements[1]
        self.assertIn("status IN ('COMPLETED', 'MAX_TURNS_REACHED')", query)
        self.assertEqual([190, 190], parameters)
        self.assertTrue(connection.closed)

    def test_correct_flag_outcomes_are_read_only_and_scenario_scoped(self):
        connection = FakeConnection([(190, False), (191, True)])
        reader = PostgresGroundTruthReader("postgresql://evaluator")
        with patch.object(
            PostgresGroundTruthReader,
            "_load_connect",
            return_value=lambda url: connection,
        ):
            outcomes = reader.read_correct_flag_outcomes([190, 191])

        self.assertEqual({190: False, 191: True}, outcomes)
        self.assertEqual(
            "SET TRANSACTION READ ONLY",
            connection.fake_cursor.statements[0][0],
        )
        query, parameters = connection.fake_cursor.statements[1]
        self.assertIn("flag_correct IS TRUE", query)
        self.assertIn("action_type = 'FLAG_COMPANY'", query)
        self.assertEqual([190, 191], parameters)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
