"""Unit tests for services/http_app/app.py — the container HTTP entry point.

Fully mocked: token verification and handler invocation are patched, so no JWKS,
no DB, no real service handlers are touched. These assert the app's own
responsibilities: public-vs-authenticated gating, 401/404 behaviour, and that the
API-Gateway-v2 event handed to handlers carries the verified claims.
"""

from unittest.mock import patch

import pytest

from services.http_app import app as http_app


@pytest.fixture
def client():
    http_app.app.config["TESTING"] = True
    return http_app.app.test_client()


def _ok_handler_response():
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": '{"ok":true}'}


class TestHealth:
    def test_health_is_unauthenticated_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


class TestAuthenticatedRoutes:
    def test_missing_token_returns_401(self, client):
        with patch.object(http_app, "build_authorizer_claims", return_value=None) as verify:
            resp = client.get("/v1/billing/disputes")
        assert resp.status_code == 401
        verify.assert_called_once()

    def test_valid_token_invokes_handler_with_claims(self, client):
        claims = {"sub": "u1", "custom:tenant_id": "t1", "cognito:groups": "t1:tenant_admin"}
        with (
            patch.object(http_app, "build_authorizer_claims", return_value=claims),
            patch.object(http_app, "invoke_handler", return_value=_ok_handler_response()) as invoke,
        ):
            resp = client.get("/v1/billing/disputes", headers={"Authorization": "Bearer good"})
        assert resp.status_code == 200
        event = invoke.call_args.args[1]
        assert event["requestContext"]["authorizer"]["claims"] == claims
        assert event["requestContext"]["http"]["method"] == "GET"

    def test_unrouted_path_with_valid_token_returns_404(self, client):
        claims = {"sub": "u1", "custom:tenant_id": "t1"}
        with (
            patch.object(http_app, "build_authorizer_claims", return_value=claims),
            patch.object(http_app, "invoke_handler") as invoke,
        ):
            resp = client.get("/v1/not-a-real-resource", headers={"Authorization": "Bearer good"})
        assert resp.status_code == 404
        invoke.assert_not_called()

    def test_handler_exception_returns_500(self, client):
        claims = {"sub": "u1", "custom:tenant_id": "t1"}
        with (
            patch.object(http_app, "build_authorizer_claims", return_value=claims),
            patch.object(http_app, "invoke_handler", side_effect=RuntimeError("boom")),
        ):
            resp = client.get("/v1/billing", headers={"Authorization": "Bearer good"})
        assert resp.status_code == 500


class TestPublicRoutes:
    def test_public_route_skips_auth_and_has_no_authorizer_context(self, client):
        with (
            patch.object(http_app, "build_authorizer_claims") as verify,
            patch.object(http_app, "invoke_handler", return_value=_ok_handler_response()) as invoke,
        ):
            resp = client.post("/v1/webhooks/payment", data="{}", content_type="application/json")
        assert resp.status_code == 200
        verify.assert_not_called()  # public routes never verify a token
        event = invoke.call_args.args[1]
        assert event["requestContext"]["authorizer"] == {}

    def test_public_tracking_lookup_skips_auth(self, client):
        with (
            patch.object(http_app, "build_authorizer_claims") as verify,
            patch.object(http_app, "invoke_handler", return_value=_ok_handler_response()),
        ):
            resp = client.get("/v1/shipments/TRACK123")
        assert resp.status_code == 200
        verify.assert_not_called()


class TestCors:
    def test_options_preflight_returns_204(self, client):
        resp = client.open("/v1/billing", method="OPTIONS")
        assert resp.status_code == 204
        assert "Access-Control-Allow-Methods" in resp.headers


class TestFrontDoor:
    """The Azure edge: the client address comes from our Front Door's stamp, and the optional origin lock."""

    FDID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"

    @staticmethod
    def _call(client, headers):
        seen = {}

        def handler(event, _context):
            seen["event"] = event
            return _ok_handler_response()

        with (
            patch.object(http_app, "build_authorizer_claims", return_value={"sub": "u1"}),
            patch.object(http_app, "invoke_handler", side_effect=lambda name, event: handler(event, None)),
        ):
            resp = client.get("/v1/billing/disputes", headers={"Authorization": "Bearer good", **headers})
        return resp, seen.get("event")

    def test_the_handler_sees_the_address_front_door_recorded(self, client, monkeypatch):
        monkeypatch.setenv("AZURE_FRONT_DOOR_ID", self.FDID)
        resp, event = self._call(
            client, {"X-Azure-FDID": self.FDID, "X-Azure-SocketIP": "41.58.10.20", "X-Forwarded-For": "6.6.6.6"}
        )
        assert resp.status_code == 200
        assert event["requestContext"]["http"]["sourceIp"] == "41.58.10.20"
        assert event["requestContext"]["identity"]["sourceIp"] == "41.58.10.20"

    def test_a_request_around_front_door_is_served_but_has_no_address(self, client, monkeypatch):
        monkeypatch.setenv("AZURE_FRONT_DOOR_ID", self.FDID)
        resp, event = self._call(client, {"X-Azure-SocketIP": "6.6.6.6", "X-Forwarded-For": "6.6.6.6"})
        assert resp.status_code == 200
        assert "sourceIp" not in event["requestContext"]["http"]

    def test_with_the_lock_on_a_request_around_front_door_is_refused_before_any_handler(self, client, monkeypatch):
        monkeypatch.setenv("AZURE_FRONT_DOOR_ID", self.FDID)
        monkeypatch.setenv("REQUIRE_FRONT_DOOR", "true")
        resp, event = self._call(client, {"X-Azure-FDID": "someone-elses-front-door"})
        assert resp.status_code == 403 and event is None

    def test_with_the_lock_on_front_door_traffic_still_passes(self, client, monkeypatch):
        monkeypatch.setenv("AZURE_FRONT_DOOR_ID", self.FDID)
        monkeypatch.setenv("REQUIRE_FRONT_DOOR", "true")
        resp, _ = self._call(client, {"X-Azure-FDID": self.FDID, "X-Azure-SocketIP": "41.58.10.20"})
        assert resp.status_code == 200

    def test_the_health_probe_is_never_locked_out(self, client, monkeypatch):
        """The platform probes the container directly, not through Front Door."""
        monkeypatch.setenv("AZURE_FRONT_DOOR_ID", self.FDID)
        monkeypatch.setenv("REQUIRE_FRONT_DOOR", "true")
        assert client.get("/health").status_code == 200
