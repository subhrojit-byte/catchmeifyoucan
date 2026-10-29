"""Evaluator-only PostgreSQL ground-truth lookup."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable


DATABASE_URL_ENV = "CATCHMEIFYOUCAN_EVALUATOR_DATABASE_URL"


class EvaluatorConfigurationError(RuntimeError):
    """The evaluator-only database connection is not safely configured."""

    def __init__(self, message: str, *, diagnostic: dict[str, str] | None = None):
        super().__init__(message)
        self.diagnostic = diagnostic


class EvaluatorDataError(RuntimeError):
    """Ground-truth or recorded decision data is incomplete or inconsistent."""


@dataclass(frozen=True)
class CandidateDecision:
    scenario_id: int
    company_id: int
    shell_company: bool
    flagged: bool
    fraud_path_involved: bool = False


class PostgresGroundTruthReader:
    """Read terminal evaluator labels in read-only transactions."""

    def __init__(self, database_url: str):
        if not database_url:
            raise EvaluatorConfigurationError(
                f"Set {DATABASE_URL_ENV} to a separate read-only evaluator database URL."
            )
        self._database_url = database_url

    @classmethod
    def from_environment(cls) -> "PostgresGroundTruthReader":
        return cls(os.getenv(DATABASE_URL_ENV, ""))

    def read_candidates(self, scenario_ids: Iterable[int]) -> list[CandidateDecision]:
        ids = list(dict.fromkeys(scenario_ids))
        if not ids:
            raise EvaluatorDataError("No successfully created scenarios are available for detection evaluation.")

        connect = self._load_connect()
        placeholders = ", ".join(["%s"] * len(ids))
        candidate_sql = f"""
            WITH candidates AS (
                SELECT id AS scenario_id, source_company_id AS company_id
                FROM fraud_scenarios
                WHERE id IN ({placeholders})
                  AND status IN ('COMPLETED', 'MAX_TURNS_REACHED')
                UNION
                SELECT id AS scenario_id, target_company_id AS company_id
                FROM fraud_scenarios
                WHERE id IN ({placeholders})
                  AND status IN ('COMPLETED', 'MAX_TURNS_REACHED')
            )
            SELECT candidates.scenario_id, candidates.company_id, companies.shell_company
            FROM candidates
            JOIN companies ON companies.id = candidates.company_id
            ORDER BY candidates.scenario_id, candidates.company_id
        """
        flags_sql = f"""
            SELECT DISTINCT scenario_id, company_id
            FROM investigator_actions
            WHERE action_type = 'FLAG_COMPANY' AND scenario_id IN ({placeholders})
        """

        connection = None
        try:
            connection = connect(self._database_url)
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(candidate_sql, ids + ids)
                candidate_rows = cursor.fetchall()

            expected = len(ids) * 2
            if len(candidate_rows) != expected:
                raise EvaluatorDataError(
                    "Expected terminal source/target ground-truth rows for every "
                    f"scenario ({expected}), found {len(candidate_rows)}."
                )

            with connection.cursor() as cursor:
                cursor.execute(flags_sql, ids)
                flag_rows = set(cursor.fetchall())

            candidates = [
                CandidateDecision(
                    scenario_id=row[0],
                    company_id=row[1],
                    shell_company=self._require_label(row[2]),
                    flagged=(row[0], row[1]) in flag_rows,
                )
                for row in candidate_rows
            ]
            # The source/target set is the declared baseline metric population,
            # not the complete set of companies that the investigator may have
            # legally discovered and flagged. Out-of-population decisions do
            # not participate in this baseline confusion matrix.
            return candidates
        except EvaluatorDataError:
            raise
        except Exception as error:
            raise EvaluatorConfigurationError(
                "Evaluator database lookup failed; verify the separate read-only PostgreSQL configuration."
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def read_discovered_candidates(
        self,
        scenario_ids: Iterable[int],
        candidate_ids_by_scenario: dict[int, Iterable[int]],
    ) -> list[CandidateDecision]:
        """Label only companies present in a runner-captured legal flag choice.

        The caller supplies decision-time candidate IDs; this reader never
        reconstructs a candidate population from the current company graph.
        Both terminal validation and labels are read in a read-only evaluator
        transaction, after the runner has completed the episode.
        """
        raw_ids = list(scenario_ids)
        if not raw_ids:
            raise EvaluatorDataError("No scenarios are available for discovered-candidate evaluation.")
        ids: list[int] = []
        for scenario_id in raw_ids:
            if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
                raise EvaluatorDataError("Scenario IDs must be positive integers.")
            if scenario_id in ids:
                raise EvaluatorDataError("Duplicate scenario IDs are invalid for discovered-candidate evaluation.")
            ids.append(scenario_id)
        if not isinstance(candidate_ids_by_scenario, dict) or set(candidate_ids_by_scenario) != set(ids):
            raise EvaluatorDataError("Captured candidate scenarios must exactly match evaluated scenarios.")

        pairs: list[tuple[int, int]] = []
        for scenario_id in ids:
            values = candidate_ids_by_scenario[scenario_id]
            if isinstance(values, (str, bytes)):
                raise EvaluatorDataError("Candidate IDs must be an iterable of positive integers.")
            seen: set[int] = set()
            try:
                for company_id in values:
                    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
                        raise EvaluatorDataError("Candidate company IDs must be positive integers.")
                    seen.add(company_id)
            except TypeError as error:
                raise EvaluatorDataError("Candidate IDs must be iterable.") from error
            pairs.extend((scenario_id, company_id) for company_id in sorted(seen))

        connect = self._load_connect()
        placeholders = ", ".join(["%s"] * len(ids))
        terminal_sql = f"""
            SELECT id
            FROM fraud_scenarios
            WHERE id IN ({placeholders})
              AND status IN ('COMPLETED', 'MAX_TURNS_REACHED')
            ORDER BY id
        """
        connection = None
        failure_stage = "connection_open"
        try:
            connection = connect(self._database_url)
            failure_stage = "read_only_transaction_setup"
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                failure_stage = "terminal_status_query"
                cursor.execute(terminal_sql, ids)
                failure_stage = "fetch"
                terminal_rows = cursor.fetchall()
            terminal_ids = [row[0] for row in terminal_rows]
            if terminal_ids != sorted(ids):
                raise EvaluatorDataError("Every discovered-candidate scenario must have a valid terminal status.")
            if not pairs:
                return []

            value_sql = ", ".join(["(%s, %s)"] * len(pairs))
            labels_sql = f"""
                WITH candidates(scenario_id, company_id) AS (VALUES {value_sql})
                SELECT candidates.scenario_id, candidates.company_id,
                       companies.shell_company,
                       EXISTS (
                           SELECT 1 FROM investigator_actions actions
                           WHERE actions.scenario_id = candidates.scenario_id
                             AND actions.company_id = candidates.company_id
                             AND actions.action_type = 'FLAG_COMPANY'
                       ) AS flagged,
                       EXISTS (
                           SELECT 1 FROM transactions transfers
                           WHERE transfers.scenario_id = candidates.scenario_id
                             AND transfers.origin = 'FRAUDSTER_ACTION'
                             AND (
                                 transfers.source_company_id = candidates.company_id
                                 OR transfers.destination_company_id = candidates.company_id
                             )
                       ) AS fraud_path_involved
                FROM candidates
                JOIN fraud_scenarios scenarios ON scenarios.id = candidates.scenario_id
                  AND scenarios.status IN ('COMPLETED', 'MAX_TURNS_REACHED')
                JOIN companies ON companies.id = candidates.company_id
                ORDER BY candidates.scenario_id, candidates.company_id
            """
            parameters = [value for pair in pairs for value in pair]
            failure_stage = "discovered_candidate_query"
            with connection.cursor() as cursor:
                cursor.execute(labels_sql, parameters)
                failure_stage = "fetch"
                rows = cursor.fetchall()
            if len(rows) != len(pairs):
                raise EvaluatorDataError("A discovered candidate is missing its scenario or ground-truth label.")
            expected_pairs = set(pairs)
            decisions: list[CandidateDecision] = []
            found_pairs: set[tuple[int, int]] = set()
            for row in rows:
                scenario_id, company_id, shell_company, flagged, fraud_path_involved = row
                pair = (scenario_id, company_id)
                if pair not in expected_pairs or pair in found_pairs:
                    raise EvaluatorDataError("Discovered-candidate query returned duplicate or unexpected pairs.")
                found_pairs.add(pair)
                if not isinstance(flagged, bool) or not isinstance(fraud_path_involved, bool):
                    raise EvaluatorDataError(
                        "Persisted flag decisions and fraud-path membership must be boolean."
                    )
                decisions.append(CandidateDecision(
                    scenario_id=scenario_id,
                    company_id=company_id,
                    shell_company=self._require_label(shell_company),
                    flagged=flagged,
                    fraud_path_involved=fraud_path_involved,
                ))
            if found_pairs != expected_pairs:
                raise EvaluatorDataError("Discovered-candidate labels do not match captured candidate pairs.")
            return decisions
        except EvaluatorDataError:
            raise
        except Exception as error:
            raise EvaluatorConfigurationError(
                "Evaluator discovered-candidate lookup failed; verify the separate read-only PostgreSQL configuration.",
                diagnostic=self._safe_database_diagnostic(error, failure_stage),
            ) from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _safe_database_diagnostic(error: Exception, stage: str) -> dict[str, str]:
        """Return bounded diagnostic fields without exception text or query data."""
        exception_type = type(error).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", exception_type):
            exception_type = "DatabaseError"
        sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
        if not isinstance(sqlstate, str) or not re.fullmatch(r"[0-9A-Z]{5}", sqlstate.upper()):
            sqlstate = "unavailable"
        else:
            sqlstate = sqlstate.upper()
        return {
            "stage": stage,
            "exception_type": exception_type,
            "sqlstate": sqlstate,
        }

    def read_correct_flag_outcomes(self, scenario_ids: Iterable[int]) -> dict[int, bool]:
        """Read persisted correct-flag evidence for terminal reward validation.

        This evaluator-only query must be called after the live scenario has
        reached a terminal status. It returns no company labels or policy data.
        """
        ids = list(dict.fromkeys(scenario_ids))
        if not ids:
            raise EvaluatorDataError("No terminal scenarios are available for reward validation.")

        connect = self._load_connect()
        placeholders = ", ".join(["%s"] * len(ids))
        sql = f"""
            SELECT scenarios.id,
                   COALESCE(BOOL_OR(actions.flag_correct IS TRUE), FALSE)
            FROM fraud_scenarios scenarios
            LEFT JOIN investigator_actions actions
              ON actions.scenario_id = scenarios.id
             AND actions.action_type = 'FLAG_COMPANY'
            WHERE scenarios.id IN ({placeholders})
            GROUP BY scenarios.id
            ORDER BY scenarios.id
        """

        connection = None
        try:
            connection = connect(self._database_url)
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(sql, ids)
                rows = cursor.fetchall()

            if len(rows) != len(ids):
                raise EvaluatorDataError(
                    "Correct-flag evidence is missing for one or more terminal scenarios."
                )
            outcomes: dict[int, bool] = {}
            for scenario_id, correctly_flagged in rows:
                if not isinstance(correctly_flagged, bool):
                    raise EvaluatorDataError(
                        "Correct-flag evidence must be boolean for every terminal scenario."
                    )
                outcomes[scenario_id] = correctly_flagged
            if set(outcomes) != set(ids):
                raise EvaluatorDataError(
                    "Correct-flag evidence does not match the requested scenarios."
                )
            return outcomes
        except EvaluatorDataError:
            raise
        except Exception as error:
            raise EvaluatorConfigurationError(
                "Evaluator correct-flag lookup failed; verify the separate read-only PostgreSQL configuration."
            ) from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _require_label(value: Any) -> bool:
        if not isinstance(value, bool):
            raise EvaluatorDataError("A candidate company is missing a boolean shell-company label.")
        return value

    @staticmethod
    def _load_connect():
        try:
            import psycopg
            return psycopg.connect
        except ImportError:
            try:
                import psycopg2
                return psycopg2.connect
            except ImportError as error:
                raise EvaluatorConfigurationError(
                    "Install psycopg or psycopg2 to enable offline PostgreSQL detection evaluation."
                ) from error
