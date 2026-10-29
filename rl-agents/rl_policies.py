"""RL adapters that preserve the existing bot action contracts."""

from __future__ import annotations

import random
from typing import Any

from fraudster_bot import FraudsterBot
from investigator_bot import InvestigatorBot, InvestigatorPolicyError
from q_learning import QLearningAgent, ensure_policy_compatibility
from state_abstraction import (
    fraudster_state_key,
    investigator_state_key,
    legal_fraudster_actions,
    legal_investigator_actions,
    public_company_evidence_profile,
    validated_transaction_ids,
)


class RLFraudsterPolicy:
    def __init__(self, learner: QLearningAgent, fallback: FraudsterBot | None = None):
        ensure_policy_compatibility(learner, "fraudster")
        self.learner = learner
        self.fallback = fallback or FraudsterBot()

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        actions = legal_fraudster_actions(state)
        if not actions:
            return self.fallback.choose_action(state)
        return self.learner.select_action(fraudster_state_key(state), actions)


class RandomFraudsterPolicy:
    """Uniformly select from the currently legal fraudster actions."""

    def __init__(self, seed: int = 0):
        self._random = random.Random(seed)

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        actions = legal_fraudster_actions(state)
        if not actions:
            raise ValueError("No legal fraudster action is available.")
        return self._random.choice(actions)


class RLInvestigatorPolicy:
    def __init__(self, learner: QLearningAgent, fallback: InvestigatorBot | None = None):
        ensure_policy_compatibility(learner, "investigator")
        self.learner = learner
        self.fallback = fallback or InvestigatorBot()
        self._completed_actions: set[tuple[str, int]] = set()
        self._flagged_company_ids: set[int] = set()
        self._trace_transaction_ids: set[int] = set()
        self._discovered_company_ids: set[int] = set()
        self._observed_company_ids: set[int] = set()
        self._discovered_director_ids: set[int] = set()
        self._director_relationships: set[tuple[int, int]] = set()
        self._company_public_evidence: dict[int, dict[str, Any]] = {}
        self.last_decision_diagnostics: dict[str, Any] | None = None

    @property
    def completed_actions(self) -> set[tuple[str, int]]:
        return set(self._completed_actions)

    def legal_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        candidate_company_ids = self._candidate_company_ids(state)
        observed_company_ids = self._observed_company_ids_for_state(state)
        trace_transaction_ids = self._history_transaction_ids(state)
        return legal_investigator_actions(
            state,
            completed_actions=self._completed_actions,
            trace_transaction_ids=trace_transaction_ids,
            candidate_company_ids=sorted(candidate_company_ids),
            observed_company_ids=observed_company_ids,
        )

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        actions = self.legal_actions(state)
        self._remember_state_company_evidence(state)
        candidate_company_ids = self._candidate_company_ids(state)
        observed_company_ids = self._observed_company_ids_for_state(state)
        trace_transaction_ids = self._history_transaction_ids(state)
        if not actions:
            fallback_action = self.fallback.choose_action(state)
            if fallback_action not in legal_investigator_actions(
                    state,
                    completed_actions=self._completed_actions,
                    trace_transaction_ids=trace_transaction_ids,
                    candidate_company_ids=sorted(candidate_company_ids),
                    observed_company_ids=observed_company_ids):
                raise InvestigatorPolicyError(
                    "Fallback investigator action is not legal for confirmed scenario evidence."
                )
            self.last_decision_diagnostics = {
                "chosen_action_type": fallback_action.get("action_type"),
                "selection_mode": "validated_fallback",
                "tie_breaking": "not_applicable",
                "max_q_indices": [],
                "legal_alternatives": [],
            }
            return fallback_action
        key = investigator_state_key(
            state,
            investigated_company_ids={company_id for action_type, company_id in self._completed_actions
                                      if action_type in {"OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS"}},
            flagged_company_ids=self._flagged_company_ids,
            trace_transaction_ids=self._trace_transaction_ids,
            candidate_company_ids=candidate_company_ids,
            observed_company_ids=observed_company_ids,
            discovered_director_ids=self._discovered_director_ids,
            director_relationships=self._director_relationships,
            company_evidence_by_id=self._company_public_evidence,
        )
        learned_actions = [self.learning_action(state, action) for action in actions]
        selector = getattr(self.learner, "select_action_with_diagnostics", None)
        if callable(selector):
            _, selection = selector(key, learned_actions)
        else:
            selected = self.learner.select_action(key, learned_actions)
            selection = {
                "q_values": [], "selected_index": next(
                    (index for index, candidate in enumerate(learned_actions)
                     if candidate == selected), 0
                ),
                "max_q_indices": [], "selection_mode": "unspecified",
                "tie_breaking": "unavailable",
            }
        selected_index = selection["selected_index"]
        chosen = actions[selected_index]
        alternatives = []
        for index, learned_action in enumerate(learned_actions):
            alternative = {
                "action_type": learned_action.get("action_type"),
                "q_value": (selection["q_values"][index]
                            if index < len(selection["q_values"]) else None),
                "selected": index == selected_index,
            }
            features = learned_action.get("candidate_features")
            if features is not None:
                alternative["candidate_features"] = features
            alternatives.append(alternative)
        self.last_decision_diagnostics = {
            "chosen_action_type": chosen.get("action_type"),
            "selection_mode": selection["selection_mode"],
            "tie_breaking": selection["tie_breaking"],
            "max_q_indices": list(selection["max_q_indices"]),
            "legal_alternatives": alternatives,
        }
        return chosen

    def learning_action(self, state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Canonical Q action that generalizes company decisions across IDs."""
        self._remember_state_company_evidence(state)
        action_type = action.get("action_type")
        company_id = self._valid_id(action.get("company_id"))
        if company_id is not None:
            return {
                "action_type": action_type,
                "candidate_features": self._candidate_action_features(state, company_id),
            }
        # Transaction IDs identify public, validated trace choices; they are not
        # company identity features and remain part of the trace action.
        if action_type == "TRACE_TRANSACTION":
            return {"action_type": action_type, "transaction_id": action.get("transaction_id")}
        return {"action_type": action_type}

    def learning_actions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [self.learning_action(state, action) for action in self.legal_actions(state)]

    def mark_action_completed(self, decision: dict[str, Any], response: dict[str, Any] | None = None) -> None:
        action_type = decision.get("action_type")
        identifier = self._valid_id(
            decision.get("company_id", decision.get("transaction_id"))
        )
        if identifier is None:
            return
        self._completed_actions.add((action_type, identifier))
        if isinstance(response, dict):
            self._remember_response_company_evidence(response)
        if action_type == "FLAG_COMPANY":
            self._flagged_company_ids.add(identifier)
        elif action_type in {"OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS"}:
            self._observed_company_ids.add(identifier)
            self._discovered_company_ids.add(identifier)
            investigation = (response or {}).get("directorInvestigation") or {}
            for director in investigation.get("directors") or []:
                if not isinstance(director, dict):
                    continue
                director_id = self._valid_id(director.get("directorId"))
                if director_id is not None:
                    self._discovered_director_ids.add(director_id)
                for company in director.get("associatedCompanies") or []:
                    if isinstance(company, dict):
                        company_id = self._valid_id(company.get("id"))
                        if company_id is not None:
                            self._discovered_company_ids.add(company_id)
                            self._observed_company_ids.add(company_id)
                            if director_id is not None:
                                self._director_relationships.add((director_id, company_id))
        elif action_type == "TRACE_TRANSACTION":
            self._trace_transaction_ids.add(identifier)
            transaction = (response or {}).get("transactionTrace") or {}
            if isinstance(transaction, dict) and self._valid_id(transaction.get("id")) == identifier:
                for field in ("sourceCompany", "destinationCompany"):
                    company = transaction.get(field)
                    if isinstance(company, dict):
                        company_id = self._valid_id(company.get("id"))
                        if company_id is not None:
                            self._discovered_company_ids.add(company_id)
                            self._observed_company_ids.add(company_id)

        # The response is deliberately passed only to the baseline fallback.
        if action_type != "FLAG_COMPANY":
            self.fallback.mark_action_completed(decision, response)

    def state_key(self, state: dict[str, Any]) -> tuple[Any, ...]:
        self._remember_state_company_evidence(state)
        return investigator_state_key(
            state,
            investigated_company_ids={company_id for action_type, company_id in self._completed_actions
                                      if action_type in {"OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS"}},
            flagged_company_ids=self._flagged_company_ids,
            trace_transaction_ids=self._trace_transaction_ids,
            candidate_company_ids=self._candidate_company_ids(state),
            observed_company_ids=self._observed_company_ids_for_state(state),
            discovered_director_ids=self._discovered_director_ids,
            director_relationships=self._director_relationships,
            company_evidence_by_id=self._company_public_evidence,
        )

    def _candidate_action_features(self, state: dict[str, Any], company_id: int) -> tuple[Any, ...]:
        company = self._company_public_evidence.get(company_id)
        profile = public_company_evidence_profile(company)
        relationships = min(sum(1 for _, linked_id in self._director_relationships
                               if linked_id == company_id), 4)
        observed = company_id in self._observed_company_ids_for_state(state)
        investigated = any(
            action_type in {"OBSERVE_COMPANY", "INVESTIGATE_DIRECTORS"}
            and completed_id == company_id
            for action_type, completed_id in self._completed_actions
        )
        flagged = company_id in self._flagged_company_ids
        return (*profile, int(observed), int(investigated), int(flagged), relationships)

    def _remember_state_company_evidence(self, state: dict[str, Any]) -> None:
        for company in (state.get("sourceCompany") or {}, state.get("targetCompany") or {}):
            self._remember_company(company)
        for position in state.get("positions") or []:
            if isinstance(position, dict):
                self._remember_company(position.get("company"))

    def _remember_response_company_evidence(self, response: dict[str, Any]) -> None:
        self._remember_company(response.get("observation"))
        trace = response.get("transactionTrace")
        if isinstance(trace, dict):
            self._remember_company(trace.get("sourceCompany"))
            self._remember_company(trace.get("destinationCompany"))
        investigation = response.get("directorInvestigation")
        if not isinstance(investigation, dict):
            return
        self._remember_company(investigation.get("company"))
        for director in investigation.get("directors") or []:
            if not isinstance(director, dict):
                continue
            for company in director.get("associatedCompanies") or []:
                self._remember_company(company)

    def _remember_company(self, company: Any) -> None:
        if not isinstance(company, dict):
            return
        company_id = self._valid_id(company.get("id"))
        if company_id is None:
            return
        # Copy only fields already allowed in public company observations.
        public_fields = (
            "id", "ageInYears", "numberOfEmployees", "annualRevenue", "address"
        )
        self._company_public_evidence[company_id] = {
            field: company[field] for field in public_fields if field in company
        }

    def _candidate_company_ids(self, state: dict[str, Any]) -> set[int]:
        candidates: set[int] = set(self._discovered_company_ids)
        for company in (
                state.get("sourceCompany") or {},
                state.get("targetCompany") or {}):
            company_id = self._valid_id(company.get("id"))
            if company_id is not None:
                candidates.add(company_id)
        for position in state.get("positions") or []:
            company_id = self._valid_id((position.get("company") or {}).get("id"))
            if company_id is not None:
                candidates.add(company_id)
        return candidates

    def _observed_company_ids_for_state(self, state: dict[str, Any]) -> set[int]:
        observed = set(self._observed_company_ids)
        observed.update(self._candidate_company_ids(state))
        return observed

    def _history_transaction_ids(self, state: dict[str, Any]) -> list[int]:
        return validated_transaction_ids(state)

    @staticmethod
    def _valid_id(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value


class RandomInvestigatorPolicy(RLInvestigatorPolicy):
    """Uniformly select from the policy's confirmed legal investigator actions."""

    def __init__(self, seed: int = 0, fallback: InvestigatorBot | None = None):
        super().__init__(QLearningAgent(epsilon=0, seed=seed), fallback=fallback)
        self._random = random.Random(seed)

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        actions = self.legal_actions(state)
        if not actions:
            raise InvestigatorPolicyError("No legal investigator action is available.")
        return self._random.choice(actions)

