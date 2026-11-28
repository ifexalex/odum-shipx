"""Platform admin audit, Phase 1b: platform admins must sign in with multi-factor authentication (decision D3).

AWS: a separate Cognito pool with MFA required, recognised by its verified issuer. Entra: Conditional Access, shown in
the token's ``amr`` / ``acrs``. Plus the session cookie and step-up plumbing that pool needs, and the Entra step-up
sign-in that never replaces the session cookie.
"""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

import shared.providers as providers
from shared.exceptions import AuthenticationRequiredError, PlatformMfaRequiredError
from shared.tenant_context import TenantContext, UserRole
from tests.browser import BROWSER_HEADERS

PLATFORM_ISS = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_platform"
TENANT_ISS = "https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_tenant"


@pytest.fixture
def platform_pool(monkeypatch):
    monkeypatch.setenv("PLATFORM_COGNITO_ISSUER", PLATFORM_ISS)
    monkeypatch.setenv("COGNITO_PLATFORM_USER_POOL_ID", "eu-west-1_platform")
    monkeypatch.setenv("COGNITO_PLATFORM_CLIENT_ID", "platform-client")
    yield


def _context_event(claims: dict, path: str = "/v1/platform/tenants") -> dict:
    return {"requestContext": {"http": {"method": "GET", "path": path}, "authorizer": {"jwt": {"claims": claims}}}}


# ---------------------------------------------------------------------------
# Recognising the platform pool and MFA
# ---------------------------------------------------------------------------


class TestPlatformIdentity:
    def test_a_token_from_the_platform_pool_is_recognised_by_issuer(self, platform_pool):
        from shared.platform_identity import is_platform_pool_token

        assert is_platform_pool_token({"iss": PLATFORM_ISS})
        assert is_platform_pool_token({"iss": PLATFORM_ISS + "/"})
        assert not is_platform_pool_token({"iss": TENANT_ISS})

    def test_nothing_is_a_platform_pool_token_without_a_platform_pool(self, monkeypatch):
        from shared.platform_identity import is_platform_pool_token

        monkeypatch.delenv("PLATFORM_COGNITO_ISSUER", raising=False)
        assert not is_platform_pool_token({"iss": ""})

    def test_on_aws_mfa_means_the_platform_pool(self, platform_pool):
        from shared.platform_identity import token_shows_mfa

        assert token_shows_mfa({"iss": PLATFORM_ISS}, "aws")
        assert not token_shows_mfa({"iss": TENANT_ISS, "amr": ["mfa"]}, "aws")

    @pytest.mark.parametrize(
        ("claims", "expected"),
        [
            ({"amr": ["pwd", "mfa"]}, True),
            ({"amr": "mfa"}, True),
            ({"amr": ["pwd"]}, False),
            ({}, False),
            ({"acrs": ["c1"]}, True),
            ({"acrs": ["c2"]}, False),
        ],
    )
    def test_on_entra_mfa_is_read_from_amr_or_the_configured_auth_context(self, claims, expected, monkeypatch):
        from shared.platform_identity import token_shows_mfa

        monkeypatch.setenv("ENTRA_PLATFORM_MFA_ACR", "c1")
        assert token_shows_mfa(claims, "azure") is expected

    def test_mfa_is_required_only_when_switched_on(self, monkeypatch):
        from shared.platform_identity import mfa_required

        monkeypatch.delenv("PLATFORM_MFA_REQUIRED", raising=False)
        assert not mfa_required()
        monkeypatch.setenv("PLATFORM_MFA_REQUIRED", "true")
        assert mfa_required()


class TestClaimsMapper:
    def test_a_platform_pool_token_reads_as_a_platform_admin(self, platform_pool):
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        mapper = CognitoClaimsMapper()
        claims = {"iss": PLATFORM_ISS, "sub": "s", "custom:tenant_id": "aaaa", "cognito:groups": "aaaa:tenant_admin"}
        assert mapper.tenant_id(claims) == "PLATFORM"
        assert mapper.groups(claims) == ["platform_admin"]
        assert mapper.primary_role(claims) == "platform_admin"

    def test_a_tenant_pool_token_is_read_as_before(self, platform_pool):
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        claims = {"iss": TENANT_ISS, "custom:tenant_id": "aaaa", "cognito:groups": "aaaa:tenant_admin"}
        assert CognitoClaimsMapper().tenant_id(claims) == "aaaa"


class TestMfaEnforcement:
    def test_a_platform_admin_from_the_tenant_pool_is_refused(self, platform_pool, monkeypatch):
        from shared.auth import get_tenant_context

        monkeypatch.setenv("PLATFORM_MFA_REQUIRED", "true")
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        claims = {"iss": TENANT_ISS, "sub": "s1", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
        with pytest.raises(PlatformMfaRequiredError):
            get_tenant_context(_context_event(claims))

    def test_a_platform_pool_token_passes_and_is_marked(self, platform_pool, monkeypatch):
        from shared.auth import get_tenant_context

        monkeypatch.setenv("PLATFORM_MFA_REQUIRED", "true")
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        ctx = get_tenant_context(_context_event({"iss": PLATFORM_ISS, "sub": "s1"}))
        assert ctx.is_platform_admin
        assert ctx.platform_pool is True
        assert ctx.platform_role == "owner"  # the conftest directory stub

    def test_with_mfa_off_the_tenant_pool_still_works(self, platform_pool, monkeypatch):
        from shared.auth import get_tenant_context

        monkeypatch.delenv("PLATFORM_MFA_REQUIRED", raising=False)
        claims = {"iss": TENANT_ISS, "sub": "s1", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
        ctx = get_tenant_context(_context_event(claims))
        assert ctx.is_platform_admin and ctx.platform_pool is False

    def test_tenant_users_are_never_asked_for_platform_mfa(self, platform_pool, monkeypatch):
        from shared.auth import get_tenant_context

        monkeypatch.setenv("PLATFORM_MFA_REQUIRED", "true")
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        claims = {"iss": TENANT_ISS, "sub": "u1", "custom:tenant_id": tenant, "cognito:groups": f"{tenant}:tenant_admin"}
        assert get_tenant_context(_context_event(claims, "/v1/containers")).tenant_id == tenant

    def test_the_error_is_a_403_with_its_own_code(self):
        err = PlatformMfaRequiredError()
        assert (err.status_code, err.error_code) == (403, "PLATFORM_MFA_REQUIRED")


class TestTokenVerification:
    def test_a_token_the_tenant_pool_refuses_is_tried_against_the_platform_pool(self, platform_pool, monkeypatch):
        from shared import auth_verify

        monkeypatch.setenv("PLATFORM_COGNITO_JWKS_URL", PLATFORM_ISS + "/.well-known/jwks.json")
        calls: list[tuple] = []

        def fake(token, jwks, aud, iss):
            calls.append((jwks, aud, iss))
            return None if aud != "platform-client" else {"iss": iss, "sub": "s"}

        with patch.object(auth_verify, "_verify_with", side_effect=fake):
            claims = auth_verify.verify_oidc_jwt("t")
        assert claims == {"iss": PLATFORM_ISS, "sub": "s"}
        assert calls[-1] == (PLATFORM_ISS + "/.well-known/jwks.json", "platform-client", PLATFORM_ISS)

    def test_without_a_platform_pool_only_the_tenant_pool_is_tried(self, monkeypatch):
        from shared import auth_verify

        monkeypatch.delenv("PLATFORM_COGNITO_JWKS_URL", raising=False)
        with patch.object(auth_verify, "_verify_with", return_value=None) as verify:
            assert auth_verify.verify_oidc_jwt("t") is None
        assert verify.call_count == 1


# ---------------------------------------------------------------------------
# Provisioning in the platform pool
# ---------------------------------------------------------------------------


class TestPlatformIdentityProvider:
    def test_a_platform_pool_gets_its_own_cognito_provider(self, platform_pool, monkeypatch):
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_platform_identity_provider", None)
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("COGNITO_USER_POOL_ID", "eu-west-1_tenant")
        with patch("boto3.client"):
            idp = providers.get_platform_identity_provider()
        assert idp.user_pool_id == "eu-west-1_platform"
        monkeypatch.setattr(providers, "_platform_identity_provider", None)

    def test_entra_keeps_platform_admins_in_its_one_directory(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_platform_identity_provider", None)
        monkeypatch.setattr(providers, "get_identity_provider", lambda: sentinel)
        assert providers.get_platform_identity_provider() is sentinel
        monkeypatch.setattr(providers, "_platform_identity_provider", None)


class TestDisablingDuringTheMove:
    def test_both_pools_are_tried_and_one_failure_does_not_stop_the_other(self):
        from services.tenant_management import platform_admins

        platform_idp, tenant_idp = MagicMock(), MagicMock()
        platform_idp.disable_user.side_effect = RuntimeError("UserNotFoundException")
        with (
            patch.object(platform_admins, "get_platform_identity_provider", return_value=platform_idp),
            patch.object(platform_admins, "get_identity_provider", return_value=tenant_idp),
        ):
            platform_admins._cut_off({"id": "pu", "email": "a@x.co"})
        tenant_idp.disable_user.assert_called_once_with("a@x.co")
        tenant_idp.global_sign_out.assert_called_once_with("a@x.co")
        platform_idp.global_sign_out.assert_called_once_with("a@x.co")


class TestStepUpUsesTheCallersPool:
    def test_a_platform_pool_caller_signs_in_through_the_platform_client(self, platform_pool, monkeypatch):
        import jwt

        from services.tenant_management import step_up

        monkeypatch.setenv("COGNITO_CLIENT_ID", "tenant-client")
        client = MagicMock()
        client.initiate_auth.return_value = {
            "AuthenticationResult": {"IdToken": jwt.encode({"sub": "s1"}, "k", algorithm="HS256"), "RefreshToken": "rt"}
        }
        monkeypatch.setattr(step_up, "_cognito_client", lambda: client)
        ctx = TenantContext(
            tenant_id="PLATFORM", user_id="s1", role=UserRole.PLATFORM_ADMIN, platform_role="owner", platform_pool=True
        )
        step_up._verify_cognito(ctx, "a@x.co", "secret-value", None)
        assert client.initiate_auth.call_args.kwargs["ClientId"] == "platform-client"


# ---------------------------------------------------------------------------
# The session cookie remembers which pool to refresh through
# ---------------------------------------------------------------------------

REFRESH = "r" * 40


def _auth_event(path: str, body: dict | None = None, cookies: list[str] | None = None) -> dict:
    return {
        "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": path}},
        "headers": dict(BROWSER_HEADERS),
        "cookies": cookies or [],
        "body": json.dumps(body) if body is not None else "",
    }


class TestSessionPool:
    def test_a_platform_session_sets_the_pool_cookie(self):
        from services.auth import handler

        resp = handler.lambda_handler(_auth_event("/v1/auth/session", {"refresh_token": REFRESH, "pool": "platform"}), None)
        assert resp["statusCode"] == 204
        pool_cookie = next(c for c in resp["cookies"] if c.startswith("shipx_rt_pool="))
        assert pool_cookie.startswith("shipx_rt_pool=platform;") and "HttpOnly" in pool_cookie

    def test_refresh_and_logout_use_the_platform_client(self, monkeypatch):
        from services.auth import handler

        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        cookies = [f"shipx_rt={REFRESH}", "shipx_rt_pool=platform"]
        with patch(
            "services.auth.cognito_refresh.refresh_id_token",
            return_value={"id_token": "a.b.c", "access_token": "x", "expires_in": 900},
        ) as refresh:
            handler.lambda_handler(_auth_event("/v1/auth/refresh", cookies=cookies), None)
        refresh.assert_called_once_with(REFRESH, pool="platform")
        with patch("services.auth.cognito_refresh.revoke_refresh_token") as revoke:
            resp = handler.lambda_handler(_auth_event("/v1/auth/logout", cookies=cookies), None)
        revoke.assert_called_once_with(REFRESH, pool="platform")
        assert any(c.startswith("shipx_rt_pool=;") for c in resp["cookies"])

    def test_the_client_is_chosen_by_pool(self, platform_pool, monkeypatch):
        from services.auth import cognito_refresh

        monkeypatch.setenv("COGNITO_CLIENT_ID", "tenant-client")
        assert cognito_refresh._client_id("platform") == "platform-client"
        assert cognito_refresh._client_id("tenant") == "tenant-client"
        monkeypatch.delenv("COGNITO_PLATFORM_CLIENT_ID")
        with pytest.raises(AuthenticationRequiredError):
            cognito_refresh._client_id("platform")

    def test_a_refreshed_platform_token_carries_the_platform_context(self, platform_pool):
        from services.auth import handler

        payload = base64.urlsafe_b64encode(json.dumps({"iss": PLATFORM_ISS, "sub": "s"}).encode()).decode().rstrip("=")
        assert handler._session_context(f"h.{payload}.s") == {
            "tenant_id": "PLATFORM",
            "role": "platform_admin",
            "roles": ["platform_admin"],
        }


# ---------------------------------------------------------------------------
# Entra step-up: a fresh sign-in that never touches the session cookie
# ---------------------------------------------------------------------------

_ENTRA_ENV = {
    "ENTRA_TOKEN_ENDPOINT": "https://login.example/tenant/oauth2/v2.0/token",
    "ENTRA_CLIENT_ID": "client",
    "ENTRA_REDIRECT_URI": "https://app.example/auth/callback",
}


class TestEntraStepUpSignIn:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for key, value in _ENTRA_ENV.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")

    def test_the_authorize_url_forces_a_fresh_sign_in_and_marks_the_state(self):
        import urllib.parse

        from services.auth import handler

        resp = handler.lambda_handler(_auth_event("/v1/auth/authorize-url", {"purpose": "step_up"}), None)
        url = json.loads(resp["body"])["data"]["authorize_url"]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert query["prompt"] == ["login"] and query["max_age"] == ["0"]
        assert query["state"][0].startswith("su.")
        tx_cookie = next(c for c in resp["cookies"] if c.startswith("shipx_auth_tx="))
        assert handler._verify_tx(tx_cookie.split("=", 1)[1].split(";", 1)[0])["p"] == "step_up"

    def test_an_unknown_purpose_is_refused(self):
        from services.auth import handler

        resp = handler.lambda_handler(_auth_event("/v1/auth/authorize-url", {"purpose": "admin"}), None)
        assert resp["statusCode"] == 422

    def test_the_callback_returns_the_token_and_leaves_the_session_cookie_alone(self):
        from services.auth import handler

        tx = handler._sign_tx({"v": "verifier", "s": "su.state", "n": "nonce", "p": "step_up"})
        payload = base64.urlsafe_b64encode(json.dumps({"nonce": "nonce", "oid": "u1"}).encode()).decode().rstrip("=")
        with patch(
            "services.auth.entra_refresh.authorization_code_grant",
            return_value={"id_token": f"h.{payload}.s", "access_token": "a", "refresh_token": "r", "expires_in": 1800},
        ):
            resp = handler.lambda_handler(
                _auth_event("/v1/auth/callback", {"code": "c", "state": "su.state"}, [f"shipx_auth_tx={tx}"]), None
            )
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"] == {"id_token": f"h.{payload}.s", "purpose": "step_up"}
        assert not any(c.startswith("shipx_rt=") for c in resp["cookies"])
        assert any(c.startswith("shipx_auth_tx=;") for c in resp["cookies"])


# ---------------------------------------------------------------------------
# Moving admins to the platform pool
# ---------------------------------------------------------------------------


class TestMoveToPlatformPool:
    def test_each_admin_gets_a_platform_account_and_keeps_their_old_subject(self, monkeypatch):
        import scripts.platform_admins as script

        monkeypatch.setenv("COGNITO_PLATFORM_USER_POOL_ID", "eu-west-1_platform")
        monkeypatch.setenv("COGNITO_USER_POOL_ID", "eu-west-1_tenant")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        cur = MagicMock()
        cur.fetchall.return_value = [{"id": "pu-1", "email": "a@x.co", "name": "A", "subject": "old-sub"}]
        client = MagicMock()
        from botocore.exceptions import ClientError

        client.admin_get_user.side_effect = ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
        client.admin_create_user.return_value = {"User": {"Attributes": [{"Name": "sub", "Value": "new-sub"}]}}
        with patch("boto3.client", return_value=client):
            report = script.move_to_platform_pool(cur, dry_run=False, disable_old=True)
        update_sql, params = cur.execute.call_args_list[-1].args
        assert "array_append(previous_subjects, subject)" in update_sql
        assert params == ("new-sub", "pu-1")
        client.admin_disable_user.assert_called_once_with(UserPoolId="eu-west-1_tenant", Username="a@x.co")
        assert report == ["moved a@x.co (account created, temporary password emailed)"]

    def test_a_dry_run_changes_nothing(self, monkeypatch):
        import scripts.platform_admins as script

        monkeypatch.setenv("COGNITO_PLATFORM_USER_POOL_ID", "p")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        cur = MagicMock()
        cur.fetchall.return_value = [{"id": "pu-1", "email": "a@x.co", "name": "A", "subject": "old"}]
        client = MagicMock()
        with patch("boto3.client", return_value=client):
            assert script.move_to_platform_pool(cur, dry_run=True, disable_old=False) == ["would move a@x.co"]
        client.admin_create_user.assert_not_called()
        assert cur.execute.call_count == 1
