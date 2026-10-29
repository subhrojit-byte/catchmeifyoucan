"""Compact public-state abstractions and legal-action filters."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


STATE_ABSTRACTION_VERSION = "fraudster-state-abstraction-v4"
INVESTIGATOR_STATE_ABSTRACTION_VERSION = "state-abstraction-v3"
LEGAL_ACTION_SCHEMA_VERSION = "legal-actions-v2"


def _amount(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _bucket(value: Decimal, boundaries: tuple[Decimal, ...]) -> int:
    for index, boundary in enumerate(boundaries):
        if value < boundary:
            return index
    return len(boundaries)


def _public_numeric_bucket(company: dict[str, Any], field: str,
                           boundaries: tuple[Decimal, ...]) -> int:
    """Bucket one allowlisted public numeric feature; -1 means unavailable."""
    if field not in company or isinstance(company.get(field), bool):
        return -1
    try:
        value = Decimal(str(company[field]))
    except (InvalidOperation, TypeError, ValueError):
        return -1
    if not value.is_finite() or value < 0:
        return -1
    return _bucket(value, boundaries)


def public_company_evidence_profile(company: Any) -> tuple[int, ...]:
    """Return a bounded profile from public company fields only.

    Raw identifiers, names, addresses, labels, and unbounded strings never
    enter the learned state or learned action key.
    """
    if not isinstance(company, dict):
        company = {}
    address = company.get("address")
    if isinstance(address, str):
        normalized = address.strip()
        address_features = (
            int(bool(normalized)),
            _bucket(Decimal(len(normalized)),
                    (Decimal(1), Decimal(16), Decimal(40), Decimal(80))),
            int(any(character.isdigit() for character in normalized)),
            _bucket(Decimal(normalized.count(",")),
                    (Decimal(0), Decimal(1), Decimal(2))),
        )
    else:
        address_features = (0, -1, 0, -1)
    return (
        _public_numeric_bucket(
            company, "ageInYears", (Decimal(2), Decimal(5), Decimal(12), Decimal(20))
        ),
        _public_numeric_bucket(
            company, "numberOfEmployees",
            (Decimal(0), Decimal(1), Decimal(5), Decimal(20), Decimal(100), Decimal(500)),
        ),
        _public_numeric_bucket(
            company, "annualRevenue",
            (Decimal(0), Decimal(100000), Decimal(500000), Decimal(1000000),
             Decimal(5000000), Decimal(20000000)),
        ),
        *address_features,
    )


def _valid_id(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def validated_transaction_ids(state: dict[str, Any]) -> list[int]:
    """Return IDs from the runner-validated history for this scenario."""
    scenario_id = _valid_id(state.get("id"))
    if scenario_id is None or not isinstance(state.get("transactionHistory"), list):
        return []
    transaction_ids = set()
    for transaction in state["transactionHistory"]:
        if not isinstance(transaction, dict):
            continue
        transaction_id = _valid_id(transaction.get("id"))
        source = transaction.get("sourceCompany")
        destination = transaction.get("destinationCompany")
        if (transaction_id is not None
                and transaction.get("scenarioId") == scenario_id
                and isinstance(source, dict)
                and isinstance(destination, dict)
                and _valid_id(source.get("id")) is not None
                and _valid_id(destination.get("id")) is not None):
            transaction_ids.add(transaction_id)
    return sorted(transaction_ids)


_TRANSACTION_ORIGINS = ("INITIAL_BACKGROUND", "BACKGROUND", "FRAUDSTER_ACTION")
_INVESTIGATOR_FLOW_EDGE_LIMIT = 16
_INVESTIGATOR_FLOW_EDGE_COUNT_LIMIT = 4
_TRANSACTION_AMOUNT_RATIO_BOUNDARIES = (
    Decimal("0.1"), Decimal("0.25"), Decimal("0.5"),
    Decimal("0.75"), Decimal(1), Decimal(2),
)


def _bounded_count(values: Iterable[Any], maximum: int = 4) -> int:
    """Convert an observable collection into a small categorical count."""
    unique_values = set()
    for value in values:
        try:
            unique_values.add(value)
        except TypeError:
            # Malformed evidence is not allowed to make state construction fail.
            continue
    return min(len(unique_values), maximum)


def transaction_origin_counts(state: dict[str, Any]) -> tuple[int, ...]:
    """Return bounded counts for validated, scenario-local transaction origins."""
    scenario_id = _valid_id(state.get("id"))
    counts = {origin: 0 for origin in _TRANSACTION_ORIGINS}
    history = state.get("transactionHistory")
    if scenario_id is None or not isinstance(history, list):
        return tuple(0 for _ in _TRANSACTION_ORIGINS)
    for transaction in history:
        if not isinstance(transaction, dict):
            continue
        transaction_id = _valid_id(transaction.get("id"))
        source = transaction.get("sourceCompany")
        destination = transaction.get("destinationCompany")
        if (transaction_id is None
                or transaction.get("scenarioId") != scenario_id
                or not isinstance(source, dict)
                or not isinstance(destination, dict)
                or _valid_id(source.get("id")) is None
                or _valid_id(destination.get("id")) is None):
            continue
        origin = transaction.get("origin")
        if origin in counts:
            counts[origin] += 1
    return tuple(min(counts[origin], 4) for origin in _TRANSACTION_ORIGINS)


def investigator_transaction_flow_features(state: dict[str, Any]) -> tuple[Any, ...]:
    """Return bounded directed public transaction-edge and amount features.

    Company IDs and names are used neither as features nor as tie-breakers.
    Endpoint roles distinguish the scenario source and target from other
    companies; other endpoints are represented by their allowlisted public
    company profile. Amounts are bucketed relative to the public target amount.
    """
    target_amount = _amount(state.get("targetAmount"))
    source_id = _valid_id((state.get("sourceCompany") or {}).get("id"))
    target_id = _valid_id((state.get("targetCompany") or {}).get("id"))
    counts: Counter[tuple[Any, ...]] = Counter()
    for transaction in _valid_scenario_history(state):
        source = transaction["sourceCompany"]
        destination = transaction["destinationCompany"]
        origin = transaction.get("origin")
        origin_index = (
            _TRANSACTION_ORIGINS.index(origin)
            if origin in _TRANSACTION_ORIGINS else len(_TRANSACTION_ORIGINS)
        )
        amount = _amount(transaction.get("amount"))
        amount_bucket = (
            _bucket(amount / target_amount, _TRANSACTION_AMOUNT_RATIO_BOUNDARIES)
            if amount > 0 and target_amount > 0 else -1
        )
        signature = (
            origin_index,
            _investigator_transaction_endpoint(source, source_id, target_id),
            _investigator_transaction_endpoint(destination, source_id, target_id),
            amount_bucket,
        )
        counts[signature] += 1

    # Keep fraudster-action edges first so ordinary background noise cannot
    # displace the route evidence the investigator is meant to learn from.
    fraudster_origin_index = _TRANSACTION_ORIGINS.index("FRAUDSTER_ACTION")
    signatures = sorted(
        counts,
        key=lambda signature: (
            0 if signature[0] == fraudster_origin_index else 1,
            signature,
        ),
    )[:_INVESTIGATOR_FLOW_EDGE_LIMIT]
    return tuple(
        (signature, min(counts[signature], _INVESTIGATOR_FLOW_EDGE_COUNT_LIMIT))
        for signature in signatures
    )


def _investigator_transaction_endpoint(
    company: dict[str, Any], source_id: int | None, target_id: int | None
) -> tuple[int, tuple[int, ...]]:
    company_id = _valid_id(company.get("id"))
    if company_id is not None and company_id == source_id:
        role = 0
    elif company_id is not None and company_id == target_id:
        role = 1
    else:
        role = 2
    return role, public_company_evidence_profile(company)


def fraudster_state_key(state: dict[str, Any]) -> tuple[Any, ...]:
    positions = state.get("positions") or []
    funded = sum(1 for position in positions if _amount(position.get("amount")) > 0)
    target_amount = _amount(state.get("targetAmount"))
    target_id = (state.get("targetCompany") or {}).get("id")
    target_balance = sum(
        (_amount(position.get("amount")) for position in positions
         if (position.get("company") or {}).get("id") == target_id),
        Decimal(0),
    )
    ratio = target_balance / target_amount if target_amount > 0 else Decimal(0)
    intermediary_features = []
    for company in state.get("eligibleIntermediaries") or []:
        if not isinstance(company, dict):
            continue
        revenue = _amount(company.get("annualRevenue"))
        employees = _amount(company.get("numberOfEmployees"))
        per_employee = revenue / employees if employees > 0 else Decimal(0)
        intermediary_features.append((
            _bucket(_amount(company.get("ageInYears")),
                    (Decimal(2), Decimal(5), Decimal(12), Decimal(20))),
            _bucket(employees, (Decimal(5), Decimal(20), Decimal(100), Decimal(500))),
            _bucket(per_employee, (Decimal("150000"), Decimal("500000"), Decimal("1000000"),
                                   Decimal("2500000"))),
        ))
    known_shell_ids = sorted({
        valid_id for valid_id in (_valid_id(item) for item in state.get("privateShellCompanyIds", []))
        if valid_id is not None
    })
    return (
        state.get("status"),
        state.get("turn"),
        min(int(state.get("step") or 0), 3),
        min(len(positions), 4),
        min(funded, 4),
        _bucket(ratio, (Decimal(0), Decimal("0.5"), Decimal("1"))),
        bool(state.get("financialObjectiveAchieved")),
        transaction_origin_counts(state),
        _bucket(sum((_amount(t.get("amount")) for t in _valid_scenario_history(state)), Decimal(0))
                / target_amount if target_amount > 0 else Decimal(0),
                (Decimal(0), Decimal("0.5"), Decimal("1"))),
        min(_route_revisit_count(state), 4),
        min(len(known_shell_ids), 8),
        tuple(known_shell_ids[:8]),
        min(len(intermediary_features), 8),
        tuple(sorted(intermediary_features)[:8]),
    )


def _valid_scenario_history(state: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_id = _valid_id(state.get("id"))
    history = state.get("transactionHistory")
    if scenario_id is None or not isinstance(history, list):
        return []
    return [item for item in history if isinstance(item, dict)
            and item.get("scenarioId") == scenario_id
            and _valid_id(item.get("id")) is not None
            and isinstance(item.get("sourceCompany"), dict)
            and isinstance(item.get("destinationCompany"), dict)
            and _valid_id(item["sourceCompany"].get("id")) is not None
            and _valid_id(item["destinationCompany"].get("id")) is not None]


def _route_revisit_count(state: dict[str, Any]) -> int:
    """Bounded count of scenario transactions that revisit an earlier company."""
    seen: set[int] = set()
    revisits = 0
    for item in _valid_scenario_history(state):
        source = item["sourceCompany"]["id"]
        destination = item["destinationCompany"]["id"]
        if source in seen or destination in seen:
            revisits += 1
        seen.update((source, destination))
    return revisits


def investigator_state_key(
    state: dict[str, Any],
    *,
    investigated_company_ids: Iterable[int] = (),
    flagged_company_ids: Iterable[int] = (),
    trace_transaction_ids: Iterable[int] = (),
    candidate_company_ids: Iterable[int] = (),
    observed_company_ids: Iterable[int] = (),
    discovered_director_ids: Iterable[int] = (),
    director_relationships: Iterable[Any] = (),
    company_evidence_by_id: dict[int, dict[str, Any]] | None = None,
) -> tuple[Any, ...]:
    """Build a bounded key from policy-visible investigator evidence only.

    IDs are used only to count distinct evidence in memory; no identifier is
    placed in the resulting key. Transaction history is independently checked
    for the current scenario before its origin counts are included.
    """
    source_id = (state.get("sourceCompany") or {}).get("id")
    target_id = (state.get("targetCompany") or {}).get("id")
    investigated = set(investigated_company_ids)
    flagged = set(flagged_company_ids)
    candidates = {
        company_id for company_id in (_valid_id(item) for item in candidate_company_ids)
        if company_id is not None
    }
    observed = {
        company_id for company_id in (_valid_id(item) for item in observed_company_ids)
        if company_id is not None
    }
    investigated = {
        company_id for company_id in (_valid_id(item) for item in investigated_company_ids)
        if company_id is not None
    }
    flagged = {
        company_id for company_id in (_valid_id(item) for item in flagged_company_ids)
        if company_id is not None
    }
    evidence_by_id = dict(company_evidence_by_id or {})
    for company in (state.get("sourceCompany") or {}, state.get("targetCompany") or {}):
        company_id = _valid_id(company.get("id")) if isinstance(company, dict) else None
        if company_id is not None:
            candidates.add(company_id)
            evidence_by_id.setdefault(company_id, company)
    for position in state.get("positions") or []:
        company = position.get("company") if isinstance(position, dict) else None
        company_id = _valid_id(company.get("id")) if isinstance(company, dict) else None
        if company_id is not None:
            candidates.add(company_id)
            evidence_by_id.setdefault(company_id, company)
    relationships = set()
    for relationship in director_relationships:
        if not isinstance(relationship, (tuple, list)) or len(relationship) != 2:
            continue
        director_id, linked_company_id = map(_valid_id, relationship)
        if director_id is not None and linked_company_id is not None:
            relationships.add((director_id, linked_company_id))
    profile_counts: dict[tuple[Any, ...], int] = {}
    for company_id in candidates:
        profile = (
            public_company_evidence_profile(evidence_by_id.get(company_id)),
            company_id in observed,
            company_id in investigated,
            company_id in flagged,
            min(sum(1 for _, linked_company_id in relationships
                    if linked_company_id == company_id), 4),
        )
        profile_counts[profile] = min(profile_counts.get(profile, 0) + 1, 4)
    # Bound by distinct profiles rather than IDs so ordering and truncation do
    # not favor a particular company identifier.
    candidate_evidence = tuple(
        (profile, profile_counts[profile])
        for profile in sorted(profile_counts)[:8]
    )
    return (
        state.get("status"),
        state.get("turn"),
        min(max(int(state.get("investigatorActionsRemaining") or 0), 0), 3),
        source_id in investigated,
        target_id in investigated,
        source_id in flagged,
        target_id in flagged,
        _bounded_count(investigated, 4),
        _bounded_count(flagged, 4),
        _bounded_count(trace_transaction_ids, 4),
        _bounded_count(candidates, 8),
        _bounded_count(observed, 8),
        _bounded_count(discovered_director_ids, 4),
        _bounded_count(director_relationships, 6),
        transaction_origin_counts(state),
        investigator_transaction_flow_features(state),
        bool(state.get("financialObjectiveAchieved")),
        candidate_evidence,
    )


def legal_fraudster_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return backend-supported actions from validated candidate IDs only."""
    if state.get("status") != "ACTIVE" or state.get("turn") != "FRAUDSTER":
        return []
    funded = [
        position for position in state.get("positions") or []
        if _valid_id(position.get("id")) is not None
        and _valid_id((position.get("company") or {}).get("id")) is not None
        and _amount(position.get("amount")) > 0
        and (position.get("company") or {}).get("id")
        != (state.get("targetCompany") or {}).get("id")
    ]
    funded.sort(key=lambda position: str(position.get("id")))
    actions = [
        {"action_type": "DIRECT_TRANSFER", "source_position_id": position["id"], "targets": None}
        for position in funded
    ]
    eligible_by_source = state.get("eligibleIntermediateCompanyIds")
    if not isinstance(eligible_by_source, dict):
        eligible_by_source = {}
    # IDs must come from the backend eligibility result and be backed by a
    # successfully fetched public company record in this observation.
    validated_company_ids = {
        company_id
        for company_id in (_valid_id((company or {}).get("id"))
                           for company in state.get("eligibleIntermediaries") or [])
        if company_id is not None
    }
    for position in funded:
        source_company_id = _valid_id((position.get("company") or {}).get("id"))
        raw_ids = eligible_by_source.get(str(source_company_id), [])
        eligible = sorted({item for item in (_valid_id(value) for value in raw_ids)
                           if item is not None and item != source_company_id
                           and item != (state.get("targetCompany") or {}).get("id")
                           and item in validated_company_ids}) \
            if isinstance(raw_ids, list) else []
        amount = _amount(position.get("amount"))
        actions.extend({
            "action_type": "ROUTE_TRANSFER", "source_position_id": position["id"],
            "targets": [{"destinationCompanyId": company_id, "amount": str(amount)}],
        } for company_id in eligible)
        for index, first in enumerate(eligible):
            for second in eligible[index + 1:]:
                half = amount / 2
                actions.append({
                    "action_type": "SPLIT_TRANSFER", "source_position_id": position["id"],
                    "targets": [
                        {"destinationCompanyId": first, "amount": str(half)},
                        {"destinationCompanyId": second, "amount": str(amount - half)},
                    ],
                })
    wait_position = next(
        (position for position in state.get("positions") or []
         if _valid_id(position.get("id")) is not None),
        None,
    )
    if wait_position is not None:
        actions.append({"action_type": "WAIT", "source_position_id": wait_position["id"], "targets": []})
    return actions


def legal_investigator_actions(
    state: dict[str, Any],
    *,
    completed_actions: Iterable[tuple[str, int]] = (),
    trace_transaction_ids: Iterable[int] = (),
    candidate_company_ids: Iterable[int] = (),
    observed_company_ids: Iterable[int] = (),
) -> list[dict[str, Any]]:
    """Return actions supported by confirmed observable scenario evidence."""
    if (state.get("status") != "ACTIVE"
            or state.get("turn") != "INVESTIGATOR"
            or int(state.get("investigatorActionsRemaining") or 0) <= 0):
        return []
    completed = set(completed_actions)
    candidates = []
    for company in (state.get("sourceCompany") or {}, state.get("targetCompany") or {}):
        company_id = _valid_id(company.get("id"))
        if company_id is None or company_id in candidates:
            continue
        candidates.append(company_id)
    for company in state.get("positions") or []:
        company_id = _valid_id((company.get("company") or {}).get("id"))
        if company_id is not None and company_id not in candidates:
            candidates.append(company_id)
    for company_id in candidate_company_ids:
        company_id = _valid_id(company_id)
        if company_id is not None and company_id not in candidates:
            candidates.append(company_id)

    observed = {
        company_id for company_id in (_valid_id(item) for item in observed_company_ids)
        if company_id is not None
    }
    observed.update(candidates[:2])
    observed.update(
        _valid_id((position.get("company") or {}).get("id"))
        for position in state.get("positions") or []
        if _valid_id((position.get("company") or {}).get("id")) is not None
    )
    actions: list[dict[str, Any]] = []
    for company_id in candidates:
        action_types = ("OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS")
        if company_id in observed:
            action_types += ("FLAG_COMPANY",)
        for action_type in action_types:
            if (action_type, company_id) not in completed:
                actions.append({"action_type": action_type, "company_id": company_id})
    supplied_trace_ids = {
        transaction_id
        for transaction_id in (_valid_id(item) for item in trace_transaction_ids)
        if transaction_id is not None
    }
    valid_trace_ids = supplied_trace_ids.intersection(
        validated_transaction_ids(state)
    )
    for transaction_id in sorted(valid_trace_ids):
        if ("TRACE_TRANSACTION", transaction_id) not in completed:
            actions.append({"action_type": "TRACE_TRANSACTION", "transaction_id": transaction_id})
    return actions

