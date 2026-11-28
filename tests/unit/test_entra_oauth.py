"""Unit tests for the interactive Entra login (BFF auth-code + PKCE):
services/auth/entra_oauth.py, entra_refresh.authorization_code_grant, and the
/v1/auth/authorize-url + /v1/auth/callback handler routes. Fully mocked."""

import base64
import hashlib
import io
import json
import urllib.error
import urllib.parse
from unittest.mock import patch

import pytest

import shared.providers as providers
from services.auth import entra_oauth, entra_refresh, handler
from shared.exceptions import AuthenticationRequiredError
from tests.browser import BROWSER_HEADERS

_ENV = {
    "ENTRA_TOKEN_ENDPOINT": "https://t.ciamlogin.com/t.onmicrosoft.com/oauth2/v2.0/token",
    "ENTRA_CLIENT_ID": "client-123",
    "ENTRA_REDIRECT_URI": "https://app.example.test/auth/callback",
    "ENTRA_SCOPE": "openid profile offline_access",
}


def _encode_tx(tx: dict) -> str:
    """Encode a transaction dict the way the handler does (HMAC-signed base64url JSON)."""
    return handler._sign_tx({k: str(v) for k, v in tx.items()})


def _urlopen_returning(payload: dict):
    from unittest.mock import MagicMock

    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    cm.__exit__.return_value = False
    return cm


class TestPkceAndAuthorizeUrl:
    def test_pkce_challenge_is_sha256_of_verifier(self):
        verifier, challenge = entra_oauth.generate_pkce()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert challenge == expected
        assert 43 <= len(verifier) <= 128

    def test_authorize_endpoint_derived_from_token_endpoint(self):
        with patch.dict("os.environ", _ENV, clear=False):
            assert entra_oauth.authorize_endpoint().endswith("/oauth2/v2.0/authorize")

    def test_build_authorize_url_has_pkce_and_params(self):
        with patch.dict("os.environ", _ENV, clear=False):
            url = entra_oauth.build_authorize_url(state="st", nonce="no", code_challenge="ch")
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert qs["client_id"] == ["client-123"]
        assert qs["response_type"] == ["code"]
        assert qs["code_challenge"] == ["ch"]
        assert qs["code_challenge_method"] == ["S256"]
        assert qs["state"] == ["st"] and qs["nonce"] == ["no"]
        assert qs["redirect_uri"] == ["https://app.example.test/auth/callback"]
        # Account picker by default so users can choose / switch accounts.
        assert qs["prompt"] == ["select_account"]

    def test_build_authorize_url_prompt_is_overridable(self):
        with patch.dict("os.environ", {**_ENV, "ENTRA_AUTHORIZE_PROMPT": ""}, clear=False):
            url = entra_oauth.build_authorize_url(state="s", nonce="n", code_challenge="c")
        assert "prompt=" not in urllib.parse.urlparse(url).query

    def test_build_authorize_url_raises_when_unconfigured(self):
        with patch.dict("os.environ", {"ENTRA_TOKEN_ENDPOINT": "", "ENTRA_CLIENT_ID": "", "ENTRA_REDIRECT_URI": ""}):
            with pytest.raises(ValueError):
                entra_oauth.build_authorize_url(state="s", nonce="n", code_challenge="c")


class TestAuthorizationCodeGrant:
    def setup_method(self):
        self._env = patch.dict("os.environ", _ENV, clear=False)
        self._env.start()

    def teardown_method(self):
        self._env.stop()

    def test_exchange_maps_tokens(self):
        payload = {"id_token": "id.jwt", "access_token": "a", "refresh_token": "r", "expires_in": 3600}
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(payload)):
            result = entra_refresh.authorization_code_grant("code1", "verifier1", _ENV["ENTRA_REDIRECT_URI"])
        assert result == {"id_token": "id.jwt", "access_token": "a", "refresh_token": "r", "expires_in": 3600}

    def test_sends_code_verifier_and_grant(self):
        captured: dict = {}

        def _fake(req, timeout=None):  # noqa: ANN001
            captured["form"] = urllib.parse.parse_qs(req.data.decode())
            captured["req"] = req
            return _urlopen_returning({"id_token": "x", "refresh_token": "r", "expires_in": 60})

        with patch("urllib.request.urlopen", side_effect=_fake):
            entra_refresh.authorization_code_grant("the-code", "the-verifier", _ENV["ENTRA_REDIRECT_URI"])
        assert captured["form"]["grant_type"] == ["authorization_code"]
        assert captured["form"]["code"] == ["the-code"]
        assert captured["form"]["code_verifier"] == ["the-verifier"]
        # The redirect URI is registered under the Mobile & desktop (publicClient)
        # platform, so the server-side PKCE redemption is a same-origin POST: it
        # must NOT send an Origin header (that is SPA-only — AADSTS9002326).
        assert captured["req"].get_header("Origin") is None

    def test_refresh_does_not_send_origin_header(self):
        captured: dict = {}

        def _fake(req, timeout=None):  # noqa: ANN001
            captured["req"] = req
            return _urlopen_returning({"id_token": "x", "access_token": "a", "expires_in": 60})

        with patch("urllib.request.urlopen", side_effect=_fake):
            entra_refresh.refresh_id_token("rt")
        assert captured["req"].get_header("Origin") is None

    def test_invalid_code_raises(self):
        err = urllib.error.HTTPError(url="https://t", code=400, msg="bad", hdrs=None, fp=io.BytesIO(b'{"error":"invalid_grant"}'))
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(AuthenticationRequiredError):
                entra_refresh.authorization_code_grant("c", "v", _ENV["ENTRA_REDIRECT_URI"])


class TestHandlerInteractiveRoutes:
    def setup_method(self):
        self._env = patch.dict("os.environ", _ENV, clear=False)
        self._env.start()

    def teardown_method(self):
        self._env.stop()

    @staticmethod
    def _event(path: str, body: dict | None = None, cookies: list[str] | None = None) -> dict:
        return {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": path}},
            "headers": dict(BROWSER_HEADERS),
            "cookies": cookies or [],
            "body": json.dumps(body) if body is not None else "",
        }

    def test_authorize_url_sets_tx_cookie_and_returns_url(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        resp = handler.lambda_handler(self._event("/v1/auth/authorize-url"), None)
        assert resp["statusCode"] == 200
        assert "authorize_url" in json.loads(resp["body"])["data"]
        tx_cookie = next(c for c in resp["cookies"] if c.startswith("shipx_auth_tx="))
        assert "HttpOnly" in tx_cookie and "Secure" in tx_cookie
        # The cookie VALUE must be a valid cookie-octet string (RFC 6265): raw JSON
        # (spaces/commas/quotes/braces) is dropped by browsers. It is base64url JSON
        # carrying the PKCE verifier, state and nonce.
        value = tx_cookie.split("=", 1)[1].split(";", 1)[0]
        assert not any(ch in value for ch in ' ",;{}')
        decoded = handler._verify_tx(value)
        assert set(decoded) == {"v", "s", "n"}

    def test_callback_validates_state_exchanges_and_sets_session(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        tx = _encode_tx({"v": "verifier", "s": "state-xyz", "n": "nonce"})
        payload = base64.urlsafe_b64encode(json.dumps({"nonce": "nonce", "oid": "u1"}).encode()).decode().rstrip("=")
        fake_id_token = f"hdr.{payload}.sig"
        with patch(
            "services.auth.entra_refresh.authorization_code_grant",
            return_value={"id_token": fake_id_token, "access_token": "a", "refresh_token": "r", "expires_in": 1800},
        ) as mock_x:
            resp = handler.lambda_handler(
                self._event("/v1/auth/callback", {"code": "the-code", "state": "state-xyz"}, [f"shipx_auth_tx={tx}"]),
                None,
            )
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"]["id_token"] == fake_id_token
        # Session cookie set with the refresh token; tx cookie expired.
        assert any(c.startswith("shipx_rt=r;") for c in resp["cookies"])
        assert any(c.startswith("shipx_auth_tx=;") and "Max-Age=0" in c for c in resp["cookies"])
        mock_x.assert_called_once_with(code="the-code", code_verifier="verifier", redirect_uri=_ENV["ENTRA_REDIRECT_URI"])

    def test_callback_rejects_nonce_mismatch(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        tx = _encode_tx({"v": "verifier", "s": "state-xyz", "n": "expected-nonce"})
        payload = base64.urlsafe_b64encode(json.dumps({"nonce": "wrong-nonce"}).encode()).decode().rstrip("=")
        with patch(
            "services.auth.entra_refresh.authorization_code_grant",
            return_value={"id_token": f"hdr.{payload}.sig", "access_token": "a", "refresh_token": "r", "expires_in": 1800},
        ):
            resp = handler.lambda_handler(
                self._event("/v1/auth/callback", {"code": "the-code", "state": "state-xyz"}, [f"shipx_auth_tx={tx}"]),
                None,
            )
        assert resp["statusCode"] == 401

    def test_callback_rejects_state_mismatch(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        tx = _encode_tx({"v": "verifier", "s": "expected", "n": "nonce"})
        resp = handler.lambda_handler(
            self._event("/v1/auth/callback", {"code": "c", "state": "forged"}, [f"shipx_auth_tx={tx}"]),
            None,
        )
        assert resp["statusCode"] == 401

    def test_callback_without_tx_cookie_rejected(self, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        resp = handler.lambda_handler(
            self._event("/v1/auth/callback", {"code": "c", "state": "s"}, []),
            None,
        )
        assert resp["statusCode"] == 401

    def test_callback_rejects_malformed_tx_cookie(self, monkeypatch):
        # A tx cookie that is not valid base64url JSON (e.g. a legacy raw-JSON
        # value or a truncated cookie) fails closed rather than 500ing.
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        resp = handler.lambda_handler(
            self._event("/v1/auth/callback", {"code": "c", "state": "s"}, ["shipx_auth_tx=not-base64url!!"]),
            None,
        )
        assert resp["statusCode"] == 401
