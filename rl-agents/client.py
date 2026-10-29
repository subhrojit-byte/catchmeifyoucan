"""Small standard-library client for the verified CatchMeIfYouCan REST API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:8080"
BASE_URL_ENV = "CATCHMEIFYOUCAN_BASE_URL"
FRAUDSTER_RUN_CREDENTIAL_ENV = "CATCHME_FRAUDSTER_RUN_CREDENTIAL"
FRAUDSTER_RUN_CREDENTIAL_HEADER = "X-Fraudster-Run-Credential"
FRAUDSTER_RUN_ID_ENV = "CATCHME_FRAUDSTER_RUN_ID"
FRAUDSTER_RUN_ID_HEADER = "X-Fraudster-Run-ID"


class CatchMeIfYouCanApiError(RuntimeError):
    """Raised when the backend returns an HTTP error or invalid JSON."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class CatchMeIfYouCanApiClient:
    """Client for the currently implemented scenario/action endpoints."""

    base_url: str | None = None
    timeout: float = 10.0
    _fraudster_run_credential: str | None = field(default=None, init=False, repr=False, compare=False)
    _fraudster_run_id: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        configured = self.base_url or os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL)
        object.__setattr__(self, "base_url", configured.rstrip("/"))
        # Consume the child-process secret once so unrelated Python code cannot
        # retrieve it from the environment after API-client construction.
        credential = os.environ.pop(FRAUDSTER_RUN_CREDENTIAL_ENV, None)
        object.__setattr__(self, "_fraudster_run_credential", credential)
        run_id = os.environ.pop(FRAUDSTER_RUN_ID_ENV, None)
        object.__setattr__(self, "_fraudster_run_id", run_id)

    def get_fraudster_authorization_probe(self, scenario_id: int) -> Any:
        """Call the harmless, run-authorized probe without adding credentials to other requests."""
        if (isinstance(scenario_id, bool)
                or not isinstance(scenario_id, int)
                or scenario_id <= 0):
            raise ValueError("scenario_id must be a positive integer.")
        return self._request(
            "GET",
            f"/api/fraudster-private/{scenario_id}/authorization-probe",
            fraudster_credential=self._fraudster_run_credential,
            fraudster_run_id=self._fraudster_run_id,
        )

    def start_agent_run(self, scenario_id: int) -> Any:
        """Start the established managed inference lifecycle for one scenario."""
        return self._request("POST", "/api/agent-runs", {"scenarioId": scenario_id, "mode": "INFERENCE"})

    def get_agent_run(self, run_id: str) -> Any:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string.")
        return self._request("GET", f"/api/agent-runs/{run_id}")

    def cancel_agent_run(self, run_id: str) -> Any:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string.")
        return self._request("POST", f"/api/agent-runs/{run_id}/cancel")

    def continue_agent_run(self, run_id: str) -> Any:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string.")
        return self._request("POST", f"/api/agent-runs/{run_id}/continue")

    @property
    def has_fraudster_run_context(self) -> bool:
        """Expose only whether this client consumed a complete run grant, never its secret."""
        return bool(self._fraudster_run_credential and self._fraudster_run_id)

    def create_scenario(
        self,
        *,
        source_company_id: int,
        target_company_id: int,
        amount: str | int | float,
    ) -> Any:
        """POST /api/fraud/scenarios."""
        return self._request(
            "POST",
            "/api/fraud/scenarios",
            {
                "sourceCompanyId": source_company_id,
                "targetCompanyId": target_company_id,
                "amount": amount,
            },
        )

    def get_scenario(self, scenario_id: int) -> Any:
        """GET /api/fraud/scenarios/{scenarioId}."""
        return self._request("GET", f"/api/fraud/scenarios/{scenario_id}")

    def get_scenario_transactions(self, scenario_id: int) -> Any:
        """GET /api/transactions/scenario/{scenarioId}."""
        if (isinstance(scenario_id, bool)
                or not isinstance(scenario_id, int)
                or scenario_id <= 0):
            raise ValueError("scenario_id must be a positive integer.")
        return self._request(
            "GET", f"/api/transactions/scenario/{scenario_id}"
        )

    def get_eligible_intermediate_companies(self, company_id: int) -> Any:
        """GET backend director-linked intermediary IDs for a source company."""
        if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
            raise ValueError("company_id must be a positive integer.")
        return self._request("GET", f"/api/company-directors/eligible/{company_id}")

    def get_company(self, company_id: int) -> Any:
        """GET public company characteristics for a validated candidate ID."""
        if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
            raise ValueError("company_id must be a positive integer.")
        return self._request("GET", f"/api/companies/{company_id}")

    def create_fraudster_action(
        self,
        *,
        scenario_id: int,
        action_type: str,
        source_position_id: int,
        targets: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any:
        """POST /api/fraud/actions.

        Each target uses the verified backend fields ``destinationCompanyId``
        and ``amount``. DIRECT_TRANSFER may omit targets; ROUTE_TRANSFER,
        SPLIT_TRANSFER, and WAIT are validated by the backend.
        """
        payload: dict[str, Any] = {
            "scenarioId": scenario_id,
            "actionType": action_type,
            "sourcePositionId": source_position_id,
        }
        if targets is not None:
            payload["targets"] = [dict(target) for target in targets]
        return self._request("POST", "/api/fraud/actions", payload)

    def execute_fraudster_action(self, action_id: int) -> Any:
        """POST /api/fraud/actions/{actionId}/execute."""
        return self._request("POST", f"/api/fraud/actions/{action_id}/execute")

    def submit_investigator_action(
        self,
        *,
        scenario_id: int,
        action_type: str,
        company_id: int | None = None,
        transaction_id: int | None = None,
    ) -> Any:
        """POST /api/investigator/actions."""
        payload: dict[str, Any] = {
            "scenarioId": scenario_id,
            "actionType": action_type,
        }
        if company_id is not None:
            payload["companyId"] = company_id
        if transaction_id is not None:
            payload["transactionId"] = transaction_id
        return self._request("POST", "/api/investigator/actions", payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        fraudster_credential: str | None = None,
        fraudster_run_id: str | None = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if fraudster_credential:
            headers[FRAUDSTER_RUN_CREDENTIAL_HEADER] = fraudster_credential
        if fraudster_run_id:
            headers[FRAUDSTER_RUN_ID_HEADER] = fraudster_run_id
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return self._decode_json(raw, response.status)
        except HTTPError as error:
            raw = error.read()
            try:
                error_body = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                error_body = raw.decode("utf-8", errors="replace")
            raise CatchMeIfYouCanApiError(
                f"HTTP {error.code} from {method} {path}: {error_body}",
                status=error.code,
                body=error_body,
            ) from error
        except URLError as error:
            raise CatchMeIfYouCanApiError(
                f"Could not reach CatchMeIfYouCan backend at {self.base_url}: {error.reason}"
            ) from error
        except TimeoutError as error:
            raise CatchMeIfYouCanApiError(
                f"Timed out contacting CatchMeIfYouCan backend at {self.base_url}"
            ) from error

    @staticmethod
    def _decode_json(raw: bytes, status: int) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CatchMeIfYouCanApiError(
                f"HTTP {status} returned a non-JSON response", status=status
            ) from error


__all__ = ["CatchMeIfYouCanApiClient", "CatchMeIfYouCanApiError"]
