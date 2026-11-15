"""Unit tests for shared.auth — JWT parsing, role validation, suspension check."""

import pytest

from shared.auth import _check_user_active as _real_check_user_active
from shared.auth import _parse_primary_role, _parse_roles, get_tenant_context
from shared.exceptions import AuthenticationRequiredError, ServiceUnavailableError, TenantSuspendedError
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


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
            "get_tenant_context must call assert_not_read_only — central enforcement was removed"
        )


class TestCognitoClaimsMapper:
    """The claims mapper is the only cloud-specific part of claim reading
    (ADR-004 Phase 2); auth.py keeps the {tenant_id}:{role} interpretation."""

    def _mapper(self):
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        return CognitoClaimsMapper()

    def test_extracts_logical_fields_from_cognito_claims(self):
        m = self._mapper()
        claims = {
            "sub": "user-1",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:tenant_admin",
            "custom:role": "tenant_admin",
        }
        assert m.user_id(claims) == "user-1"
        assert m.tenant_id(claims) == TENANT_ID
        assert m.groups(claims) == [f"{TENANT_ID}:tenant_admin"]
        assert m.primary_role(claims) == "tenant_admin"

    def test_groups_handles_http_v2_bracket_form_and_missing(self):
        m = self._mapper()
        assert m.groups({"cognito:groups": f"[{TENANT_ID}:a,{TENANT_ID}:b]"}) == [
            f"{TENANT_ID}:a",
            f"{TENANT_ID}:b",
        ]
        assert m.groups({}) == []

    def test_missing_fields_are_empty_or_none(self):
        m = self._mapper()
        assert m.user_id({}) == ""
        assert m.tenant_id({}) == ""
        assert m.primary_role({}) is None

    def test_factory_default_cloud_returns_cognito_mapper(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper
        from shared.providers.base import ClaimsMapper

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_claims_mapper", None)

        mapper = providers.get_claims_mapper()
        assert isinstance(mapper, CognitoClaimsMapper)
        assert isinstance(mapper, ClaimsMapper)
        assert mapper is providers.get_claims_mapper()  # cached singleton


# ---------------------------------------------------------------------------
# Identity resolution from the DB (tokens with no tenant claim)
# ---------------------------------------------------------------------------


def _use_entra_mapper(monkeypatch) -> None:
    """Switch the claims mapper to Entra (reads `oid`/`tenant_id`, not Cognito's
    `sub`/`custom:tenant_id`) and reset the cached singleton."""
    import shared.providers as providers

    monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
    monkeypatch.setattr(providers, "_claims_mapper", None)


class TestIdentityResolutionFallback:
    """Entra External ID does not emit the custom-claims provider's tenant_id/
    role into the token, so for tenant-scoped users those claims are simply
    absent. `tenant_user.id` IS the IdP subject, so the oid in the token is
    enough to resolve the same authoritative answer from the DB."""

    def test_resolves_tenant_and_role_when_the_token_has_no_tenant_claim(self, monkeypatch):
        _use_entra_mapper(monkeypatch)
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        monkeypatch.setattr("shared.auth.resolve_identity_from_db", lambda uid: (TENANT_ID, "tenant_admin"))
        # An Entra token: oid present, no tenant_id/role, groups only holds GUIDs.
        claims = {"oid": "entra-oid-1", "groups": ["some-directory-guid"]}
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.tenant_id == TENANT_ID
        assert ctx.user_id == "entra-oid-1"
        assert ctx.role == UserRole.TENANT_ADMIN
        assert UserRole.TENANT_ADMIN in ctx.roles

    def test_unresolvable_subject_is_denied(self, monkeypatch):
        _use_entra_mapper(monkeypatch)
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        monkeypatch.setattr("shared.auth.resolve_identity_from_db", lambda uid: None)
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims({"oid": "unknown-oid"}))

    def test_explicit_tenant_claim_does_not_use_the_identity_fallback(self, monkeypatch):
        """A token that already carries the claim takes its tenant and role from it. The user is
        still checked for an active row (TestActiveUserCheck), but not by this fallback."""
        _use_entra_mapper(monkeypatch)
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)

        def _boom(uid):  # pragma: no cover - must never be called
            raise AssertionError("resolve_identity_from_db should not be called")

        monkeypatch.setattr("shared.auth.resolve_identity_from_db", _boom)
        claims = {"oid": "o1", "tenant_id": TENANT_ID, "role": "nigeria_office_staff"}
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.tenant_id == TENANT_ID
        assert ctx.role == UserRole.NIGERIA_OFFICE_STAFF

    def test_platform_admin_never_needs_the_db(self, monkeypatch):
        """platform_admin derives PLATFORM from the group claim, so it must not
        depend on a tenant_user row (it legitimately has none)."""
        import shared.providers as providers

        def _boom(uid):  # pragma: no cover - must never be called
            raise AssertionError("resolve_identity_from_db should not be called")

        monkeypatch.setattr("shared.auth.resolve_identity_from_db", _boom)
        monkeypatch.setenv("ENTRA_PLATFORM_ADMIN_GROUP_ID", "group-guid-pa")
        _use_entra_mapper(monkeypatch)
        try:
            ctx = get_tenant_context(_event_with_claims({"oid": "pa-1", "groups": ["group-guid-pa"]}))
            assert ctx.tenant_id == "PLATFORM"
            assert ctx.role == UserRole.PLATFORM_ADMIN
        finally:
            monkeypatch.setattr(providers, "_claims_mapper", None)


# ---------------------------------------------------------------------------
# Active-user check (SEC-02): a valid token must not outlive its user
# ---------------------------------------------------------------------------


class _FakeCache:
    """In-memory stand-in for the Redis-backed DistributedCache."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


_TENANT_CLAIMS = {
    "sub": "user-123",
    "custom:tenant_id": TENANT_ID,
    "cognito:groups": f"{TENANT_ID}:nigeria_office_staff",
}


class TestActiveUserCheck:
    @pytest.fixture(autouse=True)
    def _real_check(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tid: None)
        monkeypatch.setattr("shared.auth._check_user_active", _real_check_user_active)

    def test_a_deactivated_user_with_a_valid_token_is_denied(self, monkeypatch):
        """The token is signed and unexpired, but its user has no active row any more."""
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: None)
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims(_TENANT_CLAIMS))

    def test_a_user_with_an_active_row_is_let_through(self, monkeypatch):
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: (TENANT_ID, "nigeria_office_staff"))
        ctx = get_tenant_context(_event_with_claims(_TENANT_CLAIMS))
        assert ctx.user_id == "user-123"
        assert ctx.tenant_id == TENANT_ID

    def test_the_lookup_is_by_the_token_subject(self, monkeypatch):
        seen: list[str] = []
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: seen.append(uid) or (TENANT_ID, "customer"))
        get_tenant_context(_event_with_claims(_TENANT_CLAIMS))
        assert seen == ["user-123"]

    def test_a_token_for_a_tenant_that_is_not_the_users_is_denied(self, monkeypatch):
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: (OTHER_TENANT_ID, "nigeria_office_staff"))
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims(_TENANT_CLAIMS))

    def test_tenant_ids_compare_regardless_of_case(self, monkeypatch):
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: (TENANT_ID.upper(), "customer"))
        assert get_tenant_context(_event_with_claims(_TENANT_CLAIMS)).tenant_id == TENANT_ID

    def test_a_failed_lookup_denies_with_503_instead_of_letting_the_user_in(self, monkeypatch):
        """Fail closed: an outage must not be a way to keep a revoked user in."""

        def _down(uid):
            raise RuntimeError("database unreachable")

        monkeypatch.setattr("shared.auth._active_identity", _down)
        with pytest.raises(ServiceUnavailableError):
            get_tenant_context(_event_with_claims(_TENANT_CLAIMS))

    def test_an_impersonation_token_is_checked_like_any_other(self, monkeypatch):
        """Its subject is the target tenant's admin; if that admin is deactivated the session ends."""
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: None)
        with pytest.raises(AuthenticationRequiredError):
            get_tenant_context(_event_with_claims(_IMP_CLAIMS))

    def test_a_platform_admin_has_no_row_and_is_not_looked_up(self, monkeypatch):
        def _boom(uid):  # pragma: no cover - must never be called
            raise AssertionError("a platform admin must not be looked up in tenant_user")

        monkeypatch.setattr("shared.auth._active_identity", _boom)
        claims = {"sub": "pa-1", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
        ctx = get_tenant_context(_event_with_claims(claims))
        assert ctx.role == UserRole.PLATFORM_ADMIN

    def test_a_token_without_a_tenant_claim_is_looked_up_once(self, monkeypatch):
        """The identity fallback already proved the user active; the check must not repeat it."""
        _use_entra_mapper(monkeypatch)
        calls: list[str] = []
        monkeypatch.setattr("shared.auth._active_identity", lambda uid: calls.append(uid) or (TENANT_ID, "tenant_admin"))
        get_tenant_context(_event_with_claims({"oid": "entra-oid-1", "groups": ["some-directory-guid"]}))
        assert calls == ["entra-oid-1"]


class TestActiveIdentityLookup:
    """The cached lookup behind the check, and the eviction that makes deactivation immediate."""

    @pytest.fixture
    def cache(self, monkeypatch) -> _FakeCache:
        fake = _FakeCache()
        monkeypatch.setattr("shared.auth._identity_cache", fake)
        return fake

    @staticmethod
    def _database(monkeypatch, rows):
        calls: list[tuple] = []

        def _execute(tenant_id, query, params=None):
            calls.append(params)
            return rows() if callable(rows) else rows

        monkeypatch.setattr("shared.db.execute_with_tenant", _execute)
        return calls

    def test_reads_the_database_once_then_the_cache(self, monkeypatch, cache):
        from shared.auth import _active_identity

        calls = self._database(monkeypatch, [{"tenant_id": TENANT_ID, "role": "customer"}])
        assert _active_identity("u1") == (TENANT_ID, "customer")
        assert _active_identity("u1") == (TENANT_ID, "customer")
        assert len(calls) == 1
        assert cache.store["u1"] == f"{TENANT_ID}:customer"

    def test_only_an_active_row_counts(self, monkeypatch, cache):
        from shared.auth import _active_identity

        captured: list[str] = []

        def _execute(tenant_id, query, params=None):
            captured.append(query)
            return []

        monkeypatch.setattr("shared.db.execute_with_tenant", _execute)
        assert _active_identity("u1") is None
        assert "status = 'active'" in captured[0]

    def test_an_absent_user_is_remembered_as_absent(self, monkeypatch, cache):
        from shared.auth import _active_identity

        calls = self._database(monkeypatch, [])
        assert _active_identity("u1") is None
        assert _active_identity("u1") is None
        assert len(calls) == 1
        assert cache.store["u1"] == ""

    def test_deactivation_is_seen_on_the_very_next_request_once_the_entry_is_evicted(self, monkeypatch, cache):
        """The scenario of the finding: cached as active, then deactivated in the database."""
        from shared.auth import _active_identity, evict_identity_cache

        state = {"rows": [{"tenant_id": TENANT_ID, "role": "nigeria_office_staff"}]}
        self._database(monkeypatch, lambda: state["rows"])
        assert _active_identity("u1") == (TENANT_ID, "nigeria_office_staff")

        state["rows"] = []  # the user is deactivated
        assert _active_identity("u1") is not None  # still served from the cache: why eviction exists

        evict_identity_cache("u1")
        assert _active_identity("u1") is None

    def test_a_database_failure_is_raised_and_not_cached(self, monkeypatch, cache):
        from shared.auth import _active_identity

        def _down(tenant_id, query, params=None):
            raise RuntimeError("database unreachable")

        monkeypatch.setattr("shared.db.execute_with_tenant", _down)
        with pytest.raises(RuntimeError):
            _active_identity("u1")
        assert "u1" not in cache.store

    def test_the_identity_fallback_still_tolerates_a_failure(self, monkeypatch, cache):
        """resolve_identity_from_db keeps its contract: a failure is None, so the caller answers 401."""
        from shared.auth import resolve_identity_from_db

        def _down(tenant_id, query, params=None):
            raise RuntimeError("database unreachable")

        monkeypatch.setattr("shared.db.execute_with_tenant", _down)
        assert resolve_identity_from_db("u1") is None
        assert "u1" not in cache.store
