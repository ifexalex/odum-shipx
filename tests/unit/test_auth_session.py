"""Unit tests for services/auth — the httpOnly-cookie session-persistence flow.

Covers: refresh-token exchange against Cognito (services/auth/cognito_refresh.py)
and the Lambda handler's cookie handling (services/auth/handler.py). See
docs/project docs/frontend/04_auth_and_session.md for the flow this closes —
a page reload wiping the in-memory-only ID token used to force a full re-login.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from services.auth import cognito_refresh, handler
from shared.exceptions import AuthenticationRequiredError, ExternalServiceError

REFRESH_TOKEN = "a-valid-looking-refresh-token-value"  # noqa: S105 — test fixture, not a real credential


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "InitiateAuth")


# ---------------------------------------------------------------------------
# cognito_refresh.refresh_id_token
# ---------------------------------------------------------------------------


class TestRefreshIdToken:
    def test_success_returns_tokens(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        mock_client.initiate_auth.return_value = {
            "AuthenticationResult": {
                "IdToken": "id.tok.en",
                "AccessToken": "acc.tok.en",
                "ExpiresIn": 3600,
            }
        }
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            result = cognito_refresh.refresh_id_token(REFRESH_TOKEN)

        assert result == {"id_token": "id.tok.en", "access_token": "acc.tok.en", "expires_in": 3600}
        mock_client.initiate_auth.assert_called_once_with(
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": REFRESH_TOKEN},
            ClientId="client-123",
        )

    def test_expired_or_revoked_token_raises_authentication_required(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        mock_client.initiate_auth.side_effect = _client_error("NotAuthorizedException")
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            with pytest.raises(AuthenticationRequiredError):
                cognito_refresh.refresh_id_token(REFRESH_TOKEN)

    def test_deleted_user_raises_authentication_required(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        mock_client.initiate_auth.side_effect = _client_error("UserNotFoundException")
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            with pytest.raises(AuthenticationRequiredError):
                cognito_refresh.refresh_id_token(REFRESH_TOKEN)

    def test_other_cognito_failure_raises_external_service_error(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        mock_client.initiate_auth.side_effect = _client_error("InternalErrorException")
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            with pytest.raises(ExternalServiceError):
                cognito_refresh.refresh_id_token(REFRESH_TOKEN)


# ---------------------------------------------------------------------------
# cognito_refresh.revoke_refresh_token
# ---------------------------------------------------------------------------


class TestRevokeRefreshToken:
    def test_success_calls_revoke_token(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            cognito_refresh.revoke_refresh_token(REFRESH_TOKEN)
        mock_client.revoke_token.assert_called_once_with(Token=REFRESH_TOKEN, ClientId="client-123")

    def test_failure_is_swallowed_not_raised(self, monkeypatch):
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
        mock_client = MagicMock()
        mock_client.revoke_token.side_effect = _client_error("TooManyRequestsException")
        with patch("services.auth.cognito_refresh._cognito_client", return_value=mock_client):
            cognito_refresh.revoke_refresh_token(REFRESH_TOKEN)  # must not raise


# ---------------------------------------------------------------------------
# handler — POST /v1/auth/session
# ---------------------------------------------------------------------------


def _event(method: str, path: str, body: dict | None = None, cookies: list[str] | None = None) -> dict:
    event = {
        "requestContext": {"requestId": "req-1", "http": {"method": method, "path": path}},
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if cookies is not None:
        event["cookies"] = cookies
    return event


class TestEstablishSession:
    def test_valid_refresh_token_sets_httponly_cookie(self):
        event = _event("POST", "/v1/auth/session", body={"refresh_token": REFRESH_TOKEN})
        resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 204
        (cookie,) = resp["cookies"]
        assert cookie.startswith(f"shipx_rt={REFRESH_TOKEN}")
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=Strict" in cookie
        assert "Path=/v1/auth" in cookie

    def test_missing_refresh_token_returns_422(self):
        event = _event("POST", "/v1/auth/session", body={})
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 422
        assert "cookies" not in resp

    def test_short_refresh_token_returns_422(self):
        event = _event("POST", "/v1/auth/session", body={"refresh_token": "short"})
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 422


# ---------------------------------------------------------------------------
# handler — POST /v1/auth/refresh
# ---------------------------------------------------------------------------


class TestRefreshRoute:
    def test_valid_cookie_returns_fresh_id_token(self):
        event = _event("POST", "/v1/auth/refresh", cookies=[f"shipx_rt={REFRESH_TOKEN}"])
        with patch(
            "services.auth.cognito_refresh.refresh_id_token",
            return_value={"id_token": "fresh.id.token", "access_token": "x", "expires_in": 3600},
        ) as mock_refresh:
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["data"]["id_token"] == "fresh.id.token"  # noqa: S105 — test fixture, not a real credential
        assert body["data"]["expires_in"] == 3600
        mock_refresh.assert_called_once_with(REFRESH_TOKEN)

    def test_missing_cookie_returns_401(self):
        event = _event("POST", "/v1/auth/refresh", cookies=[])
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_no_cookies_key_at_all_returns_401(self):
        event = _event("POST", "/v1/auth/refresh")
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_ignores_unrelated_cookies(self):
        event = _event("POST", "/v1/auth/refresh", cookies=["other_cookie=abc"])
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 401

    def test_expired_refresh_token_propagates_401(self):
        event = _event("POST", "/v1/auth/refresh", cookies=[f"shipx_rt={REFRESH_TOKEN}"])
        with patch(
            "services.auth.cognito_refresh.refresh_id_token",
            side_effect=AuthenticationRequiredError(),
        ):
            resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 401


# ---------------------------------------------------------------------------
# handler — POST /v1/auth/logout
# ---------------------------------------------------------------------------


class TestLogoutRoute:
    def test_revokes_token_and_clears_cookie(self):
        event = _event("POST", "/v1/auth/logout", cookies=[f"shipx_rt={REFRESH_TOKEN}"])
        with patch("services.auth.cognito_refresh.revoke_refresh_token") as mock_revoke:
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 204
        (cookie,) = resp["cookies"]
        assert cookie.startswith("shipx_rt=;")
        assert "Max-Age=0" in cookie
        mock_revoke.assert_called_once_with(REFRESH_TOKEN)

    def test_no_cookie_still_clears_and_skips_revoke_call(self):
        event = _event("POST", "/v1/auth/logout", cookies=[])
        with patch("services.auth.cognito_refresh.revoke_refresh_token") as mock_revoke:
            resp = handler.lambda_handler(event, None)

        assert resp["statusCode"] == 204
        mock_revoke.assert_not_called()


# ---------------------------------------------------------------------------
# handler — routing
# ---------------------------------------------------------------------------


class TestRouting:
    def test_unknown_route_returns_404(self):
        event = _event("GET", "/v1/auth/nonsense")
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 404

    def test_response_never_leaks_cache(self):
        event = _event("POST", "/v1/auth/session", body={"refresh_token": REFRESH_TOKEN})
        resp = handler.lambda_handler(event, None)
        assert resp["headers"]["Cache-Control"] == "no-store"
