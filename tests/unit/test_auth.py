"""Unit tests for shared.auth — JWT parsing, role validation, suspension check."""
import pytest

from shared.auth import _parse_primary_role, _parse_roles, get_tenant_context
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


class TestParseRoles:
    def test_tenant_admin_role(self):
        claims = {
            "sub": "user-1",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:tenant_admin",
        }
        roles = _parse_roles(claims, TENANT_ID)
        assert roles == frozenset({UserRole.TENANT_ADMIN})

    def test_nigeria_office_staff_role(self):
        claims = {
            "cognito:groups": f"{TENANT_ID}:nigeria_office_staff",
        }
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.NIGERIA_OFFICE_STAFF})

    def test_china_office_staff_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:china_office_staff"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CHINA_OFFICE_STAFF})

    def test_warehouse_attendant_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:warehouse_attendant"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.WAREHOUSE_ATTENDANT})

    def test_customer_role(self):
        claims = {"cognito:groups": f"{TENANT_ID}:customer"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CUSTOMER})

    def test_platform_admin_role(self):
        claims = {"cognito:groups": "platform_admin"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.PLATFORM_ADMIN})

    def test_no_matching_group_defaults_to_customer(self):
        claims = {"cognito:groups": "other-tenant:tenant_admin"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CUSTOMER})

    def test_empty_groups_defaults_to_customer(self):
        claims = {"cognito:groups": ""}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CUSTOMER})

    def test_missing_groups_defaults_to_customer(self):
        claims = {}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CUSTOMER})

    def test_invalid_role_in_group_ignored(self):
        claims = {"cognito:groups": f"{TENANT_ID}:super_user"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.CUSTOMER})

    def test_multiple_groups_for_same_tenant_all_kept(self):
        """Multi-role staff support: every matching group is kept, not just the first."""
        claims = {
            "cognito:groups": f"{TENANT_ID}:nigeria_office_staff,{TENANT_ID}:warehouse_attendant",
        }
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})

    def test_other_tenant_groups_excluded_from_multi_role_set(self):
        claims = {
            "cognito:groups": f"other-tenant:tenant_admin,{TENANT_ID}:nigeria_office_staff",
        }
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.NIGERIA_OFFICE_STAFF})

    def test_json_array_groups_string_multi_role(self):
        """API Gateway HTTP API v2's unquoted-bracket format, with 2 roles for this tenant."""
        claims = {
            "cognito:groups": f"[{TENANT_ID}:nigeria_office_staff,{TENANT_ID}:warehouse_attendant]",
        }
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})

    def test_platform_admin_group_wins_over_any_tenant_groups(self):
        claims = {"cognito:groups": f"platform_admin,{TENANT_ID}:tenant_admin"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.PLATFORM_ADMIN})

    def test_duplicate_group_deduplicated(self):
        claims = {"cognito:groups": f"{TENANT_ID}:tenant_admin,{TENANT_ID}:tenant_admin"}
        assert _parse_roles(claims, TENANT_ID) == frozenset({UserRole.TENANT_ADMIN})


class TestParsePrimaryRole:
    def test_uses_custom_role_claim_when_valid_and_assigned(self):
        roles = frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})
        claims = {"custom:role": "warehouse_attendant"}
        assert _parse_primary_role(claims, roles) == UserRole.WAREHOUSE_ATTENDANT

    def test_falls_back_when_custom_role_claim_absent(self):
        roles = frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})
        # Deterministic fallback — alphabetically first value ("nigeria_office_staff" < "warehouse_attendant").
        assert _parse_primary_role({}, roles) == UserRole.NIGERIA_OFFICE_STAFF

    def test_falls_back_when_custom_role_claim_names_unassigned_role(self):
        """custom:role is stale (names a role the user no longer holds) — must not be trusted."""
        roles = frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})
        claims = {"custom:role": "tenant_admin"}
        assert _parse_primary_role(claims, roles) == UserRole.NIGERIA_OFFICE_STAFF

    def test_falls_back_when_custom_role_claim_invalid(self):
        roles = frozenset({UserRole.CUSTOMER})
        claims = {"custom:role": "not_a_real_role"}
        assert _parse_primary_role(claims, roles) == UserRole.CUSTOMER

    def test_single_role_always_wins_regardless_of_claim(self):
        roles = frozenset({UserRole.TENANT_ADMIN})
        assert _parse_primary_role({}, roles) == UserRole.TENANT_ADMIN


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

    def test_multi_role_user_gets_full_roles_set_and_custom_role_primary(self, monkeypatch):
        """Multi-role staff support: ctx.roles carries every assigned group;
        ctx.role (primary) comes from custom:role, not an arbitrary group."""
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        claims = {
            "sub": "user-123",
            "custom:tenant_id": TENANT_ID,
            "custom:role": "warehouse_attendant",
            "cognito:groups": f"{TENANT_ID}:nigeria_office_staff,{TENANT_ID}:warehouse_attendant",
        }
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.roles == frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT})
        assert ctx.role == UserRole.WAREHOUSE_ATTENDANT


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

    def test_roles_defaults_to_singleton_set_of_primary_role(self):
        """A context constructed without `roles` (e.g. most existing test
        fixtures/call sites) must not regress to 'no roles = no permissions'."""
        ctx = TenantContext(tenant_id=TENANT_ID, user_id="u", role=UserRole.TENANT_ADMIN)
        assert ctx.roles == frozenset({UserRole.TENANT_ADMIN})

    def test_assert_role_union_check_passes_when_any_role_matches(self):
        """Multi-role staff support: assert_role is satisfied if ANY of the
        user's roles is allowed — not just the currently active/primary one."""
        ctx = TenantContext(
            tenant_id=TENANT_ID,
            user_id="u",
            role=UserRole.NIGERIA_OFFICE_STAFF,
            roles=frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT}),
        )
        ctx.assert_role(UserRole.WAREHOUSE_ATTENDANT)  # not the primary role — must still pass

    def test_assert_role_union_check_raises_when_no_role_matches(self):
        from shared.exceptions import InsufficientPermissionsError

        ctx = TenantContext(
            tenant_id=TENANT_ID,
            user_id="u",
            role=UserRole.NIGERIA_OFFICE_STAFF,
            roles=frozenset({UserRole.NIGERIA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT}),
        )
        with pytest.raises(InsufficientPermissionsError):
            ctx.assert_role(UserRole.TENANT_ADMIN)

    def test_113_call_sites_unaffected_signature_still_star_args(self):
        """Regression guard: assert_role must keep its *allowed_roles call
        signature so none of the 113 existing call sites need to change."""
        import inspect

        sig = inspect.signature(TenantContext.assert_role)
        params = list(sig.parameters.values())
        assert params[1].kind == inspect.Parameter.VAR_POSITIONAL
        assert params[1].name == "allowed_roles"


# ---------------------------------------------------------------------------
# Read-only impersonation enforcement
# ---------------------------------------------------------------------------

_IMP_CLAIMS = {
    "sub": "tenant-user-1",
    "custom:tenant_id": TENANT_ID,
    "cognito:groups": f"{TENANT_ID}:tenant_admin",
    "impersonated_by": "platform-admin-1",
    "session_id": "session-uuid-1",
    "read_only": "true",
}


def _imp_event(method: str) -> dict:
    """Build an API Gateway event carrying impersonation claims."""
    return {
        "requestContext": {
            "authorizer": {"claims": _IMP_CLAIMS},
            "http": {"method": method, "path": "/v1/test"},
        }
    }


class TestReadOnlyImpersonation:
    """get_tenant_context must reject mutating methods for read_only sessions.

    The guard is enforced centrally inside get_tenant_context so every handler
    is protected without needing explicit call sites.
    """

    def test_post_blocked_for_impersonation(self, monkeypatch):
        from shared.exceptions import BusinessRuleViolationError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        with pytest.raises(BusinessRuleViolationError) as exc_info:
            get_tenant_context(_imp_event("POST"))
        assert exc_info.value.error_code == "BUSINESS_RULE_VIOLATION"
        assert exc_info.value.rule_id == "IMPERSONATION_READ_ONLY"

    def test_patch_blocked_for_impersonation(self, monkeypatch):
        from shared.exceptions import BusinessRuleViolationError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        with pytest.raises(BusinessRuleViolationError):
            get_tenant_context(_imp_event("PATCH"))

    def test_delete_blocked_for_impersonation(self, monkeypatch):
        from shared.exceptions import BusinessRuleViolationError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        with pytest.raises(BusinessRuleViolationError):
            get_tenant_context(_imp_event("DELETE"))

    def test_put_blocked_for_impersonation(self, monkeypatch):
        from shared.exceptions import BusinessRuleViolationError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        with pytest.raises(BusinessRuleViolationError):
            get_tenant_context(_imp_event("PUT"))

    def test_get_allowed_for_impersonation(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        ctx = get_tenant_context(_imp_event("GET"))
        assert ctx.read_only is True
        assert ctx.impersonated_by == "platform-admin-1"
        assert ctx.session_id == "session-uuid-1"
        assert ctx.role == UserRole.TENANT_ADMIN

    def test_head_allowed_for_impersonation(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        ctx = get_tenant_context(_imp_event("HEAD"))
        assert ctx.read_only is True

    def test_options_allowed_for_impersonation(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        ctx = get_tenant_context(_imp_event("OPTIONS"))
        assert ctx.read_only is True

    def test_normal_post_not_blocked(self, monkeypatch):
        """Non-impersonated users must not be affected by the guard."""
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        normal_event = {
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": "user-1",
                        "custom:tenant_id": TENANT_ID,
                        "cognito:groups": f"{TENANT_ID}:tenant_admin",
                    }
                },
                "http": {"method": "POST", "path": "/v1/test"},
            }
        }
        ctx = get_tenant_context(normal_event)
        assert ctx.read_only is False

    def test_regression_guard_lives_in_get_tenant_context(self):
        """assert_not_read_only must be called from inside get_tenant_context.

        This test fails if someone moves the enforcement out of get_tenant_context
        and back to individual call sites (regression guard).
        """
        import inspect

        from shared.auth import get_tenant_context as fn

        source = inspect.getsource(fn)
        assert "assert_not_read_only" in source, (
            "get_tenant_context must call assert_not_read_only — " "central enforcement was removed"
        )
