"""Self-registration must not reveal which emails already have an account (audit SEC-04).

Two registrations for the same email go through the real handler and the real repository SQL,
which is where "does this email already exist" is decided. Only the identity provider and the
notification queue are stubbed.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import DuplicateResourceError
from tests.patching import patch_tenant_management

pytestmark = pytest.mark.db


def _register(world, email: str, cognito: MagicMock, enqueue: MagicMock) -> dict:
    from services.tenant_management import handler

    slug = f"money-{world['tenant'][:8]}"
    event = {
        "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": f"/v1/register/{slug}"}},
        "headers": {"host": "api.shipx.test"},
        "body": json.dumps({"name": "Ngozi Okonkwo", "email": email, "phone": "08012345678"}),
        "cookies": [],
    }
    with (
        patch_tenant_management("get_identity_provider", return_value=cognito),
        patch_tenant_management("log_audit"),
        patch("services.tenant_management.customers.login_url", return_value="https://app.shipx.test/login"),
        patch("shared.notifications.enqueue_notifications", enqueue),
    ):
        return handler.lambda_handler(event, None)


def _count(admin, sql: str, params: tuple) -> int:
    with admin.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


@pytest.fixture
def cognito() -> MagicMock:
    provider = MagicMock()
    provider.create_user.side_effect = lambda **kwargs: str(uuid.uuid4())
    return provider


class TestRegistrationDoesNotRevealExistingAccounts:
    def test_a_second_registration_for_the_same_email_is_answered_identically_and_creates_nothing(self, world, admin, cognito):
        email = f"ngozi-{uuid.uuid4().hex[:8]}@example.test"
        enqueue = MagicMock()

        first = _register(world, email, cognito, enqueue)
        second = _register(world, email, cognito, enqueue)

        assert first["statusCode"] == second["statusCode"] == 202
        assert first["body"] == second["body"]
        assert _count(admin, "SELECT COUNT(*) FROM customer WHERE tenant_id = %s AND email = %s", (world["tenant"], email)) == 1
        assert (
            _count(admin, "SELECT COUNT(*) FROM tenant_user WHERE tenant_id = %s AND email = %s", (world["tenant"], email)) == 1
        )
        assert cognito.create_user.call_count == 1, "the existing account must not be provisioned again"

    def test_only_the_existing_accounts_owner_hears_about_the_second_attempt(self, world, admin, cognito):
        email = f"ngozi-{uuid.uuid4().hex[:8]}@example.test"
        enqueue = MagicMock()

        _register(world, email, cognito, enqueue)
        events_after_first = [c.kwargs["event_type"] for c in enqueue.call_args_list]
        _register(world, email, cognito, enqueue)
        events_after_second = [c.kwargs["event_type"] for c in enqueue.call_args_list]

        assert events_after_first == ["customer_registered"]
        assert events_after_second == ["customer_registered", "registration_existing_account"]
        notice = enqueue.call_args_list[-1].kwargs
        assert notice["recipient"]["email"] == email
        assert notice["recipient"]["name"] == "Ngozi Okonkwo"

    def test_a_differently_cased_email_is_the_same_account(self, world, admin, cognito):
        local = f"ngozi-{uuid.uuid4().hex[:8]}"
        enqueue = MagicMock()

        _register(world, f"{local}@example.test", cognito, enqueue)
        again = _register(world, f"{local.upper()}@Example.Test", cognito, enqueue)

        assert again["statusCode"] == 202
        assert (
            _count(
                admin,
                "SELECT COUNT(*) FROM customer WHERE tenant_id = %s AND LOWER(email) = %s",
                (world["tenant"], f"{local}@example.test"),
            )
            == 1
        )
        assert cognito.create_user.call_count == 1

    def test_an_email_that_exists_only_in_the_shared_identity_pool_is_answered_the_same(self, world, admin, cognito):
        """An account at another company is invisible to this tenant's table; the provider's duplicate error is what shows it."""
        email = f"elsewhere-{uuid.uuid4().hex[:8]}@example.test"
        cognito.create_user.side_effect = DuplicateResourceError("user", email)
        enqueue = MagicMock()

        resp = _register(world, email, cognito, enqueue)

        assert resp["statusCode"] == 202
        assert json.loads(resp["body"]) == {"data": {"status": "received"}}
        assert _count(admin, "SELECT COUNT(*) FROM customer WHERE tenant_id = %s AND email = %s", (world["tenant"], email)) == 0
        assert (
            _count(admin, "SELECT COUNT(*) FROM tenant_user WHERE tenant_id = %s AND email = %s", (world["tenant"], email)) == 0
        )
        assert [c.kwargs["event_type"] for c in enqueue.call_args_list] == ["registration_existing_account"]
