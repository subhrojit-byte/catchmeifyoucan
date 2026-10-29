"""Evidence-based investigator policy using only permitted observations.

The score below is an initial transparent heuristic, not a statistically
validated shell-company classifier. Its bounds must be calibrated against
offline evaluation data before being treated as a production decision rule.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from state_abstraction import legal_investigator_actions


YOUNG_COMPANY_MAX_AGE_YEARS = 5
HIGH_REVENUE_PER_EMPLOYEE = Decimal("2000000")
YOUNG_COMPANY_WEIGHT = 1
HIGH_REVENUE_PER_EMPLOYEE_WEIGHT = 1
SHARED_ADDRESS_WEIGHT = 1
REUSED_DIRECTOR_WEIGHT = 2
SUSPICION_THRESHOLD = 4


def heuristic_policy_configuration() -> dict[str, Any]:
    """Return the policy's actual code defaults and fixed decision rules."""
    return {
        "source": "code defaults in rl-agents/investigator_bot.py",
        "parameters": [
            {"name": "YOUNG_COMPANY_MAX_AGE_YEARS", "value": YOUNG_COMPANY_MAX_AGE_YEARS,
             "meaning": "Maximum age treated as young, inclusive.", "effect": "Adds the young-company weight when a valid age is at or below this value."},
            {"name": "HIGH_REVENUE_PER_EMPLOYEE", "value": str(HIGH_REVENUE_PER_EMPLOYEE),
             "meaning": "Revenue-per-employee threshold, inclusive.", "effect": "Adds its weight when valid revenue divided by valid employee count meets this threshold."},
            {"name": "YOUNG_COMPANY_WEIGHT", "value": YOUNG_COMPANY_WEIGHT,
             "meaning": "Score weight for the young-company feature.", "effect": "Contributes this many points when the age feature is true."},
            {"name": "HIGH_REVENUE_PER_EMPLOYEE_WEIGHT", "value": HIGH_REVENUE_PER_EMPLOYEE_WEIGHT,
             "meaning": "Score weight for high revenue per employee.", "effect": "Contributes this many points when the revenue feature is true."},
            {"name": "SHARED_ADDRESS_WEIGHT", "value": SHARED_ADDRESS_WEIGHT,
             "meaning": "Score weight for a normalized address shared by multiple evidenced companies.", "effect": "Contributes this many points when the shared-address feature is true."},
            {"name": "REUSED_DIRECTOR_WEIGHT", "value": REUSED_DIRECTOR_WEIGHT,
             "meaning": "Score weight for a director linked to at least two distinct companies.", "effect": "Contributes this many points for each company with reused-director evidence."},
            {"name": "SUSPICION_THRESHOLD", "value": SUSPICION_THRESHOLD,
             "meaning": "Minimum evidence score for selecting FLAG_COMPANY.", "effect": "Flags the highest-ranked candidate meeting or exceeding this score."},
        ],
        "selection_rules": [
            "Risk score is the sum of the four weighted boolean features.",
            "Flag candidates sort by descending score, then ascending company ID.",
            "If no candidate meets the flag threshold, investigate source then target once; afterward investigate connected companies by descending distinct-director count, ties by ascending company ID.",
            "Candidates and features come only from public observations and sanitized relationship evidence; shell labels are not used.",
        ],
    }


@dataclass(frozen=True)
class RiskFeatures:
    young_company: bool
    high_revenue_per_employee: bool
    shared_address: bool
    reused_director: bool


def _positive_decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 and str(number) == str(value) else None


def _valid_id(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def extract_risk_features(
    company: dict[str, Any],
    *,
    shared_address: bool = False,
    reused_director: bool = False,
) -> RiskFeatures:
    """Extract only whitelisted company features and relationship indicators."""
    if not isinstance(company, dict):
        return RiskFeatures(False, False, bool(shared_address), bool(reused_director))
    age = _positive_integer(company.get("ageInYears"))
    employees = _positive_integer(company.get("numberOfEmployees"))
    revenue = _positive_decimal(company.get("annualRevenue"))

    high_revenue_per_employee = False
    if employees is not None and revenue is not None:
        high_revenue_per_employee = (
            revenue / Decimal(employees) >= HIGH_REVENUE_PER_EMPLOYEE
        )

    return RiskFeatures(
        young_company=age is not None and age <= YOUNG_COMPANY_MAX_AGE_YEARS,
        high_revenue_per_employee=high_revenue_per_employee,
        shared_address=bool(shared_address),
        reused_director=bool(reused_director),
    )


def score_risk_features(features: RiskFeatures) -> int:
    """Return the deterministic heuristic score for extracted features."""
    return (
        YOUNG_COMPANY_WEIGHT * int(features.young_company)
        + HIGH_REVENUE_PER_EMPLOYEE_WEIGHT * int(features.high_revenue_per_employee)
        + SHARED_ADDRESS_WEIGHT * int(features.shared_address)
        + REUSED_DIRECTOR_WEIGHT * int(features.reused_director)
    )


class InvestigatorPolicyError(RuntimeError):
    pass


class InvestigatorBot:
    """Stateful baseline policy using only permitted scenario observations."""

    _COMPANY_FIELDS = (
        "id",
        "companyName",
        "registrationNumber",
        "industry",
        "address",
        "ageInYears",
        "registrationDate",
        "annualRevenue",
        "numberOfEmployees",
    )
    _TRANSACTION_FIELDS = (
        "id",
        "amount",
        "timestamp",
        "description",
        "channel",
        "origin",
        "scenarioId",
        "fraudActionId",
    )

    def __init__(self) -> None:
        self._completed_actions: set[tuple[str, int]] = set()
        self._observed_company_ids: set[int] = set()
        self._director_evidence: dict[int, dict[str, Any]] = {}
        self._flagged_company_ids: set[int] = set()
        self._observation_evidence: dict[int, dict[str, Any]] = {}
        self._trace_evidence: dict[int, dict[str, Any]] = {}

    @property
    def observation_evidence(self) -> dict[int, dict[str, Any]]:
        return {company_id: dict(evidence)
                for company_id, evidence in self._observation_evidence.items()}

    @property
    def trace_evidence(self) -> dict[int, dict[str, Any]]:
        return {transaction_id: dict(evidence)
                for transaction_id, evidence in self._trace_evidence.items()}

    def legal_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Return evidence-bounded choices without changing heuristic selection."""
        candidate_company_ids = set(self._observed_company_ids)
        for company_id, evidence in self._director_evidence.items():
            candidate_company_ids.add(company_id)
            for director in evidence.get("directors", []):
                for company in director.get("associatedCompanies", []):
                    if isinstance(company, dict):
                        related_id = _valid_id(company.get("id"))
                        if related_id is not None:
                            candidate_company_ids.add(related_id)
        for transaction in self._trace_evidence.values():
            for field in ("sourceCompany", "destinationCompany"):
                company = transaction.get(field)
                if isinstance(company, dict):
                    company_id = _valid_id(company.get("id"))
                    if company_id is not None:
                        candidate_company_ids.add(company_id)

        completed = set(self._completed_actions)
        completed.update(
            ("FLAG_COMPANY", company_id)
            for company_id in self._flagged_company_ids
        )
        trace_transaction_ids = set(self._trace_evidence)
        observed_company_ids = set(candidate_company_ids)
        observed_company_ids.update(self._observed_company_ids)
        return legal_investigator_actions(
            state,
            completed_actions=completed,
            trace_transaction_ids=trace_transaction_ids,
            candidate_company_ids=candidate_company_ids,
            observed_company_ids=observed_company_ids,
        )

    def mark_action_completed(
        self,
        decision: dict[str, Any],
        response: dict[str, Any] | None = None,
    ) -> None:
        """Record sanitized evidence after the runner confirms backend success."""
        action_type = decision.get("action_type")
        company_id = decision.get("company_id")
        if action_type == "FLAG_COMPANY":
            if company_id is not None:
                self._flagged_company_ids.add(company_id)
            return
        if action_type == "TRACE_TRANSACTION":
            transaction_id = _valid_id(decision.get("transaction_id"))
            if transaction_id is None:
                return
            self._completed_actions.add((action_type, transaction_id))
            transaction = (response or {}).get("transactionTrace") or {}
            if isinstance(transaction, dict):
                sanitized = self._sanitize_transaction(transaction)
                if sanitized.get("id") == transaction_id:
                    self._trace_evidence[transaction_id] = sanitized
            return
        if action_type not in {"OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS"}:
            return
        if company_id is None:
            return

        self._completed_actions.add((action_type, company_id))
        if action_type == "OBSERVE_COMPANY":
            self._observed_company_ids.add(company_id)
            observation = (response or {}).get("observation") or {}
            if isinstance(observation, dict):
                self._observation_evidence[company_id] = {
                    "company": self._sanitize_company(observation),
                }
            return

        director_investigation = (response or {}).get("directorInvestigation") or {}
        investigated_company = director_investigation.get("company") or {}
        directors = []
        connected_company_ids: set[int] = set()
        for director in director_investigation.get("directors") or []:
            connected_companies = []
            for company in director.get("associatedCompanies") or []:
                sanitized_company = self._sanitize_company(company)
                connected_companies.append(sanitized_company)
                connected_id = sanitized_company.get("id")
                if connected_id is not None:
                    connected_company_ids.add(connected_id)
            directors.append(
                {
                    "directorId": director.get("directorId"),
                    "directorName": director.get("directorName"),
                    "associatedCompanies": connected_companies,
                }
            )

        self._director_evidence[company_id] = {
            "company": self._sanitize_company(investigated_company),
            "directors": directors,
            "connectedCompanyIds": connected_company_ids,
        }

    def evidence_summary(self) -> dict[str, Any]:
        """Summarize the sanitized director evidence retained for this episode."""
        investigated_company_ids = set(self._director_evidence)
        director_ids: set[int] = set()
        connected_company_ids: set[int] = set()
        company_director_relationships: set[tuple[int, int]] = set()
        director_company_connections: set[tuple[int, int]] = set()

        for investigated_company_id, evidence in self._director_evidence.items():
            for director in evidence.get("directors", []):
                director_id = director.get("directorId")
                if director_id is not None:
                    director_ids.add(director_id)
                    company_director_relationships.add(
                        (investigated_company_id, director_id)
                    )
                for company in director.get("associatedCompanies", []):
                    connected_company_id = company.get("id")
                    if connected_company_id is not None:
                        connected_company_ids.add(connected_company_id)
                        if director_id is not None:
                            director_company_connections.add(
                                (director_id, connected_company_id)
                            )

        return {
            "successful_director_investigations": len(investigated_company_ids),
            "investigated_company_ids": sorted(investigated_company_ids),
            "unique_director_ids_discovered": len(director_ids),
            "unique_connected_company_ids_discovered": len(connected_company_ids),
            "unique_company_director_relationships": len(
                company_director_relationships
            ),
            "unique_director_company_connections": len(
                director_company_connections
            ),
        }

    @classmethod
    def sanitize_action_response(
        cls,
        response: Any,
        *,
        scenario_id: int | None = None,
        expected_transaction_id: int | None = None,
    ) -> dict[str, Any]:
        """Keep only response fields permitted for policy memory."""
        if not isinstance(response, dict):
            return {}
        sanitized: dict[str, Any] = {}
        raw_observation = response.get("observation")
        if isinstance(raw_observation, dict):
            sanitized["observation"] = cls._sanitize_company(raw_observation)

        raw_investigation = response.get("directorInvestigation")
        if isinstance(raw_investigation, dict):
            directors = []
            for director in raw_investigation.get("directors") or []:
                if not isinstance(director, dict):
                    continue
                associated_companies = []
                for company in director.get("associatedCompanies") or []:
                    if isinstance(company, dict):
                        associated_companies.append(cls._sanitize_company(company))
                directors.append(
                    {
                        "directorId": director.get("directorId"),
                        "directorName": director.get("directorName"),
                        "associatedCompanies": associated_companies,
                    }
                )

            company = raw_investigation.get("company")
            sanitized["directorInvestigation"] = {
                "company": cls._sanitize_company(company) if isinstance(company, dict) else {},
                "directors": directors,
            }

        raw_transaction = response.get("transactionTrace")
        if isinstance(raw_transaction, dict):
            transaction = cls._sanitize_transaction(raw_transaction)
            transaction_scenario_id = transaction.get("scenarioId")
            transaction_id = transaction.get("id")
            if (scenario_id is None or _valid_id(transaction_scenario_id) == scenario_id) and (
                    expected_transaction_id is None
                    or _valid_id(transaction_id) == expected_transaction_id):
                sanitized["transactionTrace"] = transaction

        return sanitized

    @classmethod
    def sanitize_transaction_history(
        cls,
        history: Any,
        scenario_id: int,
    ) -> list[dict[str, Any]] | None:
        """Validate and whitelist scenario-scoped transaction history."""
        if not isinstance(history, list) or _valid_id(scenario_id) is None:
            return None
        sanitized_history = []
        for item in history:
            if not isinstance(item, dict):
                return None
            transaction = cls._sanitize_transaction(item)
            source_company = item.get("sourceCompany")
            destination_company = item.get("destinationCompany")
            transaction_scenario_id = _valid_id(transaction.get("scenarioId"))
            amount = _positive_decimal(transaction.get("amount"))
            if (transaction.get("id") is None
                    or transaction_scenario_id != scenario_id
                    or amount is None
                    or not isinstance(source_company, dict)
                    or not isinstance(destination_company, dict)
                    or _valid_id(source_company.get("id")) is None
                    or _valid_id(destination_company.get("id")) is None
                    or _valid_id(transaction.get("id")) is None):
                return None
            sanitized_history.append(transaction)
        return sanitized_history

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") != "ACTIVE":
            raise InvestigatorPolicyError("Scenario is not active.")
        if state.get("turn") != "INVESTIGATOR":
            raise InvestigatorPolicyError("It is not the investigator turn.")
        if state.get("investigatorActionsRemaining", 0) <= 0:
            raise InvestigatorPolicyError("No investigator actions remain.")

        for company_id, score in self._rank_flag_candidates():
            if score >= SUSPICION_THRESHOLD:
                return {
                    "action_type": "FLAG_COMPANY",
                    "company_id": company_id,
                }

        source = state.get("sourceCompany") or {}
        target = state.get("targetCompany") or {}
        source_id = source.get("id")
        target_id = target.get("id")

        # Start with one director investigation for each scenario company.
        for company_id in (source_id, target_id):
            if company_id is not None and (
                    "INVESTIGATE_DIRECTORS", company_id
            ) not in self._completed_actions:
                return {
                    "action_type": "INVESTIGATE_DIRECTORS",
                    "company_id": company_id,
                }

        # Prefer connected companies whose director relationships are not known.
        # These IDs came from successful, sanitized director investigations and
        # are ranked by distinct directors connecting them to known companies.
        for company_id in self._rank_connected_company_candidates():
            return {
                "action_type": "INVESTIGATE_DIRECTORS",
                "company_id": company_id,
            }

        raise InvestigatorPolicyError(
            "No useful non-repeating investigator action is available from the exposed scenario state."
        )

    def _rank_flag_candidates(self) -> list[tuple[int, int]]:
        """Rank evidenced companies without using scenario role or labels."""
        companies: dict[int, dict[str, Any]] = {}
        reused_directors: dict[int, set[int]] = {}

        for investigated_company_id, evidence in self._director_evidence.items():
            investigated_company_id = _valid_id(investigated_company_id)
            investigated_company = evidence.get("company") or {}
            if investigated_company_id is not None:
                companies[investigated_company_id] = investigated_company

            for director in evidence.get("directors", []):
                if not isinstance(director, dict):
                    continue
                director_id = _valid_id(director.get("directorId"))
                associated = [
                    company for company in director.get("associatedCompanies", [])
                    if isinstance(company, dict)
                ]
                associated_ids = {
                    company_id
                    for company_id in (_valid_id(item.get("id")) for item in associated)
                    if company_id is not None
                }
                if investigated_company_id is not None:
                    associated_ids.add(investigated_company_id)

                for company in associated:
                    company_id = _valid_id(company.get("id"))
                    if company_id is not None:
                        companies[company_id] = company

                # Count a reused director once per company, only when the
                # director is associated with at least two distinct companies.
                if director_id is not None and len(associated_ids) >= 2:
                    for company_id in associated_ids:
                        reused_directors.setdefault(company_id, set()).add(director_id)

        address_counts: dict[str, set[int]] = {}
        for company_id, company in companies.items():
            address = company.get("address")
            if isinstance(address, str) and address.strip():
                address_counts.setdefault(address.strip().casefold(), set()).add(company_id)

        ranked: list[tuple[int, int]] = []
        for company_id, company in companies.items():
            if company_id in self._flagged_company_ids:
                continue
            normalized_address = company.get("address")
            address_is_shared = (
                isinstance(normalized_address, str)
                and len(address_counts.get(normalized_address.strip().casefold(), set())) > 1
            )
            features = extract_risk_features(
                company,
                shared_address=address_is_shared,
                reused_director=bool(reused_directors.get(company_id)),
            )
            ranked.append((company_id, score_risk_features(features)))

        return sorted(ranked, key=lambda item: (-item[1], item[0]))

    def _rank_connected_company_candidates(self) -> list[int]:
        """Return uninvestigated connected companies by graph evidence strength."""
        candidate_directors: dict[int, set[int]] = {}
        investigated_company_ids = set(self._director_evidence)

        for evidence in self._director_evidence.values():
            for director in evidence.get("directors", []):
                director_id = director.get("directorId")
                if director_id is None:
                    continue
                for company in director.get("associatedCompanies", []):
                    company_id = company.get("id")
                    if company_id is None:
                        continue
                    if company_id in investigated_company_ids:
                        continue
                    if ("INVESTIGATE_DIRECTORS", company_id) in self._completed_actions:
                        continue
                    candidate_directors.setdefault(company_id, set()).add(director_id)

        return sorted(
            candidate_directors,
            key=lambda company_id: (-len(candidate_directors[company_id]), company_id),
        )

    @classmethod
    def _sanitize_company(cls, company: dict[str, Any]) -> dict[str, Any]:
        return {field: company.get(field) for field in cls._COMPANY_FIELDS if field in company}

    @classmethod
    def _sanitize_transaction(cls, transaction: dict[str, Any]) -> dict[str, Any]:
        sanitized = {
            field: transaction.get(field)
            for field in cls._TRANSACTION_FIELDS
            if field in transaction
        }
        for field in ("sourceCompany", "destinationCompany"):
            company = transaction.get(field)
            if isinstance(company, dict):
                sanitized[field] = cls._sanitize_company(company)
        return sanitized
