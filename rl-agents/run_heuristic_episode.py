"""Run the existing heuristic policies on one existing scenario."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from .api_client import CatchMeIfYouCanApiClient
    from .fraudster_bot import FraudsterBot, heuristic_policy_configuration as fraudster_policy_configuration
    from .investigator_bot import InvestigatorBot, heuristic_policy_configuration
    from .run_episode import run_episode
except ImportError:  # Supports ``python run_heuristic_episode.py`` from rl-agents.
    from api_client import CatchMeIfYouCanApiClient
    from fraudster_bot import FraudsterBot, heuristic_policy_configuration as fraudster_policy_configuration
    from investigator_bot import InvestigatorBot, heuristic_policy_configuration
    from run_episode import run_episode


EVENT_PREFIX = "CATCHME_AGENT_EVENT "


def _emit_event(event: dict[str, Any]) -> None:
    """Emit the shared AgentRun event format without private context."""
    def public(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: public(item) for key, item in value.items()
                if key != "privateShellCompanyIds"
                and not any(secret in key.lower() for secret in ("credential", "authorization", "token"))
            }
        if isinstance(value, list):
            return [public(item) for item in value]
        return value

    print(EVENT_PREFIX + json.dumps(public(event), separators=(",", ":"), ensure_ascii=True), flush=True)


def run_heuristic_search(
    scenario_id: int,
    *,
    client: CatchMeIfYouCanApiClient | None = None,
    max_actions: int = 60,
) -> dict[str, Any]:
    """Execute the ordinary game loop with the existing heuristic bots."""
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, int) or scenario_id <= 0:
        raise ValueError("scenario_id must be a positive integer.")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer.")

    result: dict[str, Any] = {}
    _emit_event({
        "event_type": "heuristic_policy_metadata",
        "policies": [
            {"policy": "FraudsterBot", "configuration": fraudster_policy_configuration()},
            {"policy": "InvestigatorBot", "configuration": heuristic_policy_configuration()},
        ],
    })
    final_state = run_episode(
        client or CatchMeIfYouCanApiClient(),
        scenario_id=scenario_id,
        max_actions=max_actions,
        result_collector=result,
        fraudster_policy=FraudsterBot(),
        investigator_policy=InvestigatorBot(),
        event_callback=_emit_event,
    )
    _emit_event({
        "event_type": "episode_result",
        "scenario_id": scenario_id,
        "episode_class": result.get("episode_class"),
        "actions_attempted": result.get("actions_attempted"),
        "stop_reason": result.get("stop_reason"),
        "investigator_evidence": result.get("investigator_evidence"),
        "final_state": final_state,
    })
    return result


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True, type=_positive_int)
    parser.add_argument("--max-actions", type=_positive_int, default=60)
    args = parser.parse_args(argv)
    try:
        run_heuristic_search(args.scenario_id, max_actions=args.max_actions)
        return 0
    except Exception as error:
        _emit_event({
            "event_type": "runner_error",
            "scenario_id": args.scenario_id,
            "message": f"Heuristic Search failed ({error.__class__.__name__}).",
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
