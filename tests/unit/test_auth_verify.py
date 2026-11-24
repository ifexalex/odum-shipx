"""Unit tests for shared/auth_verify.py — the bearer-token verification shared
by the AWS Lambda authorizer and the container HTTP app. Fully mocked: no JWKS
network calls, no real JWTs."""

from unittest.mock import patch

from shared import auth_verify


class TestBuildAuthorizerClaims:
    def test_returns_none_for_empty_token(self):
        assert auth_verify.build_authorizer_claims("") is None

    def test_oidc_path_projects_cognito_shape(self):
        oidc_claims = {
            "sub": "user-123",
            "custom:tenant_id": "tenant-abc",
            "cognito:groups": "tenant-abc:tenant_admin",
        }
        with patch.object(auth_verify, "verify_oidc_jwt", return_value=oidc_claims):
            result = auth_verify.build_authorizer_claims("tok")
        assert result == {
            "sub": "user-123",
            "custom:tenant_id": "tenant-abc",
            "cognito:groups": "tenant-abc:tenant_admin",
        }

    def test_oidc_groups_list_is_flattened_to_csv(self):
        oidc_claims = {
            "sub": "u1",
            "custom:tenant_id": "t1",
            "cognito:groups": ["t1:tenant_admin", "t1:china_office_staff"],
        }
        with patch.object(auth_verify, "verify_oidc_jwt", return_value=oidc_claims):
            result = auth_verify.build_authorizer_claims("tok")
        assert result["cognito:groups"] == "t1:tenant_admin,t1:china_office_staff"

    def test_oidc_passes_entra_claims_through_unchanged(self):
        # Entra tokens carry oid / tenant_id / role / groups (object-id GUIDs), not
        # the Cognito keys. These must survive to the authorizer context so the
        # EntraClaimsMapper can read them downstream — projecting to only the
        # Cognito keys previously dropped them and 401'd every authenticated call.
        entra_claims = {
            "oid": "entra-obj-1",
            "tenant_id": "tenant-abc",
            "role": "tenant_admin",
            "groups": ["7eec8dba-c70f-4043-b84d-5c3a82b86c37"],
        }
        with patch.object(auth_verify, "verify_oidc_jwt", return_value=entra_claims):
            result = auth_verify.build_authorizer_claims("tok")
        assert result["oid"] == "entra-obj-1"
        assert result["tenant_id"] == "tenant-abc"
        assert result["role"] == "tenant_admin"
        assert result["groups"] == ["7eec8dba-c70f-4043-b84d-5c3a82b86c37"]

    def test_falls_through_to_impersonation_when_oidc_fails(self):
        imp_claims = {
            "sub": "admin-1",
            "tenant_id": "tenant-xyz",
            "role": "tenant_admin",
            "impersonated_by": "platform-admin-1",
            "session_id": "sess-1",
        }
        with (
            patch.object(auth_verify, "verify_oidc_jwt", return_value=None),
            patch.object(auth_verify, "verify_impersonation", return_value=imp_claims),
        ):
            result = auth_verify.build_authorizer_claims("tok")
        assert result == {
            "sub": "admin-1",
            "oid": "admin-1",
            "tenant_id": "tenant-xyz",
            "role": "tenant_admin",
            "custom:tenant_id": "tenant-xyz",
            "cognito:groups": "tenant-xyz:tenant_admin",
            "impersonated_by": "platform-admin-1",
            "session_id": "sess-1",
            "read_only": "true",
        }

    def test_returns_none_when_all_strategies_fail(self):
        with (
            patch.object(auth_verify, "verify_oidc_jwt", return_value=None),
            patch.object(auth_verify, "verify_impersonation", return_value=None),
        ):
            assert auth_verify.build_authorizer_claims("tok") is None


class TestVerifyOidcJwt:
    def test_returns_none_without_jwks_url(self, monkeypatch):
        monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
        monkeypatch.delenv("COGNITO_JWKS_URL", raising=False)
        assert auth_verify.verify_oidc_jwt("any.token.here") is None

    def test_env_prefers_oidc_over_cognito(self, monkeypatch):
        monkeypatch.setenv("OIDC_JWKS_URL", "https://entra.example/jwks")
        monkeypatch.setenv("COGNITO_JWKS_URL", "https://cognito.example/jwks")
        assert auth_verify._jwks_url() == "https://entra.example/jwks"

    def test_env_falls_back_to_cognito(self, monkeypatch):
        monkeypatch.delenv("OIDC_JWKS_URL", raising=False)
        monkeypatch.setenv("COGNITO_JWKS_URL", "https://cognito.example/jwks")
        assert auth_verify._jwks_url() == "https://cognito.example/jwks"

    def test_verification_failure_returns_none(self, monkeypatch):
        # A configured JWKS but a bogus token must swallow the error and return None.
        monkeypatch.setenv("OIDC_JWKS_URL", "https://entra.example/jwks")
        monkeypatch.setenv("OIDC_AUDIENCE", "aud")
        assert auth_verify.verify_oidc_jwt("not-a-jwt") is None
