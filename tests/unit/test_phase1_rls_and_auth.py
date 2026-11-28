"""Phase 1 permissioning regression tests (C-1, H-2, H-3, H-4, H-12, M-7, M-8, M-12)."""

import base64
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.auth import entra_refresh
from services.auth import handler as auth_handler
from services.notification import handler as notif_handler
from shared import auth_verify, http_routing, idempotency
from shared import providers as shared_providers
from shared.tenant_data import TENANT_TABLES
from tests.browser import BROWSER_HEADERS


def _fake_jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


class TestC1AndH3RlsCoverageAndIdempotency:
    def test_every_direct_tenant_table_has_rls_enabled_in_migrations(self) -> None:
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
        sql_blob = "\n".join(p.read_text(encoding="utf-8") for p in sorted(migrations_dir.glob("*.py")))
        enabled = set(re.findall(r"ALTER\s+TABLE\s+(\w+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", sql_blob, re.IGNORECASE))
        # Also pick up tables enabled via DO blocks (e.g., 005 loop over ARRAY[...]).
        array_matches = re.findall(r"ARRAY\[(.*?)\]", sql_blob, re.DOTALL | re.IGNORECASE)
        for block in array_matches:
            enabled.update(re.findall(r"'([a-z_][a-z0-9_]*)'", block))

        direct_tables = {t.name for t in TENANT_TABLES if t.via is None}
        missing = sorted(direct_tables - enabled)
        assert missing == [], f"Tenant-scoped tables missing ENABLE ROW LEVEL SECURITY: {missing}"

    def test_idempotency_uses_tenant_scoped_db_helpers_without_ddl(self) -> None:
        assert not hasattr(idempotency, "_ensure_table")
        with patch.object(
            idempotency,
            "execute_with_tenant",
            return_value=[{"response_body": {"statusCode": 201, "body": "{}"}}],
        ) as mock_read:
            hit = idempotency.check_idempotency("key-1", "tenant-1", actor_id="u-1", method="POST", path="/v1/billing")
        assert hit == {"statusCode": 201, "body": "{}"}
        assert mock_read.call_args[0][0] == "tenant-1"

        with patch.object(idempotency, "execute_write_with_tenant") as mock_write:
            idempotency.store_idempotency(
                "key-1", {"statusCode": 201}, "tenant-1", actor_id="u-1", method="POST", path="/v1/billing"
            )
        assert mock_write.call_args[0][0] == "tenant-1"


class TestH2AndH4OidcAndImpersonationBinding:
    def test_verify_oidc_jwt_fails_closed_without_issuer_in_non_local_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OIDC_JWKS_URL", "https://idp.example/jwks")
        monkeypatch.setenv("OIDC_AUDIENCE", "aud-1")
        monkeypatch.delenv("OIDC_ISSUER", raising=False)
        monkeypatch.delenv("COGNITO_ISSUER", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "dev")
        assert auth_verify.verify_oidc_jwt("header.payload.sig") is None

    def test_verify_oidc_jwt_rejects_entra_access_token_with_scp_claim(self, monkeypatch) -> None:
        monkeypatch.setenv("OIDC_JWKS_URL", "https://idp.example/jwks")
        monkeypatch.setenv("OIDC_AUDIENCE", "aud-1")
        monkeypatch.setenv("OIDC_ISSUER", "https://idp.example/v2.0")
        monkeypatch.setenv("ENVIRONMENT", "prod")
        fake_key = MagicMock(key="pubkey")
        fake_client = MagicMock(get_signing_key_from_jwt=MagicMock(return_value=fake_key))
        with (
            patch.object(auth_verify, "_get_jwks_client", return_value=fake_client),
            patch("jwt.decode", return_value={"oid": "u-1", "scp": "User.Read"}),
        ):
            assert auth_verify.verify_oidc_jwt("tok") is None

    def test_verify_impersonation_rejects_claim_mismatch_against_db_session(self) -> None:
        token_claims = {
            "sub": "user-victim",
            "tenant_id": "tenant-other",
            "role": "tenant_admin",
            "impersonated_by": "admin-1",
            "session_id": "sess-1",
        }
        db_session = {
            "id": "sess-1",
            "target_tenant_id": "tenant-1",
            "target_user_id": "user-1",
            "platform_admin_id": "admin-1",
            "target_role": "tenant_admin",
            "read_only": True,
        }
        with (
            patch("services.tenant_management.impersonation.verify_impersonation_token", return_value=token_claims),
            patch("services.tenant_management.impersonation.get_active_session", return_value=db_session),
        ):
            assert auth_verify.verify_impersonation("tok") is None


class TestM7M8M12AuthAndWebhookHardening:
    def test_ropc_login_disabled_in_production_by_default(self, monkeypatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("ENABLE_ROPC_LOGIN", raising=False)
        monkeypatch.setattr(shared_providers, "AUTH_PROVIDER", "azure")
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/login"}},
            "headers": dict(BROWSER_HEADERS),
            "body": json.dumps({"username": "u@acme.test", "password": "pw"}),
        }
        resp = auth_handler.lambda_handler(event, None)
        assert resp["statusCode"] == 404

    def test_callback_rejects_unsigned_or_missing_nonce_tx_cookie(self, monkeypatch) -> None:
        monkeypatch.setattr(shared_providers, "AUTH_PROVIDER", "azure")
        # Unsigned cookie rejected
        unsigned = base64.urlsafe_b64encode(json.dumps({"v": "v", "s": "st", "n": "no"}).encode()).decode()
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/callback"}},
            "headers": dict(BROWSER_HEADERS),
            "cookies": [f"shipx_auth_tx={unsigned}"],
            "body": json.dumps({"code": "c1", "state": "st"}),
        }
        assert auth_handler.lambda_handler(event, None)["statusCode"] == 401

        # Signed cookie without nonce rejected
        no_nonce = auth_handler._sign_tx({"v": "v", "s": "st", "n": ""})
        event["cookies"] = [f"shipx_auth_tx={no_nonce}"]
        assert auth_handler.lambda_handler(event, None)["statusCode"] == 401

    def test_session_context_includes_full_roles_list(self) -> None:
        tok = _fake_jwt({"oid": "entra-oid-1"})
        with patch(
            "shared.auth.resolve_identity_roles_from_db",
            return_value=("tenant-1", "nigeria_office_staff", ["nigeria_office_staff", "warehouse_attendant"]),
        ):
            ctx = auth_handler._session_context(tok)
        assert ctx == {
            "tenant_id": "tenant-1",
            "role": "nigeria_office_staff",
            "roles": ["nigeria_office_staff", "warehouse_attendant"],
        }

    def test_entra_logout_invokes_global_sign_out_when_bearer_present(self, monkeypatch) -> None:
        monkeypatch.setattr(shared_providers, "AUTH_PROVIDER", "azure")
        tok = _fake_jwt({"oid": "entra-user-42"})
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/auth/logout"}},
            "headers": {**BROWSER_HEADERS, "Authorization": f"Bearer {tok}"},
            "cookies": ["shipx_rt=test-refresh-tok"],
        }
        with patch.object(entra_refresh, "revoke_refresh_token") as mock_revoke:
            resp = auth_handler.lambda_handler(event, None)
        assert resp["statusCode"] == 204
        mock_revoke.assert_called_once_with("test-refresh-tok", subject="entra-user-42")

    def test_whatsapp_webhook_routes_to_webhook_handler_and_fails_closed_in_dev(self, monkeypatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.delenv("META_WHATSAPP_APP_SECRET", raising=False)
        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/webhooks/whatsapp"}},
            "headers": {},
            "body": "{}",
        }
        resp = http_routing.invoke_handler("notification", event)
        assert resp["statusCode"] == 401
        assert notif_handler.webhook_handler(event, None)["statusCode"] == 401
