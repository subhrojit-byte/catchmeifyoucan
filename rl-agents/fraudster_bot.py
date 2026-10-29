"""Placeholder fraudster policy using only sanitized scenario state."""

from typing import Any
from decimal import Decimal, InvalidOperation


class FraudsterPolicyError(RuntimeError):
    pass


def heuristic_policy_configuration() -> dict[str, Any]:
    """Return the deterministic fraudster baseline rules; it has no tunables."""
    return {
        "source": "code rules in rl-agents/fraudster_bot.py",
        "parameters": [],
        "selection_rules": [
            "Requires an ACTIVE scenario on the FRAUDSTER turn.",
            "Selects the first position in scenario order with a position ID, positive balance, and company different from the target.",
            "Uses DIRECT_TRANSFER for that position; the backend selects its fixed destination.",
            "If no funded non-target source exists, uses WAIT with the first position that has an ID; errors if no position ID is exposed.",
            "Selection is deterministic and has no thresholds, weights, or random defaults.",
        ],
    }


class FraudsterBot:
    """A deliberately simple policy; this is not an RL agent."""

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") != "ACTIVE":
            raise FraudsterPolicyError("Scenario is not active.")
        if state.get("turn") != "FRAUDSTER":
            raise FraudsterPolicyError("It is not the fraudster turn.")

        positions = []
        target_id = (state.get("targetCompany") or {}).get("id")
        for position in state.get("positions", []):
            try:
                funded = Decimal(str(position.get("amount"))) > 0
            except (InvalidOperation, TypeError, ValueError):
                funded = False
            if (position.get("id") is not None and funded
                    and (position.get("company") or {}).get("id") != target_id):
                positions.append(position)
        if not positions:
            wait_position = next(
                (position for position in state.get("positions", [])
                 if position.get("id") is not None),
                None,
            )
            if wait_position is None:
                raise FraudsterPolicyError("No source position is exposed in scenario state.")
            return {
                "action_type": "WAIT",
                "source_position_id": wait_position["id"],
                "targets": [],
            }

        # DIRECT_TRANSFER has a fixed backend destination and needs no target
        # amount or destination in the request.
        return {
            "action_type": "DIRECT_TRANSFER",
            "source_position_id": positions[0]["id"],
            "targets": None,
        }
