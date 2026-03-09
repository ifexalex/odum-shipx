"""Unit tests for shared.auth — JWT parsing, role validation, suspension check."""
import pytest

from shared.auth import _parse_role, get_tenant_context
from shared.exceptions import AuthenticationRequiredError, TenantSuspendedError
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _event_with_claims(claims: dict) -> dict:
    return {
        "requestContext": {
            "authorizer": {"claims": claims},
            "http": {"method": "GET", "path": "/v1/test"},
        }
    }


# ---------------------------------------------------------------------------
# Role parsing
# ---------------------------------------------------------------------------


class TestParseRole:
    def test_tenant_admin_role(self):
        claims = {
            "sub": "user-1",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:tenant_admin",
        }
        role = _parse_role(claims, TENANT_ID)
        assert role == UserRole.TENANT_ADMIN

    def test_nigeria_office_staff_role(self):
        claims = {
            "cognito:groups": f"{TENANT_ID}:nigeria_office_staff",
        }
        assert _parse_role(claims, TENANT_ID) == UserRole.NIGERIA_OFFICE_STAFF

    def test_china_office_staff_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:china_office_staff"}
        assert _parse_role(claims, TENANT_ID) == UserRole.CHINA_OFFICE_STAFF

    def test_warehouse_attendant_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:warehouse_attendant"}
        assert _parse_role(claims, TENANT_ID) == UserRole.WAREHOUSE_ATTENDANT

    def test_customer_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:customer"}
        assert _parse_role(claims, TENANT_ID) == UserRole.CUSTOMER

    def test_platform_admin_role(self):
        claims = {"cognito:groups": "platform_admin"}
        assert _parse_role(claims, TENANT_ID) == UserRole.PLATFORM_ADMIN

    def test_no_matching_group_defaults_to_customer(self):
        claims = {"cognito:groups": "other-tenant:tenant_admin"}
        assert _parse_role(claims, TENANT_ID) == UserRole.CUSTOMER

    def test_empty_groups_defaults_to_customer(self):
        claims = {"cognito:groups": ""}
        assert _parse_role(claims, TENANT_ID) == UserRole.CUSTOMER

    def test_missing_groups_defaults_to_customer(self):
        claims = {}
        assert _parse_role(claims, TENANT_ID) == UserRole.CUSTOMER

    def test_multiple_groups_picks_first_matching(self):
        claims = {"cognito:groups": f"other-tenant:tenant_admin,{TENANT_ID}:nigeria_office_staff"}
        assert _parse_role(claims, TENANT_ID) == UserRole.NIGERIA_OFFICE_STAFF

    def test_invalid_role_in_group_ignored(self):
        claims = {"cognito:groups": f"{TENANT_ID}:super_user"}
        assert _parse_role(claims, TENANT_ID) == UserRole.CUSTOMER


# ---------------------------------------------------------------------------
# get_tenant_context
# ---------------------------------------------------------------------------


class TestGetTenantContext:
    def test_extracts_context_from_valid_claims(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        claims = {
            "sub": "user-123",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:tenant_admin",
        }
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.tenant_id == TENANT_ID
        assert ctx.user_id == "user-123"
        assert ctx.role == UserRole.TENANT_ADMIN

    def test_missing_claims_raises_auth_error(self):
        event = {"requestContext": {"authorizer": {"claims": {}}}}
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(event)

    def test_missing_sub_raises_auth_error(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        claims = {
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:customer",
        }
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims(claims))

    def test_missing_tenant_id_raises_auth_error(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        claims = {
            "sub": "user-123",
            "cognito:groups": f"{TENANT_ID}:customer",
        }
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims(claims))

    def test_suspended_tenant_raises_error(self, monkeypatch):
        def _raise(tid):
            raise TenantSuspendedError(tid)

        monkeypatch.setattr("shared.auth._check_tenant_active", _raise)
        claims = {
            "sub": "user-123",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:tenant_admin",
        }
        with pytest.raises(TenantSuspendedError):
            get_tenant_context(_event_with_claims(claims))

    def test_platform_admin_skips_suspension_check(self, monkeypatch):
        """Platform admins bypass tenant suspension check."""
        called = []
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: called.append(tid))
        claims = {
            "sub": "platform-user",
            "custom:tenant_id": "PLATFORM",
            "cognito:groups": "platform_admin",
        }
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.role == UserRole.PLATFORM_ADMIN
        assert called == []  # suspension check not called for PLATFORM tenant


# ---------------------------------------------------------------------------
# TenantContext.assert_role
# ---------------------------------------------------------------------------


class TestAssertRole:
    def test_assert_role_passes_for_allowed_role(self):
        ctx = TenantContext(tenant_id=TENANT_ID, user_id="u", role=UserRole.TENANT_ADMIN)
        ctx.assert_role(UserRole.TENANT_ADMIN)  # should not raise

    def test_assert_role_passes_for_one_of_multiple(self):
        ctx = TenantContext(tenant_id=TENANT_ID, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)
        ctx.assert_role(UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF)

    def test_assert_role_raises_for_wrong_role(self):
        from shared.exceptions import InsufficientPermissionsError

        ctx = TenantContext(tenant_id=TENANT_ID, user_id="u", role=UserRole.CUSTOMER)
        with pytest.raises(InsufficientPermissionsError):
            ctx.assert_role(UserRole.TENANT_ADMIN)
