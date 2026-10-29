"""Coordinate placeholder fraudster and investigator policies."""

from __future__ import annotations

import argparse
from copy import deepcopy
from typing import Any, Sequence

try:
    from .api_client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError
    from .fraudster_bot import FraudsterBot
    from . import investigator_bot as investigator_bot_module
    from .investigator_bot import InvestigatorBot
except ImportError:  # Supports ``python run_episode.py`` from rl-agents.
    from api_client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError
    from fraudster_bot import FraudsterBot
    import investigator_bot as investigator_bot_module
    from investigator_bot import InvestigatorBot


TERMINAL_STATUSES = frozenset({"COMPLETED", "MAX_TURNS_REACHED"})
VALID_SCENARIO_STATUSES = TERMINAL_STATUSES | {"ACTIVE"}
FRAUDSTER_ACTION_TYPES = (
    "DIRECT_TRANSFER",
    "ROUTE_TRANSFER",
    "SPLIT_TRANSFER",
    "WAIT",
)

_PUBLIC_COMPANY_FIELDS = frozenset({
    "id", "companyName", "registrationNumber", "industry", "address",
    "ageInYears", "registrationDate", "annualRevenue", "numberOfEmployees",
})
_PUBLIC_SCENARIO_FIELDS = frozenset({
    "id", "sourceCompany", "targetCompany", "targetAmount", "positions",
    "status", "step", "turn", "investigatorActionsRemaining",
    "financialObjectiveAchieved",
})
_ROLE_OBSERVATION_FIELDS = {
    # Keep the currently consumed public state shape stable. The role-specific
    # projections are explicit so later stages can diverge them deliberately.
    "FRAUDSTER": _PUBLIC_SCENARIO_FIELDS | {
        "transactionHistory", "privateShellCompanyIds", "eligibleIntermediateCompanyIds",
        "eligibleIntermediaries",
    },
    "INVESTIGATOR": _PUBLIC_SCENARIO_FIELDS | {"transactionHistory"},
}


class AgentObservationError(RuntimeError):
    """A required public observation could not be built safely."""


def validate_scenario_status(state: Any) -> str:
    """Return an authoritative status or reject malformed backend state."""
    if not isinstance(state, dict):
        raise RuntimeError("Scenario state refresh returned a malformed response.")
    status = state.get("status")
    if not isinstance(status, str) or status not in VALID_SCENARIO_STATUSES:
        raise RuntimeError(f"Unexpected or missing scenario status: {status!r}.")
    return status


def _state_line(state: dict[str, Any]) -> str:
    return (
        f"status={state.get('status')!r}, turn={state.get('turn')!r}, "
        f"step={state.get('step')}, objectiveAchieved="
        f"{state.get('financialObjectiveAchieved')!r}, "
        f"investigatorActionsRemaining={state.get('investigatorActionsRemaining')}"
    )


def _action_line(decision: dict[str, Any]) -> str:
    details = []
    for key in ("source_position_id", "company_id", "transaction_id"):
        if decision.get(key) is not None:
            details.append(f"{key}={decision[key]}")
    return ", ".join([f"type={decision.get('action_type')!r}", *details])


def _with_scenario_transaction_history(
    client: CatchMeIfYouCanApiClient,
    scenario_id: int,
    state: dict[str, Any],
    *,
    role: str = "INVESTIGATOR",
) -> dict[str, Any]:
    """Compatibility wrapper for one required validated role observation."""
    return build_agent_observation(client, scenario_id, state, role=role)


def _sanitize_public_company(company: Any, *, location: str) -> dict[str, Any]:
    if not isinstance(company, dict):
        raise AgentObservationError(f"Malformed public company evidence at {location}.")
    return {field: deepcopy(company[field]) for field in _PUBLIC_COMPANY_FIELDS if field in company}


def _sanitize_public_scenario(state: Any, scenario_id: int) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise AgentObservationError("Scenario observation is not an object.")
    observed_id = state.get("id")
    if (isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0
            or isinstance(observed_id, bool) or not isinstance(observed_id, int)
            or observed_id <= 0 or observed_id != scenario_id):
        raise AgentObservationError("Scenario observation ID is missing or mismatched.")

    sanitized: dict[str, Any] = {}
    for field in _PUBLIC_SCENARIO_FIELDS:
        if field not in state:
            continue
        value = state[field]
        if field in {"sourceCompany", "targetCompany"}:
            sanitized[field] = _sanitize_public_company(value, location=field)
        elif field == "positions":
            if not isinstance(value, list):
                raise AgentObservationError("Scenario positions are malformed.")
            positions = []
            for index, position in enumerate(value):
                if not isinstance(position, dict):
                    raise AgentObservationError("Scenario position is malformed.")
                clean_position = {
                    key: deepcopy(position[key])
                    for key in ("id", "amount") if key in position
                }
                clean_position["company"] = _sanitize_public_company(
                    position.get("company"), location=f"positions[{index}].company"
                )
                positions.append(clean_position)
            sanitized[field] = positions
        else:
            sanitized[field] = deepcopy(value)
    return sanitized


def build_agent_observations(
    client: CatchMeIfYouCanApiClient,
    scenario_id: int,
    state: dict[str, Any],
    *,
    private_shell_company_ids: Sequence[int] = (),
) -> dict[str, dict[str, Any]]:
    """Build role-specific observations from validated evidence and private grants.

    History is required for both roles and both execution paths. A fetch error,
    malformed response, or transaction from another scenario fails the decision
    instead of letting malformed history alter a policy decision. Private IDs
    must be supplied explicitly by the authorized caller and are fraudster-only.
    """
    get_history = getattr(client, "get_scenario_transactions", None)
    if not callable(get_history):
        raise AgentObservationError(
            "Agent client does not expose scenario-scoped transaction history."
        )
    try:
        raw_history = get_history(scenario_id)
        history = investigator_bot_module.InvestigatorBot.sanitize_transaction_history(
            raw_history, scenario_id
        )
    except Exception as error:
        raise AgentObservationError(
            "Unable to fetch validated scenario transaction history."
        ) from error
    if history is None:
        raise AgentObservationError(
            "Scenario transaction history failed validation or included another scenario."
        )

    public_state = _sanitize_public_scenario(state, scenario_id)
    public_state["transactionHistory"] = history
    if (isinstance(private_shell_company_ids, (str, bytes))
            or not isinstance(private_shell_company_ids, Sequence)
            or any(not _is_positive_id(item) for item in private_shell_company_ids)
            or len(set(private_shell_company_ids)) != len(private_shell_company_ids)):
        raise AgentObservationError("Authorized private shell-company IDs are malformed.")
    fraudster_state = deepcopy(public_state)
    fraudster_state["privateShellCompanyIds"] = sorted(private_shell_company_ids)
    eligible: dict[str, list[int]] = {}
    eligible_companies: dict[int, dict[str, Any]] = {}
    get_eligible = getattr(client, "get_eligible_intermediate_companies", None)
    get_company = getattr(client, "get_company", None)
    if callable(get_eligible):
        target_id = (public_state.get("targetCompany") or {}).get("id")
        source_ids = {
            (position.get("company") or {}).get("id")
            for position in public_state.get("positions", [])
        }
        try:
            for source_id in sorted(item for item in source_ids if _is_positive_id(item)):
                raw_ids = get_eligible(source_id)
                if not isinstance(raw_ids, list) or any(not _is_positive_id(item) for item in raw_ids):
                    raise AgentObservationError("Eligible intermediary response failed validation.")
                eligible[str(source_id)] = sorted({item for item in raw_ids
                                                   if item != source_id and item != target_id})
                if callable(get_company):
                    for company_id in eligible[str(source_id)]:
                        if company_id not in eligible_companies:
                            raw_company = get_company(company_id)
                            if not isinstance(raw_company, dict) or raw_company.get("id") != company_id:
                                raise AgentObservationError("Intermediary company response failed validation.")
                            eligible_companies[company_id] = _sanitize_public_company(
                                raw_company, location="eligibleIntermediaries"
                            )
        except Exception as error:
            raise AgentObservationError("Unable to fetch validated intermediary candidates.") from error
    fraudster_state["eligibleIntermediateCompanyIds"] = eligible
    fraudster_state["eligibleIntermediaries"] = [
        eligible_companies[company_id] for company_id in sorted(eligible_companies)
    ]
    eligible_all = {company_id for values in eligible.values() for company_id in values}
    if not set(private_shell_company_ids).issubset(eligible_all):
        raise AgentObservationError(
            "Authorized private shell-company IDs are outside validated scenario intermediaries."
        )
    return {
        role: {
            field: deepcopy((fraudster_state if role == "FRAUDSTER" else public_state)[field])
            for field in _ROLE_OBSERVATION_FIELDS[role]
            if field in (fraudster_state if role == "FRAUDSTER" else public_state)
        }
        for role in ("FRAUDSTER", "INVESTIGATOR")
    }


def _is_positive_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def build_agent_observation(
    client: CatchMeIfYouCanApiClient,
    scenario_id: int,
    state: dict[str, Any],
    *,
    role: str,
    private_shell_company_ids: Sequence[int] = (),
) -> dict[str, Any]:
    """Build one policy's sanitized observation through the shared path."""
    if role not in _ROLE_OBSERVATION_FIELDS:
        raise AgentObservationError(f"Unknown agent observation role: {role!r}.")
    # Private IDs are accepted only for the fraudster projection. The investigator
    # path never passes, fetches, or receives the private feature.
    ids = private_shell_company_ids if role == "FRAUDSTER" else ()
    return build_agent_observations(
        client, scenario_id, state, private_shell_company_ids=ids
    )[role]


def with_required_scenario_transaction_history(
    client: CatchMeIfYouCanApiClient,
    scenario_id: int,
    state: dict[str, Any],
    *,
    role: str = "INVESTIGATOR",
) -> dict[str, Any]:
    """Compatibility wrapper for training's required validated observation."""
    return build_agent_observation(client, scenario_id, state, role=role)


def _print_episode_summary(
    scenario_id: int,
    attempted: int,
    state: dict[str, Any],
    stop_reason: str,
    investigator: Any | None = None,
) -> None:
    evidence_summary = getattr(investigator, "evidence_summary", None)
    if not callable(evidence_summary):
        evidence_summary = getattr(getattr(investigator, "fallback", None), "evidence_summary", None)
    evidence = (
        evidence_summary() if callable(evidence_summary) else None
    )
    print(
        f"Episode summary: scenario_id={scenario_id}, actions_attempted={attempted}, "
        f"status={state.get('status')!r}, "
        f"objectiveAchieved={state.get('financialObjectiveAchieved')!r}, "
        f"turn={state.get('turn')!r}, "
        f"investigatorActionsRemaining={state.get('investigatorActionsRemaining')}, "
        f"stopped_because={stop_reason}, "
        f"investigator_evidence={evidence!r}"
    )


def _update_episode_result(
    result_collector: dict[str, Any] | None,
    *,
    final_state: dict[str, Any] | None,
    attempted: int | None,
    stop_reason: str,
    investigator: Any | None,
    episode_class: str,
    failure_stage: str | None = None,
) -> None:
    if result_collector is None:
        return
    action_types = result_collector.setdefault("fraudster_action_types", [])
    counts = {action_type: 0 for action_type in FRAUDSTER_ACTION_TYPES}
    missing_count = 0
    unrecognized_count = 0
    for action_type in action_types:
        if action_type is None:
            missing_count += 1
        elif action_type in counts:
            counts[action_type] += 1
        else:
            unrecognized_count += 1
    counts["missing_action_type_count"] = missing_count
    counts["unrecognized_action_type_count"] = unrecognized_count
    counts["successful_action_count"] = len(action_types)
    result_collector.update(
        {
            "final_state": final_state,
            "actions_attempted": attempted,
            "stop_reason": stop_reason,
            "episode_class": episode_class,
            "failure_stage": failure_stage,
            "fraudster_action_types": action_types,
            "fraudster_action_counts": counts,
            "investigator_evidence": (
                (investigator.evidence_summary()
                 if callable(getattr(investigator, "evidence_summary", None))
                 else investigator.fallback.evidence_summary()
                 if callable(getattr(getattr(investigator, "fallback", None), "evidence_summary", None))
                 else None)
            ),
        }
    )


def _record_successful_fraudster_action(
    result_collector: dict[str, Any] | None,
    action_response: Any,
) -> None:
    """Record the backend's persisted action type only after execute succeeds."""
    if result_collector is None:
        return
    action_type = (
        action_response.get("actionType")
        if isinstance(action_response, dict)
        else None
    )
    result_collector.setdefault("fraudster_action_types", []).append(
        action_type if isinstance(action_type, str) and action_type else None
    )


def _record_candidate_opportunity(
    result_collector: dict[str, Any] | None,
    investigator: Any,
    scenario_id: int,
    state: dict[str, Any],
) -> None:
    """Capture the exact legal flag choices immediately before a decision."""
    if result_collector is None:
        return
    opportunities = result_collector.setdefault("candidate_opportunities", [])
    record: dict[str, Any] = {
        "scenario_id": scenario_id,
        "decision_index": len(opportunities),
        "step": state.get("step"),
        "investigator_actions_remaining": state.get("investigatorActionsRemaining"),
        "candidate_company_ids": None,
    }
    legal_actions = getattr(investigator, "legal_actions", None)
    valid = callable(legal_actions)
    if valid:
        try:
            actions = legal_actions(state)
        except Exception:
            actions = None
            valid = False
        valid = isinstance(actions, list)
        if valid:
            candidate_ids: set[int] = set()
            for action in actions:
                if not isinstance(action, dict) or not isinstance(action.get("action_type"), str):
                    valid = False
                    break
                if action["action_type"] != "FLAG_COMPANY":
                    continue
                company_id = action.get("company_id")
                if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
                    valid = False
                    break
                candidate_ids.add(company_id)
            if valid:
                record["candidate_company_ids"] = sorted(candidate_ids)

    opportunities.append(record)
    result_collector["candidate_opportunities_complete"] = (
        result_collector.get("candidate_opportunities_complete", True) and valid
    )


def run_episode(
    client: CatchMeIfYouCanApiClient,
    *,
    scenario_id: int | None = None,
    source_company_id: int | None = None,
    target_company_id: int | None = None,
    amount: str | None = None,
    max_actions: int = 20,
    result_collector: dict[str, Any] | None = None,
    fraudster_policy: Any | None = None,
    investigator_policy: Any | None = None,
    event_callback: Any | None = None,
    pause_before_fraudster: Any | None = None,
    human_controlled_fraudster: bool = False,
    private_shell_knowledge_provider: Any | None = None,
) -> dict[str, Any]:
    if result_collector is not None:
        result_collector.clear()
        result_collector.update(
            {
                "scenario_id": scenario_id,
                "initial_source_company_id": None,
                "initial_target_company_id": None,
                "final_state": None,
                "actions_attempted": None,
                "stop_reason": None,
                "episode_class": None,
                "failure_stage": None,
                "investigator_evidence": None,
                "candidate_opportunities": [],
                "candidate_opportunities_complete": True,
            }
        )
    if scenario_id is None:
        if source_company_id is None or target_company_id is None or amount is None:
            raise ValueError(
                "Provide scenario_id, or source_company_id, target_company_id, and amount."
            )
        created = client.create_scenario(
            source_company_id=source_company_id,
            target_company_id=target_company_id,
            amount=amount,
        )
        scenario_id = created["id"]
        if result_collector is not None:
            result_collector["scenario_id"] = scenario_id

    try:
        state = client.get_scenario(scenario_id)
    except CatchMeIfYouCanApiError:
        _update_episode_result(
            result_collector,
            final_state=None,
            attempted=0,
            stop_reason="initial_state_failed",
            investigator=None,
            episode_class="failed",
            failure_stage="initial_state",
        )
        raise
    try:
        state_status = validate_scenario_status(state)
    except RuntimeError as error:
        _update_episode_result(
            result_collector,
            final_state=state if isinstance(state, dict) else None,
            attempted=0,
            stop_reason="invalid scenario status",
            investigator=None,
            episode_class="failed",
            failure_stage="invalid_scenario_status",
        )
        raise
    if result_collector is not None:
        result_collector.update(
            {
                "scenario_id": scenario_id,
                "initial_source_company_id": (state.get("sourceCompany") or {}).get("id"),
                "initial_target_company_id": (state.get("targetCompany") or {}).get("id"),
            }
        )
    print(f"Initial scenario {scenario_id}: {_state_line(state)}")
    fraudster = fraudster_policy or FraudsterBot()
    investigator = investigator_policy or InvestigatorBot()
    attempted = 0
    previous_turn: str | None = None

    for _ in range(max_actions):
        if state_status in TERMINAL_STATUSES:
            _print_episode_summary(
                scenario_id, attempted, state, "scenario terminated", investigator
            )
            _update_episode_result(
                result_collector,
                final_state=state,
                attempted=attempted,
                stop_reason="scenario terminated",
                investigator=investigator,
                episode_class="completed",
            )
            return state

        if state.get("turn") == "FRAUDSTER" and callable(pause_before_fraudster):
            between_rounds = (previous_turn == "INVESTIGATOR"
                              and state.get("investigatorActionsRemaining") == 0)
            if human_controlled_fraudster or between_rounds:
                while True:
                    pause_before_fraudster(scenario_id, state)
                    if not human_controlled_fraudster:
                        break
                    state = client.get_scenario(scenario_id)
                    state_status = validate_scenario_status(state)
                    if state_status in TERMINAL_STATUSES or state.get("turn") != "FRAUDSTER":
                        break
                if state_status in TERMINAL_STATUSES:
                    _print_episode_summary(
                        scenario_id, attempted, state, "scenario terminated", investigator
                    )
                    _update_episode_result(
                        result_collector,
                        final_state=state,
                        attempted=attempted,
                        stop_reason="scenario terminated",
                        investigator=investigator,
                        episode_class="completed",
                    )
                    return state

        turn = state.get("turn")
        role = turn if turn in {"FRAUDSTER", "INVESTIGATOR"} else None
        try:
            if role is None:
                raise AgentObservationError(
                    f"Unknown backend turn: {turn!r}.")
            private_ids: Sequence[int] = ()
            if role == "FRAUDSTER" and callable(private_shell_knowledge_provider):
                try:
                    private_ids = private_shell_knowledge_provider(scenario_id)
                except Exception as error:
                    raise AgentObservationError(
                        "Unable to fetch authorized private shell knowledge."
                    ) from error
            decision_state = build_agent_observation(
                client, scenario_id, state, role=role,
                private_shell_company_ids=private_ids,
            )
        except AgentObservationError as error:
            _update_episode_result(
                result_collector,
                final_state=state,
                attempted=attempted,
                stop_reason="agent observation construction failed",
                investigator=investigator,
                episode_class="failed",
                failure_stage="agent_observation",
            )
            raise

        attempted += 1
        decision: dict[str, Any] | None = None
        investigator_response: dict[str, Any] | None = None
        try:
            if turn == "FRAUDSTER":
                decision = fraudster.choose_action(decision_state)
                if callable(event_callback):
                    try:
                        event_callback({"event_type": "action_started", "action_number": attempted, "agent": turn,
                                        "scenario_id": scenario_id, "action": decision, "state": decision_state})
                    except Exception:
                        pass
                print(f"Action #{attempted} before: turn={turn!r}, {_action_line(decision)}")
                action = client.create_fraudster_action(
                    scenario_id=scenario_id,
                    action_type=decision["action_type"],
                    source_position_id=decision["source_position_id"],
                    targets=decision["targets"],
                )
                client.execute_fraudster_action(action["id"])
                _record_successful_fraudster_action(result_collector, action)
            elif turn == "INVESTIGATOR":
                _record_candidate_opportunity(
                    result_collector, investigator, scenario_id, decision_state
                )
                decision = investigator.choose_action(decision_state)
                if callable(event_callback):
                    try:
                        event_callback({"event_type": "action_started", "action_number": attempted, "agent": turn,
                                        "scenario_id": scenario_id, "action": decision, "state": decision_state})
                    except Exception:
                        pass
                print(f"Action #{attempted} before: turn={turn!r}, {_action_line(decision)}")
                investigator_response = client.submit_investigator_action(
                    scenario_id=scenario_id,
                    action_type=decision["action_type"],
                    company_id=decision.get("company_id"),
                    transaction_id=decision.get("transaction_id"),
                )
            else:
                raise RuntimeError(f"Unknown backend turn: {state.get('turn')!r}")
        except (CatchMeIfYouCanApiError, RuntimeError) as error:
            # A rejected request does not imply a turn change. Re-read the
            # authoritative state and stop rather than fabricating progress.
            action_description = _action_line(decision) if decision is not None else "action selection unavailable"
            print(
                f"Action #{attempted} failed: turn={turn!r}, "
                f"{action_description}: {error}"
            )
            refreshed_after_failure = False
            try:
                state = client.get_scenario(scenario_id)
                state_status = validate_scenario_status(state)
                refreshed_after_failure = True
                print(f"State after failed action #{attempted}: {_state_line(state)}")
            except RuntimeError:
                _update_episode_result(
                    result_collector,
                    final_state=state if isinstance(state, dict) else None,
                    attempted=attempted,
                    stop_reason="invalid scenario status",
                    investigator=None,
                    episode_class="failed",
                    failure_stage="invalid_scenario_status",
                )
                raise
            except CatchMeIfYouCanApiError as state_error:
                print(f"Could not re-fetch state after failed action #{attempted}: {state_error}")
            _print_episode_summary(
                scenario_id, attempted, state, "action failed", investigator
            )
            _update_episode_result(
                result_collector,
                final_state=state if refreshed_after_failure else None,
                attempted=attempted,
                stop_reason="action failed",
                investigator=investigator if refreshed_after_failure else None,
                episode_class="failed",
                failure_stage=(
                    "action_submission_or_selection"
                    if refreshed_after_failure
                    else "post_failure_refresh"
                ),
            )
            return state

        # Both action responses and execution responses can differ in shape;
        # the scenario GET is the authoritative persisted state.
        try:
            state = client.get_scenario(scenario_id)
        except CatchMeIfYouCanApiError as error:
            print(f"Action #{attempted} could not be confirmed from persisted state: {error}")
            _print_episode_summary(
                scenario_id, attempted, state, "action failed", investigator
            )
            _update_episode_result(
                result_collector,
                final_state=None,
                attempted=attempted,
                stop_reason="authoritative_refresh_failed",
                investigator=None,
                episode_class="failed",
                failure_stage="authoritative_refresh",
            )
            return state
        try:
            state_status = validate_scenario_status(state)
        except RuntimeError:
            _update_episode_result(
                result_collector,
                final_state=state if isinstance(state, dict) else None,
                attempted=attempted,
                stop_reason="invalid scenario status",
                investigator=None,
                episode_class="failed",
                failure_stage="invalid_scenario_status",
            )
            raise
        if turn == "INVESTIGATOR" and decision is not None:
            sanitizer = getattr(investigator, "sanitize_action_response", None)
            if not callable(sanitizer):
                sanitizer = investigator.fallback.sanitize_action_response
            sanitized_response = sanitizer(
                investigator_response,
                scenario_id=scenario_id,
                expected_transaction_id=decision.get("transaction_id"),
            )
            investigator.mark_action_completed(decision, sanitized_response)
        if callable(event_callback) and decision is not None:
            try:
                progress_event = {
                    "event_type": "action",
                    "action_number": attempted,
                    "agent": turn,
                    "scenario_id": scenario_id,
                    "action": decision,
                    "state": state,
                    "evidence": sanitized_response if turn == "INVESTIGATOR" else None,
                }
                event_callback(progress_event)
            except Exception:
                # Progress reporting must not change authoritative simulation behavior.
                pass
        previous_turn = turn
        print(f"Action #{attempted} after: {_state_line(state)}")

        if state_status in TERMINAL_STATUSES:
            _print_episode_summary(
                scenario_id, attempted, state, "scenario terminated", investigator
            )
            _update_episode_result(
                result_collector,
                final_state=state,
                attempted=attempted,
                stop_reason="scenario terminated",
                investigator=investigator,
                episode_class="completed",
            )
            return state

    _print_episode_summary(
        scenario_id, attempted, state, "action limit reached", investigator
    )
    _update_episode_result(
        result_collector,
        final_state=state,
        attempted=attempted,
        stop_reason="action limit reached",
        investigator=investigator,
        episode_class="action_limit",
    )
    raise RuntimeError(f"Episode did not terminate within {max_actions} actions.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-id", type=int)
    parser.add_argument("--source-company-id", type=int)
    parser.add_argument("--target-company-id", type=int)
    parser.add_argument("--amount")
    parser.add_argument("--max-actions", type=int, default=20)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = run_episode(
        CatchMeIfYouCanApiClient(),
        scenario_id=args.scenario_id,
        source_company_id=args.source_company_id,
        target_company_id=args.target_company_id,
        amount=args.amount,
        max_actions=args.max_actions,
    )
    print(result)
