"""Unit tests for services/auth/entra_refresh.py and the handler's provider
selection. Fully mocked — no network, no Entra tenant."""

import io
import json
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

import shared.providers as providers
from services.auth import entra_refresh, handler
from shared.exceptions import AuthenticationRequiredError, ExternalServiceError

_REFRESH = "x" * 40


def _event(cookies: list[str]) -> dict:
    return {
        "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/refresh"}},
        "cookies": cookies,
        "body": "",
    }


def _urlopen_returning(payload: dict):
    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    cm.__exit__.return_value = False
    return cm


class TestEntraRefresh:
    def setup_method(self):
        self._env = patch.dict(
            "os.environ",
            {"ENTRA_TOKEN_ENDPOINT": "https://t.ciamlogin.com/t/oauth2/v2.0/token", "ENTRA_CLIENT_ID": "c1"},
        )
        self._env.start()

    def teardown_method(self):
        self._env.stop()

    def test_refresh_success_maps_tokens(self):
        payload = {"id_token": "id.jwt", "access_token": "acc", "expires_in": 3600}
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(payload)):
            result = entra_refresh.refresh_id_token(_REFRESH)
        assert result == {"id_token": "id.jwt", "access_token": "acc", "expires_in": 3600}

    def test_invalid_grant_raises_authentication_required(self):
        err = urllib.error.HTTPError(url="https://t", code=400, msg="bad", hdrs=None, fp=io.BytesIO(b'{"error":"invalid_grant"}'))
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(AuthenticationRequiredError):
                entra_refresh.refresh_id_token(_REFRESH)

    def test_missing_config_raises_external_service_error(self):
        with patch.dict("os.environ", {"ENTRA_TOKEN_ENDPOINT": "", "ENTRA_CLIENT_ID": ""}):
            with pytest.raises(ExternalServiceError):
                entra_refresh.refresh_id_token(_REFRESH)

    def test_revoke_is_noop(self):
        entra_refresh.revoke_refresh_token(_REFRESH)  # must not raise


class TestEntraPasswordGrant:
    """ROPC login proxy — the server-side half of EntraClient.signIn."""

    def setup_method(self):
        self._env = patch.dict(
            "os.environ",
            {
                "ENTRA_TOKEN_ENDPOINT": "https://t.ciamlogin.com/t/oauth2/v2.0/token",
                "ENTRA_CLIENT_ID": "c1",
                "ENTRA_USER_DOMAIN": "tenant.onmicrosoft.com",
            },
        )
        self._env.start()

    def teardown_method(self):
        self._env.stop()

    def test_password_grant_success_maps_tokens(self):
        payload = {"id_token": "id.jwt", "access_token": "acc", "refresh_token": "ref", "expires_in": 3600}
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(payload)):
            result = entra_refresh.password_grant("alex_gmail.com@tenant.onmicrosoft.com", "pw")
        assert result == {
            "id_token": "id.jwt",
            "access_token": "acc",
            "refresh_token": "ref",
            "expires_in": 3600,
        }

    def test_password_grant_translates_email_to_upn(self):
        payload = {"id_token": "id.jwt", "access_token": "a", "refresh_token": "r", "expires_in": 60}
        captured: dict = {}

        def _fake(req, timeout=None):  # noqa: ANN001
            captured["form"] = urllib.parse.parse_qs(req.data.decode())
            return _urlopen_returning(payload)

        with patch("urllib.request.urlopen", side_effect=_fake):
            entra_refresh.password_grant("alex@gmail.com", "pw")
        # The real email is normalised to the managed-domain UPN before ROPC.
        assert captured["form"]["username"] == ["alex_gmail.com@tenant.onmicrosoft.com"]
        assert captured["form"]["grant_type"] == ["password"]

    def test_password_grant_passes_full_upn_through_unchanged(self):
        payload = {"id_token": "id.jwt", "access_token": "a", "refresh_token": "r", "expires_in": 60}
        captured: dict = {}

        def _fake(req, timeout=None):  # noqa: ANN001
            captured["form"] = urllib.parse.parse_qs(req.data.decode())
            return _urlopen_returning(payload)

        with patch("urllib.request.urlopen", side_effect=_fake):
            entra_refresh.password_grant("alex_gmail.com@tenant.onmicrosoft.com", "pw")
        assert captured["form"]["username"] == ["alex_gmail.com@tenant.onmicrosoft.com"]

    def test_password_grant_invalid_grant_raises(self):
        err = urllib.error.HTTPError(url="https://t", code=400, msg="bad", hdrs=None, fp=io.BytesIO(b'{"error":"invalid_grant"}'))
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(AuthenticationRequiredError):
                entra_refresh.password_grant("alex@gmail.com", "wrong")


class TestHandlerProviderSelection:
    def test_login_route_uses_entra_when_auth_provider_azure(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/login"}},
            "cookies": [],
            "body": json.dumps({"username": "alex@gmail.com", "password": "pw"}),
        }
        with patch(
            "services.auth.entra_refresh.password_grant",
            return_value={"id_token": "e.id", "access_token": "a", "refresh_token": "r", "expires_in": 1800},
        ) as mock_login:
            resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])["data"]
        assert body["id_token"] == "e.id"
        assert body["refresh_token"] == "r"
        mock_login.assert_called_once_with("alex@gmail.com", "pw")

    def test_login_route_404s_on_cognito(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/login"}},
            "cookies": [],
            "body": json.dumps({"username": "alex@x.com", "password": "pw"}),
        }
        resp = handler.lambda_handler(event, None)
        assert resp["statusCode"] == 404

    def test_refresh_route_uses_entra_when_auth_provider_azure(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        with patch(
            "services.auth.entra_refresh.refresh_id_token",
            return_value={"id_token": "entra.id", "access_token": "a", "expires_in": 1800},
        ) as mock_refresh:
            resp = handler.lambda_handler(_event([f"shipx_rt={_REFRESH}"]), None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"]["id_token"] == "entra.id"
        mock_refresh.assert_called_once_with(_REFRESH)

    def test_refresh_route_uses_cognito_when_auth_provider_aws(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        with patch(
            "services.auth.cognito_refresh.refresh_id_token",
            return_value={"id_token": "cognito.id", "access_token": "a", "expires_in": 1800},
        ) as mock_refresh:
            resp = handler.lambda_handler(_event([f"shipx_rt={_REFRESH}"]), None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"]["id_token"] == "cognito.id"
        mock_refresh.assert_called_once_with(_REFRESH)
