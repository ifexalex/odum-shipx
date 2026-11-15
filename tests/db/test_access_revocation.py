"""Revoking a user's access against a real database (audit SEC-02).

A token is a signed claim that was true when it was issued. These tests issue one for an
active user, deactivate that user, and ask whether the very next request is still served.
Mocks cannot answer that: the answer lives in the `tenant_user.status` query, the identity
cache that sits in front of it, and the eviction that bridges the two. The cache is an in-memory
stand-in here (Redis is not part of this suite) with the same get/set/delete contract; the
database, the SQL and the service functions are real. Only the identity provider and the
audit log are stubbed.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import AuthenticationRequiredError, TenantSuspendedError
from shared.tenant_context import UserRole

pytestmark = pytest.mark.db


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def identity_cache(monkeypatch) -> _FakeCache:
    identity, tenant_status = _FakeCache(), _FakeCache()
    monkeypatch.setattr("shared.auth._identity_cache", identity)
    monkeypatch.setattr("shared.auth._tenant_status_cache", tenant_status)
    return identity


def _token_event(world, user_id: str, role: str = "nigeria_office_staff") -> dict:
    """The request a still-valid token produces: it carries the tenant claim, so no lookup is implied."""
    claims = {"sub": user_id, "custom:tenant_id": world["tenant"], "cognito:groups": f"{world['tenant']}:{role}"}
    return {"requestContext": {"authorizer": {"claims": claims}, "http": {"method": "GET", "path": "/v1/test"}}}


def _context(world, user_id: str, role: str = "nigeria_office_staff"):
    from shared.auth import get_tenant_context

    return get_tenant_context(_token_event(world, user_id, role))


def _deactivate(world, user_id: str, cognito=None):
    from services.tenant_management import service

    with (
        patch("services.tenant_management.service.get_identity_provider", return_value=cognito or MagicMock()),
        patch("services.tenant_management.service.log_audit"),
    ):
        return service.deactivate_user(world["tenant"], user_id, actor_id=world["user"])


def _portal_login(admin, world) -> tuple[str, str]:
    """A customer with a portal login: (customer_id, tenant_user_id)."""
    login_id, customer_id = str(uuid.uuid4()), world["customers"][0]
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) VALUES (%s, %s, %s, 'Ada Customer', 'customer')",
            (login_id, world["tenant"], f"ada-{login_id[:8]}@example.test"),
        )
        cur.execute("UPDATE customer SET user_id = %s, email = 'ada@example.test' WHERE id = %s", (login_id, customer_id))
    return customer_id, login_id


class TestDeactivatedUserLosesAccess:
    def test_an_active_user_is_let_in(self, world, identity_cache):
        ctx = _context(world, world["user"])
        assert ctx.user_id == world["user"]
        assert ctx.role == UserRole.NIGERIA_OFFICE_STAFF

    def test_a_token_issued_before_deactivation_is_refused_on_the_next_request(self, world, identity_cache):
        """The finding: the token is unexpired and correctly signed, and used to keep working."""
        _context(world, world["user"])  # the user is working; their identity is now cached as active
        assert identity_cache.store[world["user"]] != ""

        _deactivate(world, world["user"])

        with pytest.raises(AuthenticationRequiredError):
            _context(world, world["user"])

    def test_the_identity_provider_is_told_to_end_the_sessions(self, world, identity_cache, admin):
        cognito = MagicMock()
        _deactivate(world, world["user"], cognito)

        with admin.cursor() as cur:
            cur.execute("SELECT email FROM tenant_user WHERE id = %s", (world["user"],))
            email = cur.fetchone()[0]
        cognito.disable_user.assert_called_once_with(email)
        cognito.global_sign_out.assert_called_once_with(email)

    def test_without_the_eviction_the_old_answer_would_be_served(self, world, identity_cache, admin):
        """Why the eviction exists: change the row behind the cache's back and the cache wins."""
        _context(world, world["user"])
        with admin.cursor() as cur:
            cur.execute("UPDATE tenant_user SET status = 'deactivated' WHERE id = %s", (world["user"],))

        assert _context(world, world["user"]).user_id == world["user"]  # stale, within the cache TTL

        from shared.auth import evict_identity_cache

        evict_identity_cache(world["user"])
        with pytest.raises(AuthenticationRequiredError):
            _context(world, world["user"])

    def test_one_users_deactivation_does_not_touch_a_colleague(self, world, identity_cache, admin):
        colleague = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) "
                "VALUES (%s, %s, %s, 'Colleague', 'nigeria_office_staff')",
                (colleague, world["tenant"], f"colleague-{colleague[:8]}@example.test"),
            )
        _context(world, colleague)

        _deactivate(world, world["user"])

        assert _context(world, colleague).user_id == colleague

    def test_a_token_for_another_tenant_is_refused_even_for_a_real_user(self, world, identity_cache):
        """The user exists and is active, but not in the tenant the token claims."""
        event = _token_event(world, world["user"])
        event["requestContext"]["authorizer"]["claims"]["custom:tenant_id"] = str(uuid.uuid4())
        event["requestContext"]["authorizer"]["claims"]["cognito:groups"] = ""

        from shared.auth import get_tenant_context
        from shared.exceptions import LogisticsBaseError

        with pytest.raises(LogisticsBaseError):  # the tenant check or the user check, whichever sees it first
            get_tenant_context(event)

    def test_a_suspended_tenant_is_still_reported_as_suspended(self, world, identity_cache, admin):
        """The user check runs after the tenant check, so it does not mask the more specific answer."""
        with admin.cursor() as cur:
            cur.execute("UPDATE tenant SET status = 'suspended' WHERE id = %s", (world["tenant"],))
        with pytest.raises(TenantSuspendedError):
            _context(world, world["user"])


class TestErasedCustomerLosesTheirLogin:
    def test_erasing_a_customer_ends_their_login_and_keeps_the_audit_trail_consistent(self, world, identity_cache, admin):
        from services.tenant_management import service

        customer_id, login_id = _portal_login(admin, world)
        assert _context(world, login_id, "customer").user_id == login_id

        cognito = MagicMock()
        with (
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit") as audit,
        ):
            service.anonymise_customer(world["tenant"], customer_id, actor_id=world["user"])

        with pytest.raises(AuthenticationRequiredError):
            _context(world, login_id, "customer")
        with admin.cursor() as cur:
            cur.execute("SELECT status FROM tenant_user WHERE id = %s", (login_id,))
            assert cur.fetchone()[0] == "deactivated"
            cur.execute("SELECT name, email, user_id, anonymised_at IS NOT NULL FROM customer WHERE id = %s", (customer_id,))
            assert cur.fetchone() == ("Anonymised", None, None, True)
        cognito.global_sign_out.assert_called_once()
        reasons = [
            c.kwargs["after_state"].get("reason") for c in audit.call_args_list if c.kwargs["entity_type"] == "tenant_user"
        ]
        assert reasons == ["customer_erasure"]

    def test_a_customer_without_a_login_is_erased_without_touching_the_identity_provider(self, world, identity_cache, admin):
        from services.tenant_management import service

        cognito = MagicMock()
        with (
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
        ):
            service.anonymise_customer(world["tenant"], world["customers"][1], actor_id=world["user"])

        cognito.disable_user.assert_not_called()
        cognito.global_sign_out.assert_not_called()

    def test_a_failure_to_disable_the_login_leaves_the_customer_intact_for_a_retry(self, world, identity_cache, admin):
        from services.tenant_management import service
        from shared.exceptions import ExternalServiceError

        customer_id, login_id = _portal_login(admin, world)
        cognito = MagicMock()
        cognito.disable_user.side_effect = ExternalServiceError("Cognito", "unavailable")
        with (
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
        ):
            with pytest.raises(ExternalServiceError):
                service.anonymise_customer(world["tenant"], customer_id, actor_id=world["user"])

        with admin.cursor() as cur:
            cur.execute("SELECT anonymised_at, user_id FROM customer WHERE id = %s", (customer_id,))
            anonymised_at, user_id = cur.fetchone()
            cur.execute("SELECT status FROM tenant_user WHERE id = %s", (login_id,))
            status = cur.fetchone()[0]
        assert anonymised_at is None and str(user_id) == login_id, "the record must survive so the erasure can be retried"
        assert status == "active"
