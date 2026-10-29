import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from client import (
    FRAUDSTER_RUN_CREDENTIAL_ENV,
    FRAUDSTER_RUN_CREDENTIAL_HEADER,
    FRAUDSTER_RUN_ID_ENV,
    FRAUDSTER_RUN_ID_HEADER,
    CatchMeIfYouCanApiClient,
    CatchMeIfYouCanApiError,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._payload


class ClientScenarioHistoryTest(unittest.TestCase):
    def test_run_credential_is_consumed_and_sent_only_to_protected_probe(self):
        secret = "test-only-random-secret"
        run_id = "run-test-1"
        with patch.dict(os.environ, {
            FRAUDSTER_RUN_CREDENTIAL_ENV: secret,
            FRAUDSTER_RUN_ID_ENV: run_id,
        }):
            client = CatchMeIfYouCanApiClient(base_url="http://example.test")
            self.assertNotIn(FRAUDSTER_RUN_CREDENTIAL_ENV, os.environ)
            self.assertNotIn(secret, repr(client))
            self.assertTrue(client.has_fraudster_run_context)

            def open_probe(request, timeout):
                self.assertEqual(
                    "http://example.test/api/fraudster-private/8/authorization-probe",
                    request.full_url,
                )
                self.assertEqual(secret, request.get_header("X-fraudster-run-credential"))
                self.assertEqual(run_id, request.get_header("X-fraudster-run-id"))
                return FakeResponse(b'{"status":"authorized","privateShellCompanyIds":[21]}')

            with patch("client.urlopen", side_effect=open_probe):
                self.assertEqual({"status": "authorized", "privateShellCompanyIds": [21]},
                                 client.get_fraudster_authorization_probe(8))

            def open_public(request, timeout):
                self.assertIsNone(request.get_header("X-fraudster-run-credential"))
                self.assertIsNone(request.get_header("X-fraudster-run-id"))
                return FakeResponse(b'{"id":8}')

            with patch("client.urlopen", side_effect=open_public):
                self.assertEqual({"id": 8}, client.get_scenario(8))

    def test_probe_without_environment_credential_sends_no_credential(self):
        with patch.dict(os.environ, {}, clear=True):
            client = CatchMeIfYouCanApiClient(base_url="http://example.test")
        self.assertFalse(client.has_fraudster_run_context)

        def open_probe(request, timeout):
            self.assertIsNone(request.get_header("X-fraudster-run-credential"))
            self.assertIsNone(request.get_header("X-fraudster-run-id"))
            return FakeResponse(b'{"message":"Unauthorized."}')

        with patch("client.urlopen", side_effect=open_probe):
            self.assertEqual({"message": "Unauthorized."},
                             client.get_fraudster_authorization_probe(8))

    def test_get_scenario_transactions_uses_exact_get_url_and_returns_payload(self):
        payload = [{
            "id": 17,
            "origin": "BACKGROUND",
            "scenarioId": 8,
            "fraudActionId": None,
        }]

        def open_request(request, timeout):
            self.assertEqual("GET", request.get_method())
            self.assertEqual(
                "http://example.test/api/transactions/scenario/8",
                request.full_url,
            )
            self.assertEqual(3.5, timeout)
            return FakeResponse(json.dumps(payload).encode("utf-8"))

        with patch("client.urlopen", side_effect=open_request) as mocked:
            result = CatchMeIfYouCanApiClient(
                base_url="http://example.test", timeout=3.5
            ).get_scenario_transactions(8)

        self.assertEqual(payload, result)
        mocked.assert_called_once()

    def test_empty_scenario_history_is_returned_unchanged(self):
        with patch(
                "client.urlopen",
                return_value=FakeResponse(b"[]"),
        ):
            result = CatchMeIfYouCanApiClient(
                base_url="http://example.test"
            ).get_scenario_transactions(8)

        self.assertEqual([], result)

    def test_http_error_uses_existing_api_error_convention(self):
        error = HTTPError(
            "http://example.test/api/transactions/scenario/8",
            404,
            "not found",
            {},
            io.BytesIO(b'{"message":"Scenario not found."}'),
        )

        with patch("client.urlopen", side_effect=error):
            with self.assertRaises(CatchMeIfYouCanApiError) as raised:
                CatchMeIfYouCanApiClient(
                    base_url="http://example.test"
                ).get_scenario_transactions(8)

        self.assertEqual(404, raised.exception.status)
        self.assertEqual(
            {"message": "Scenario not found."}, raised.exception.body
        )

    def test_malformed_json_uses_existing_api_error_convention(self):
        with patch(
                "client.urlopen",
                return_value=FakeResponse(b"not-json"),
        ):
            with self.assertRaises(CatchMeIfYouCanApiError) as raised:
                CatchMeIfYouCanApiClient(
                    base_url="http://example.test"
                ).get_scenario_transactions(8)

        self.assertEqual(200, raised.exception.status)
        self.assertIn("non-JSON", str(raised.exception))

    def test_invalid_scenario_id_is_rejected_before_http_request(self):
        with patch("client.urlopen") as mocked:
            for scenario_id in (None, 0, -1, True, "8"):
                with self.subTest(scenario_id=scenario_id):
                    with self.assertRaises(ValueError):
                        CatchMeIfYouCanApiClient(
                            base_url="http://example.test"
                        ).get_scenario_transactions(scenario_id)

        mocked.assert_not_called()

    def test_no_global_transaction_endpoint_fallback_is_used(self):
        requested_paths = []

        def open_request(request, timeout):
            requested_paths.append(request.full_url)
            if request.full_url.endswith("/api/transactions"):
                self.fail("global transaction endpoint was used as a fallback")
            return FakeResponse(b"[]")

        with patch("client.urlopen", side_effect=open_request):
            result = CatchMeIfYouCanApiClient(
                base_url="http://example.test"
            ).get_scenario_transactions(8)

        self.assertEqual([], result)
        self.assertEqual(
            ["http://example.test/api/transactions/scenario/8"],
            requested_paths,
        )


if __name__ == "__main__":
    unittest.main()
