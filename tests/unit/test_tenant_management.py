"""Unit tests for services.tenant_management.service — tenant CRUD, user management, config."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ExternalServiceError,
    ResourceNotFoundError,
    UsageLimitExceededError,
    ValidationError,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _identity_not_already_taken():
    """create_tenant/create_user now pre-check that the admin email / IdP subject
    isn't already a ShipX user (`tenant_user.id` IS the subject, so one identity
    belongs to exactly one tenant). Default to "not taken" so suites don't touch
    the DB; the conflict cases patch it explicitly."""
    from services.tenant_management import service

    with patch.object(service.repo, "find_user_across_tenants", return_value=None):
        yield


def _tenant(**kw) -> dict:
    base = {
        "id": TENANT_ID,
        "company_name": "ACME Logistics",
        "status": "active",
        "subscription_tier": "business",
        "primary_contact_email": "admin@acme.com",
        "branding_config": None,
    }
    base.update(kw)
    return base


def _user(**kw) -> dict:
    base = {
        "id": "user-001",
        "tenant_id": TENANT_ID,
        "email": "staff@acme.com",
        "full_name": "Jane Staff",
        "role": "nigeria_office_staff",
        "status": "active",
        "cognito_sub": "cog-001",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# get_tenant
# ---------------------------------------------------------------------------


class TestGetTenant:
    def test_not_found_raises(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_tenant_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_tenant("nonexistent")

    def test_returns_tenant(self):
        from services.tenant_management import service

        tenant = _tenant()
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            result = service.get_tenant(TENANT_ID)

        assert result["company_name"] == "ACME Logistics"


# ---------------------------------------------------------------------------
# suspend_tenant / activate_tenant / offboard_tenant
# ---------------------------------------------------------------------------


class TestCreateTenantNotifiesOnboarding:
    """Ground-truth gap found live, reported by the user while investigating
    a separate missing notification on payment-claim rejection — asked to
    check every notification in the app. `tenant_onboarded` had a full
    template defined but no call site ever used it."""

    def _req(self):
        from services.tenant_management.models import CreateTenantRequest, InitialAdminInput, SubscriptionTier

        return CreateTenantRequest(
            company_name="ACME Logistics",
            primary_contact_email="owner@acme.com",
            primary_contact_phone="+2348012345678",
            subscription_tier=SubscriptionTier.business,
            initial_admin=InitialAdminInput(email="admin@acme.com", full_name="Jane Admin"),
        )

    def _run(self):
        from services.tenant_management import service

        tenant = _tenant(id=TENANT_ID)
        admin_user = _user(id="admin-user-001", email="admin@acme.com")
        mock_cognito = MagicMock()
        mock_cognito.create_user.return_value = "cognito-sub-001"

        return service, tenant, admin_user, mock_cognito

    def test_creating_a_tenant_notifies_the_primary_contact(self):
        service, tenant, admin_user, mock_cognito = self._run()

        with (
            patch.object(service, "get_identity_provider", return_value=mock_cognito),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications") as mock_notify,
        ):
            service.create_tenant(self._req(), actor_id="platform-admin")

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "tenant_onboarded"
        assert mock_notify.call_args.kwargs["recipient"]["email"] == "owner@acme.com"
        assert mock_notify.call_args.kwargs["template_data"]["company_name"] == "ACME Logistics"

    def test_a_notification_failure_does_not_fail_tenant_creation(self):
        service, tenant, admin_user, mock_cognito = self._run()

        with (
            patch.object(service, "get_identity_provider", return_value=mock_cognito),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications", side_effect=RuntimeError("sqs down")),
        ):
            result = service.create_tenant(self._req(), actor_id="platform-admin")

        assert result["tenant"]["id"] == TENANT_ID


class TestCreateTenantIdentityConflict:
    """`tenant_user.id` IS the IdP subject, so one identity belongs to exactly one
    tenant. Reusing an admin email must conflict cleanly — not blow up on
    tenant_user_pkey after the tenant row was already committed."""

    def _req(self):
        from services.tenant_management.models import CreateTenantRequest, InitialAdminInput, SubscriptionTier

        return CreateTenantRequest(
            company_name="ACME Logistics",
            primary_contact_email="owner@acme.com",
            primary_contact_phone="+2348012345678",
            subscription_tier=SubscriptionTier.business,
            initial_admin=InitialAdminInput(email="taken@acme.com", full_name="Jane Admin"),
        )

    def test_reused_admin_email_conflicts_before_creating_anything(self):
        from services.tenant_management import service

        with (
            patch.object(service, "get_identity_provider", return_value=MagicMock()),
            patch.object(service.repo, "find_user_across_tenants", return_value={"id": "existing-sub"}),
            patch.object(service.repo, "create_tenant") as mock_create,
        ):
            with pytest.raises(DuplicateResourceError):
                service.create_tenant(self._req(), actor_id="platform-admin")

        mock_create.assert_not_called()  # no orphan tenant

    def test_existing_idp_subject_conflicts_before_inserting_tenant_user(self):
        from services.tenant_management import service

        idp = MagicMock()
        idp.create_user.return_value = "existing-sub"
        # Email is free, but the IdP resolved to an account already attached elsewhere.
        with (
            patch.object(service, "get_identity_provider", return_value=idp),
            patch.object(service.repo, "find_user_across_tenants", side_effect=[None, {"id": "existing-sub"}]),
            patch.object(service.repo, "create_tenant", return_value=_tenant(id=TENANT_ID)),
            patch.object(service.repo, "create_tenant_user") as mock_user,
        ):
            with pytest.raises(DuplicateResourceError):
                service.create_tenant(self._req(), actor_id="platform-admin")

        mock_user.assert_not_called()


class TestCreateTenantLeadIdempotency:
    """A provision click on an already-provisioned onboarding lead must not create
    a second tenant (double-click / retry after a transient 500)."""

    def _req(self, onboarding_request_id: str):
        from services.tenant_management.models import CreateTenantRequest, InitialAdminInput, SubscriptionTier

        return CreateTenantRequest(
            company_name="ACME Logistics",
            primary_contact_email="owner@acme.com",
            primary_contact_phone="+2348012345678",
            subscription_tier=SubscriptionTier.business,
            initial_admin=InitialAdminInput(email="admin@acme.com", full_name="Jane Admin"),
            onboarding_request_id=onboarding_request_id,
        )

    def test_already_provisioned_lead_raises_and_creates_no_tenant(self):
        from services.tenant_management import service

        with (
            patch.object(service, "get_identity_provider", return_value=MagicMock()),
            patch.object(
                service.repo,
                "get_onboarding_request",
                return_value={"id": "req-1", "status": "provisioned", "tenant_id": TENANT_ID},
            ),
            patch.object(service.repo, "create_tenant") as mock_create,
        ):
            with pytest.raises(DuplicateResourceError):
                service.create_tenant(self._req("req-1"), actor_id="platform-admin")

        mock_create.assert_not_called()


class TestCreateTenantDefaultWarehouse:
    """Ground-truth gap found live, against a real paper "Goods Release
    Note": migration 041's one-time backfill gave exactly one default
    warehouse to every tenant that *already existed* at migration time —
    nothing created one for a tenant onboarded afterwards, so every release
    note a newly-onboarded tenant ever generates would resolve no warehouse
    at all and print with no branch address."""

    def _req(self):
        from services.tenant_management.models import CreateTenantRequest, InitialAdminInput, SubscriptionTier

        return CreateTenantRequest(
            company_name="ACME Logistics",
            primary_contact_email="owner@acme.com",
            primary_contact_phone="+2348012345678",
            subscription_tier=SubscriptionTier.business,
            initial_admin=InitialAdminInput(email="admin@acme.com", full_name="Jane Admin"),
        )

    def _run(self):
        from services.tenant_management import service

        tenant = _tenant(id=TENANT_ID)
        admin_user = _user(id="admin-user-001", email="admin@acme.com")
        mock_cognito = MagicMock()
        mock_cognito.create_user.return_value = "cognito-sub-001"
        return service, tenant, admin_user, mock_cognito

    def test_creating_a_tenant_creates_a_default_warehouse(self):
        service, tenant, admin_user, mock_cognito = self._run()

        with (
            patch.object(service, "get_identity_provider", return_value=mock_cognito),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications"),
            patch("services.payment_release.repository.create_warehouse") as mock_create_wh,
        ):
            service.create_tenant(self._req(), actor_id="platform-admin")

        mock_create_wh.assert_called_once()
        assert mock_create_wh.call_args.args[0] == TENANT_ID
        assert mock_create_wh.call_args.args[1]["name"] == "Main Warehouse"
        assert mock_create_wh.call_args.args[1]["is_default"] is True

    def test_a_warehouse_creation_failure_does_not_fail_tenant_creation(self):
        service, tenant, admin_user, mock_cognito = self._run()

        with (
            patch.object(service, "get_identity_provider", return_value=mock_cognito),
            patch.object(service.repo, "create_tenant", return_value=tenant),
            patch.object(service.repo, "create_tenant_user", return_value=admin_user),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications"),
            patch("services.payment_release.repository.create_warehouse", side_effect=RuntimeError("db down")),
        ):
            result = service.create_tenant(self._req(), actor_id="platform-admin")

        assert result["tenant"]["id"] == TENANT_ID


class TestSuspendTenant:
    def test_active_tenant_can_be_suspended(self):
        from services.tenant_management import service

        tenant = _tenant(status="active")
        suspended = {**tenant, "status": "suspended"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "set_tenant_status", return_value=suspended),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
        ):
            result = service.suspend_tenant(TENANT_ID, "Non-payment", actor_id="platform-admin")

        assert result["status"] == "suspended"

    def test_suspending_notifies_the_tenant(self):
        """Ground-truth gap found live, reported by the user while
        investigating a separate missing notification on payment-claim
        rejection — asked to check every notification in the app.
        `tenant_suspended` had a full template defined but no call site."""
        from services.tenant_management import service

        tenant = _tenant(status="active", primary_contact_email="owner@acme.com", primary_contact_phone="+2348012345678")
        suspended = {**tenant, "status": "suspended"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "set_tenant_status", return_value=suspended),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications") as mock_notify,
        ):
            service.suspend_tenant(TENANT_ID, "Non-payment", actor_id="platform-admin")

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "tenant_suspended"
        assert mock_notify.call_args.kwargs["recipient"]["email"] == "owner@acme.com"
        assert mock_notify.call_args.kwargs["template_data"]["reason"] == "Non-payment"

    def test_a_notification_failure_does_not_fail_suspend(self):
        from services.tenant_management import service

        tenant = _tenant(status="active")
        suspended = {**tenant, "status": "suspended"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "set_tenant_status", return_value=suspended),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.notifications.enqueue_notifications", side_effect=RuntimeError("sqs down")),
        ):
            result = service.suspend_tenant(TENANT_ID, "Non-payment", actor_id="platform-admin")

        assert result["status"] == "suspended"

    def test_already_suspended_raises(self):
        from services.tenant_management import service

        tenant = _tenant(status="suspended")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.suspend_tenant(TENANT_ID, "Reason", actor_id="platform-admin")

    def test_offboarded_tenant_cannot_be_suspended(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.suspend_tenant(TENANT_ID, "Reason", actor_id="platform-admin")


class TestActivateTenant:
    def test_suspended_tenant_can_be_activated(self):
        from services.tenant_management import service

        tenant = _tenant(status="suspended")
        activated = {**tenant, "status": "active"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "set_tenant_status", return_value=activated),
            patch.object(service.repo, "insert_platform_audit"),
        ):
            result = service.activate_tenant(TENANT_ID, actor_id="platform-admin")

        assert result["status"] == "active"

    def test_already_active_raises(self):
        from services.tenant_management import service

        tenant = _tenant(status="active")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.activate_tenant(TENANT_ID, actor_id="platform-admin")

    def test_offboarded_cannot_be_reactivated(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.activate_tenant(TENANT_ID, actor_id="platform-admin")


class TestReactivateTenant:
    def test_offboarded_tenant_can_be_reactivated(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        reactivated = {**tenant, "status": "active", "reactivated_at": "2026-03-05T00:00:00Z", "deletion_scheduled_at": None}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "reactivate_tenant", return_value=reactivated),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
        ):
            result = service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

        assert result["tenant"]["status"] == "active"
        assert result["tenant"]["deletion_scheduled_at"] is None

    def test_active_tenant_cannot_be_reactivated(self):
        from services.tenant_management import service

        tenant = _tenant(status="active")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

    def test_suspended_tenant_cannot_be_reactivated(self):
        from services.tenant_management import service

        tenant = _tenant(status="suspended")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

    def test_cache_cleared_on_reactivation(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        reactivated = {**tenant, "status": "active", "reactivated_at": "2026-03-05T00:00:00Z"}
        cache_mock = MagicMock()

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "reactivate_tenant", return_value=reactivated),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
            patch("shared.auth._tenant_status_cache", cache_mock),
        ):
            service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

        cache_mock.delete.assert_called_once_with(TENANT_ID)

    def test_notices_include_gdpr_requirements(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        reactivated = {**tenant, "status": "active", "reactivated_at": "2026-03-05T00:00:00Z"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "reactivate_tenant", return_value=reactivated),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event"),
        ):
            result = service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

        notices = result["notices"]
        assert any("CONSENT_REVERIFICATION_REQUIRED" in n for n in notices)
        assert any("ANONYMISED_DATA_IRRECOVERABLE" in n for n in notices)

    def test_reactivated_event_published(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        reactivated = {**tenant, "status": "active", "reactivated_at": "2026-03-05T00:00:00Z"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "reactivate_tenant", return_value=reactivated),
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.service.publish_event") as mock_event,
        ):
            service.reactivate_tenant(TENANT_ID, actor_id="platform-admin")

        mock_event.assert_called_once()
        assert mock_event.call_args[1]["detail_type"] == "TenantReactivated"


class TestOffboardTenant:
    def test_active_tenant_can_be_offboarded(self):
        from services.tenant_management import service

        tenant = _tenant(status="active")
        offboarded = {**tenant, "status": "offboarded"}

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "set_tenant_status", return_value=offboarded),
            patch.object(service.repo, "insert_platform_audit"),
        ):
            result = service.offboard_tenant(TENANT_ID, actor_id="platform-admin")

        assert result["status"] == "offboarded"

    def test_already_offboarded_raises(self):
        from services.tenant_management import service

        tenant = _tenant(status="offboarded")
        with patch.object(service.repo, "get_tenant_by_id", return_value=tenant):
            with pytest.raises(BusinessRuleViolationError):
                service.offboard_tenant(TENANT_ID, actor_id="platform-admin")


# ---------------------------------------------------------------------------
# Tenant config
# ---------------------------------------------------------------------------


class TestGetTenantConfig:
    def test_returns_keyed_config(self):
        from services.tenant_management import service

        rows = [
            {"config_key": "dollar_rate", "config_value": {"rate": 1550.00}},
            {"config_key": "storage_fee", "config_value": {"enabled": True}},
        ]
        with patch.object(service.repo, "get_all_configs", return_value=rows):
            result = service.get_tenant_config(TENANT_ID)

        assert result["dollar_rate"]["rate"] == 1550.00
        assert result["storage_fee"]["enabled"] is True


class TestGetDollarRate:
    """The rate is no longer typed in — get_dollar_rate reshapes whatever
    shared.fx_rate.get_effective_dollar_rate (Bybit base + tenant markup)
    returns for the API response."""

    def test_reshapes_effective_rate_for_the_api(self):
        from services.tenant_management import service

        effective = {
            "rate": Decimal("1588.20"),
            "base_rate": Decimal("1573.20"),
            "markup_type": "flat",
            "markup_value": Decimal("15"),
            "source": "bybit_p2p",
            "fetched_at": "2026-09-19T10:00:00+00:00",
            "markup_updated_at": "2026-09-18T09:00:00+00:00",
        }
        with patch.object(service, "get_effective_dollar_rate", return_value=effective):
            result = service.get_dollar_rate(TENANT_ID)

        assert result["rate"] == Decimal("1588.20")
        assert result["base_rate"] == Decimal("1573.20")
        assert result["markup_type"] == "flat"
        assert result["markup_value"] == Decimal("15")
        assert result["source"] == "bybit_p2p"
        assert result["currency_pair"] == "USD_NGN"
        assert result["effective_from"] == "2026-09-18T09:00:00+00:00"

    def test_effective_from_falls_back_to_empty_string_when_markup_never_set(self):
        from services.tenant_management import service

        effective = {
            "rate": Decimal("1550.00"),
            "base_rate": Decimal("1550.00"),
            "markup_type": "percentage",
            "markup_value": Decimal("0"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": None,
        }
        with patch.object(service, "get_effective_dollar_rate", return_value=effective):
            result = service.get_dollar_rate(TENANT_ID)

        assert result["effective_from"] == ""


class TestUpdateDollarRate:
    def test_updates_markup_and_returns_new_effective_rate_and_previous(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateDollarRateMarkupRequest

        req = UpdateDollarRateMarkupRequest(markup_type="flat", markup_value=Decimal("15"))
        before = {
            "rate": Decimal("1550.00"),
            "base_rate": Decimal("1550.00"),
            "markup_type": "percentage",
            "markup_value": Decimal("0"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "",
        }
        after = {
            "rate": Decimal("1588.20"),
            "base_rate": Decimal("1573.20"),
            "markup_type": "flat",
            "markup_value": Decimal("15"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "2026-09-19T00:00:00+00:00",
        }

        with (
            patch.object(service, "get_effective_dollar_rate", side_effect=[before, after]),
            patch.object(service.repo, "upsert_config") as mock_upsert,
            patch.object(service.repo, "append_rate_history"),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.update_dollar_rate(TENANT_ID, req, actor_id="admin")

        assert result["previous_rate"] == Decimal("1550.00")
        assert result["rate"] == Decimal("1588.20")
        assert result["markup_type"] == "flat"
        assert result["markup_value"] == Decimal("15")
        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        assert args[0] == TENANT_ID
        assert args[1] == "dollar_rate_markup"
        assert args[2]["markup_type"] == "flat"
        assert args[2]["markup_value"] == 15.0
        assert kwargs["updated_by"] == "admin"

    def test_logs_audit_with_before_after_markup(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateDollarRateMarkupRequest

        req = UpdateDollarRateMarkupRequest(markup_type="percentage", markup_value=Decimal("5"))
        before = {
            "rate": Decimal("1550.00"),
            "base_rate": Decimal("1550.00"),
            "markup_type": "percentage",
            "markup_value": Decimal("0"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "",
        }
        after = {
            "rate": Decimal("1627.50"),
            "base_rate": Decimal("1550.00"),
            "markup_type": "percentage",
            "markup_value": Decimal("5"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "2026-09-19T00:00:00+00:00",
        }

        with (
            patch.object(service, "get_effective_dollar_rate", side_effect=[before, after]),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "append_rate_history"),
            patch("services.tenant_management.service.log_audit") as mock_audit,
        ):
            service.update_dollar_rate(TENANT_ID, req, actor_id="admin")

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args[1]
        assert kwargs["action"] == "UPDATE"
        assert "dollar_rate_markup" in kwargs["before_state"]
        assert "dollar_rate_markup" in kwargs["after_state"]
        assert kwargs["after_state"]["dollar_rate_markup"]["markup_value"] == 5.0

    def test_appends_rate_history_with_the_resulting_effective_rate(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateDollarRateMarkupRequest

        req = UpdateDollarRateMarkupRequest(markup_type="flat", markup_value=Decimal("15"))
        before = {
            "rate": Decimal("1550.00"),
            "base_rate": Decimal("1550.00"),
            "markup_type": "percentage",
            "markup_value": Decimal("0"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "",
        }
        after = {
            "rate": Decimal("1588.20"),
            "base_rate": Decimal("1573.20"),
            "markup_type": "flat",
            "markup_value": Decimal("15"),
            "source": "bybit_p2p",
            "fetched_at": "t0",
            "markup_updated_at": "2026-09-19T00:00:00+00:00",
        }

        with (
            patch.object(service, "get_effective_dollar_rate", side_effect=[before, after]),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "append_rate_history") as mock_history,
            patch("services.tenant_management.service.log_audit"),
        ):
            service.update_dollar_rate(TENANT_ID, req, actor_id="admin")

        mock_history.assert_called_once()
        kwargs = mock_history.call_args.kwargs
        assert kwargs["rate_type"] == "dollar_rate"
        # RateHistoryTable/RateTrendChart on the frontend read rate_value.rate
        # as a plain number regardless of provenance — must still be there.
        assert kwargs["rate_value"]["rate"] == pytest.approx(1588.20)
        # Ground-truth bug caught live: repo.append_rate_history's real
        # json.dumps() call (mocked away above, so it can't fail here) has no
        # `default=str` and raises on a raw Decimal — get_dollar_rate returns
        # Decimal, so every value handed to it must be pre-cast to float, or
        # rate_history silently stops recording anything the moment this
        # feature ships (swallowed by update_dollar_rate's own try/except).
        # json.dumps succeeding is the real regression guard — mocking away
        # append_rate_history's body can't prove this on its own.
        json.dumps(kwargs["rate_value"])
        json.dumps(kwargs["previous_value"])


class TestUpdateCbmRateRequestValidator:
    """'flat' is not a separate code path downstream — this validator is
    what actually enforces bag_rate = bale_rate = carton_rate when the
    admin picks flat mode, so billing never has to branch on rate_mode."""

    def test_flat_mode_forces_bag_and_bale_to_match_carton(self):
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(currency="usd", rate_mode="flat", carton_rate=Decimal("45"))
        assert req.bag_rate == Decimal("45")
        assert req.bale_rate == Decimal("45")

    def test_flat_mode_ignores_a_client_supplied_bag_or_bale_rate(self):
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(
            currency="usd",
            rate_mode="flat",
            carton_rate=Decimal("45"),
            bag_rate=Decimal("99"),
            bale_rate=Decimal("1"),
        )
        assert req.bag_rate == Decimal("45")
        assert req.bale_rate == Decimal("45")

    def test_per_package_type_mode_requires_bag_and_bale(self):
        from pydantic import ValidationError

        from services.tenant_management.models import UpdateCbmRateRequest

        with pytest.raises(ValidationError):
            UpdateCbmRateRequest(currency="usd", rate_mode="per_package_type", carton_rate=Decimal("45"))

    def test_per_package_type_mode_preserves_distinct_values(self):
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(
            currency="ngn",
            rate_mode="per_package_type",
            carton_rate=Decimal("45000"),
            bag_rate=Decimal("45000"),
            bale_rate=Decimal("60000"),
        )
        assert req.carton_rate == Decimal("45000")
        assert req.bag_rate == Decimal("45000")
        assert req.bale_rate == Decimal("60000")


class TestGetCbmRate:
    def test_delegates_to_shared_cbm_rate_config(self):
        from services.tenant_management import service

        config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }
        with (
            patch.object(service, "get_cbm_rate_config", return_value=config) as mock_cfg,
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
        ):
            result = service.get_cbm_rate(TENANT_ID)

        mock_cfg.assert_called_once_with(TENANT_ID)
        for key, value in config.items():
            assert result[key] == value
        assert result["min_cbm_per_item"] == 0.1

    def test_rates_are_floats_not_decimals(self):
        """Ground-truth bug caught live: shared/responses.py's success()
        serializes anything json.dumps doesn't natively recognize via
        `default=str` — a raw Decimal here would silently become a JSON
        *string*, while update_cbm_rate's response (already float-cast)
        returns a JSON *number* for the same field. The frontend types
        these as `number` and calls `.toFixed()` on them, which crashes on
        a string — reproduced live via a real browser hitting this route
        right after a page reload (GET, not PUT)."""
        from services.tenant_management import service

        config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }
        with (
            patch.object(service, "get_cbm_rate_config", return_value=config),
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
        ):
            result = service.get_cbm_rate(TENANT_ID)

        assert isinstance(result["carton_rate"], float)
        assert isinstance(result["bag_rate"], float)
        assert isinstance(result["bale_rate"], float)
        assert isinstance(result["min_cbm_per_item"], float)


class TestUpdateCbmRate:
    def test_flat_mode_updates_all_three_rates_to_the_same_value(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(currency="usd", rate_mode="flat", carton_rate=Decimal("50"))
        current = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }

        with (
            patch.object(service, "get_cbm_rate", return_value=current),
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
            patch.object(service.repo, "upsert_config") as mock_upsert,
            patch.object(service.repo, "append_rate_history"),
            patch("services.tenant_management.service.log_audit"),
        ):
            service.update_cbm_rate(TENANT_ID, req, actor_id="admin")

        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        assert args[1] == "cbm_rate_per_unit"
        assert args[2]["carton_rate"] == 50.0
        assert args[2]["bag_rate"] == 50.0
        assert args[2]["bale_rate"] == 50.0
        assert args[2]["currency"] == "usd"
        assert args[2]["rate_mode"] == "flat"
        assert kwargs["updated_by"] == "admin"

    def test_returns_the_updated_config_in_the_get_cbm_rate_shape(self):
        """Ground-truth bug caught live: this used to return
        {**new_value, "previous_rate_usd": current.get("rate_usd")} — a
        leftover from the old single-rate shape where `current` no longer
        has a "rate_usd" key, so previous_rate_usd was always None and the
        response carried a field the frontend never even reads."""
        from services.tenant_management import service
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(
            currency="ngn",
            rate_mode="per_package_type",
            carton_rate=Decimal("45000"),
            bag_rate=Decimal("45000"),
            bale_rate=Decimal("60000"),
        )
        current = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }

        with (
            patch.object(service, "get_cbm_rate", return_value=current),
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "append_rate_history"),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.update_cbm_rate(TENANT_ID, req, actor_id="admin")

        assert "previous_rate_usd" not in result
        assert result["currency"] == "ngn"
        assert result["rate_mode"] == "per_package_type"
        assert result["carton_rate"] == 45000.0
        assert result["bag_rate"] == 45000.0
        assert result["bale_rate"] == 60000.0

    def test_per_package_type_mode_persists_distinct_rates(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(
            currency="ngn",
            rate_mode="per_package_type",
            carton_rate=Decimal("45000"),
            bag_rate=Decimal("45000"),
            bale_rate=Decimal("60000"),
        )
        current = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }

        with (
            patch.object(service, "get_cbm_rate", return_value=current),
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
            patch.object(service.repo, "upsert_config") as mock_upsert,
            patch.object(service.repo, "append_rate_history"),
            patch("services.tenant_management.service.log_audit"),
        ):
            service.update_cbm_rate(TENANT_ID, req, actor_id="admin")

        args, _ = mock_upsert.call_args
        assert args[2]["carton_rate"] == 45000.0
        assert args[2]["bag_rate"] == 45000.0
        assert args[2]["bale_rate"] == 60000.0
        assert args[2]["currency"] == "ngn"
        assert args[2]["rate_mode"] == "per_package_type"

    def test_appends_rate_history_as_json_serializable_floats(self):
        """Same class of ground-truth bug as update_dollar_rate: rate values
        here are Decimal-derived — append_rate_history's real json.dumps()
        has no default=str and raises on a raw Decimal if any value isn't
        pre-cast to float."""
        from services.tenant_management import service
        from services.tenant_management.models import UpdateCbmRateRequest

        req = UpdateCbmRateRequest(currency="usd", rate_mode="flat", carton_rate=Decimal("50"))
        current = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "t0",
        }

        with (
            patch.object(service, "get_cbm_rate", return_value=current),
            patch.object(service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
            patch.object(service.repo, "upsert_config"),
            patch.object(service.repo, "append_rate_history") as mock_history,
            patch("services.tenant_management.service.log_audit"),
        ):
            service.update_cbm_rate(TENANT_ID, req, actor_id="admin")

        kwargs = mock_history.call_args.kwargs
        assert kwargs["rate_type"] == "cbm_rate"
        json.dumps(kwargs["rate_value"])
        json.dumps(kwargs["previous_value"])


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


class TestCreateUser:
    def _setup_cognito(self):
        cognito = MagicMock()
        cognito.create_user.return_value = "cog-sub-001"
        return cognito

    def test_exceeds_tier_limit_raises(self):
        from services.tenant_management import service
        from services.tenant_management.models import CreateTenantUserRequest

        tenant = _tenant(subscription_tier="starter")  # limit = 10

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=10),
        ):
            req = CreateTenantUserRequest(email="new@acme.com", full_name="New Staff", roles=["nigeria_office_staff"])
            with pytest.raises(UsageLimitExceededError):
                service.create_user(TENANT_ID, req, actor_id="admin")

    def test_duplicate_email_raises(self):
        from services.tenant_management import service
        from services.tenant_management.models import CreateTenantUserRequest

        tenant = _tenant(subscription_tier="business")

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value={"id": "existing-001"}),
        ):
            req = CreateTenantUserRequest(email="existing@acme.com", full_name="New Staff", roles=["nigeria_office_staff"])
            with pytest.raises(DuplicateResourceError):
                service.create_user(TENANT_ID, req, actor_id="admin")

    def test_creates_user_and_provisions_cognito(self):
        from services.tenant_management import service
        from services.tenant_management.models import CreateTenantUserRequest

        tenant = _tenant(subscription_tier="business")
        user = _user()
        cognito = self._setup_cognito()

        req = CreateTenantUserRequest(email="newstaff@acme.com", full_name="New Staff", roles=["nigeria_office_staff"])

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value=user),
            patch.object(service.repo, "set_user_roles", return_value={**user, "roles": ["nigeria_office_staff"]}),
            patch.object(service.repo, "link_customer_user"),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("services.tenant_management.service.record_usage"),
        ):
            result = service.create_user(TENANT_ID, req, actor_id="admin")

        assert result["email"] == "staff@acme.com"
        cognito.create_user.assert_called_once_with(
            email="newstaff@acme.com",
            full_name="New Staff",
            tenant_id=TENANT_ID,
            role="nigeria_office_staff",
        )
        # N=1 case of the general multi-role sync — replaces the old single
        # create_group_if_not_exists/add_user_to_group pair.
        cognito.sync_user_groups.assert_called_once_with("newstaff@acme.com", TENANT_ID, {"nigeria_office_staff"})

    def test_creates_multi_role_user_seeds_tenant_user_role_and_syncs_all_groups(self):
        """A staff member invited with more than one role gets tenant_user_role
        rows for all of them (not just the primary) and every group synced."""
        from services.tenant_management import service
        from services.tenant_management.models import CreateTenantUserRequest

        tenant = _tenant(subscription_tier="business")
        user = _user(role="nigeria_office_staff")
        cognito = self._setup_cognito()

        req = CreateTenantUserRequest(
            email="multi@acme.com",
            full_name="Multi Role",
            roles=["nigeria_office_staff", "warehouse_attendant"],
            primary_role="nigeria_office_staff",
        )

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value=user),
            patch.object(service.repo, "set_user_roles") as mock_set_roles,
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("services.tenant_management.service.record_usage"),
        ):
            mock_set_roles.return_value = {**user, "roles": ["nigeria_office_staff", "warehouse_attendant"]}
            result = service.create_user(TENANT_ID, req, actor_id="admin")

        mock_set_roles.assert_called_once_with(
            TENANT_ID,
            str(user["id"]),
            ["nigeria_office_staff", "warehouse_attendant"],
            "nigeria_office_staff",
            assigned_by="admin",
        )
        cognito.sync_user_groups.assert_called_once_with(
            "multi@acme.com", TENANT_ID, {"nigeria_office_staff", "warehouse_attendant"}
        )
        assert result["roles"] == ["nigeria_office_staff", "warehouse_attendant"]

    def test_customer_role_links_customer_record_even_when_secondary(self):
        from services.tenant_management import service
        from services.tenant_management.models import CreateTenantUserRequest

        tenant = _tenant(subscription_tier="business")
        user = _user(role="nigeria_office_staff")
        cognito = self._setup_cognito()

        req = CreateTenantUserRequest(
            email="hybrid@acme.com",
            full_name="Hybrid User",
            roles=["nigeria_office_staff", "customer"],
            primary_role="nigeria_office_staff",
        )

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value=user),
            patch.object(service.repo, "set_user_roles", return_value=user),
            patch.object(service.repo, "link_customer_user") as mock_link,
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("services.tenant_management.service.record_usage"),
        ):
            service.create_user(TENANT_ID, req, actor_id="admin")

        mock_link.assert_called_once_with(TENANT_ID, "hybrid@acme.com", str(user["id"]))

    def test_starter_tier_has_limit_10(self):
        from services.tenant_management.service import TIER_USER_LIMITS

        assert TIER_USER_LIMITS["starter"] == 10

    def test_business_tier_has_limit_50(self):
        from services.tenant_management.service import TIER_USER_LIMITS

        assert TIER_USER_LIMITS["business"] == 50

    def test_enterprise_tier_has_limit_500(self):
        from services.tenant_management.service import TIER_USER_LIMITS

        assert TIER_USER_LIMITS["enterprise"] == 500


class TestDeactivateUser:
    def test_active_user_deactivated(self):
        from services.tenant_management import service

        user = _user(status="active")
        deactivated = {**user, "status": "deactivated"}
        cognito = MagicMock()

        with (
            patch.object(service.repo, "get_user_by_id", return_value=user),
            patch.object(service.repo, "set_user_status", return_value=deactivated),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")

        assert result["status"] == "deactivated"
        cognito.disable_user.assert_called_once_with("staff@acme.com")

    def test_already_deactivated_raises(self):
        from services.tenant_management import service

        user = _user(status="deactivated")
        with patch.object(service.repo, "get_user_by_id", return_value=user):
            with pytest.raises(BusinessRuleViolationError):
                service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")

    def _deactivate(self, cognito, calls: list[str] | None = None):
        """Run deactivate_user with every collaborator stubbed; `calls` records the order they run in."""
        from services.tenant_management import service

        user = _user(status="active")
        order = calls if calls is not None else []

        def _status(*args, **kwargs):
            order.append("status")
            return {**user, "status": "deactivated"}

        with (
            patch.object(service.repo, "get_user_by_id", return_value=user),
            patch.object(service.repo, "set_user_status", side_effect=_status),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch(
                "services.tenant_management.service.evict_identity_cache", side_effect=lambda uid: order.append(f"evict:{uid}")
            ),
        ):
            return service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")

    def test_sessions_are_revoked_so_the_refresh_token_cannot_renew_them(self):
        cognito = MagicMock()
        self._deactivate(cognito)
        cognito.global_sign_out.assert_called_once_with("staff@acme.com")

    def test_the_cached_identity_is_evicted_after_the_status_is_saved(self):
        """Evicting first would let a concurrent request re-cache the still-active row."""
        calls: list[str] = []
        self._deactivate(MagicMock(), calls)
        assert calls == ["status", "evict:user-001"]

    def test_a_failed_sign_out_does_not_undo_the_deactivation(self):
        """The per-request status check denies the token whether or not the IdP sign-out worked."""
        cognito = MagicMock()
        cognito.global_sign_out.side_effect = RuntimeError("idp down")
        calls: list[str] = []
        result = self._deactivate(cognito, calls)
        assert result["status"] == "deactivated"
        assert calls == ["status", "evict:user-001"]

    def test_a_failure_to_disable_the_account_changes_nothing(self):
        from services.tenant_management import service

        cognito = MagicMock()
        cognito.disable_user.side_effect = ExternalServiceError("Cognito", "unavailable")
        with (
            patch.object(service.repo, "get_user_by_id", return_value=_user(status="active")),
            patch.object(service.repo, "set_user_status") as mock_status,
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit") as mock_audit,
            patch("services.tenant_management.service.evict_identity_cache") as mock_evict,
        ):
            with pytest.raises(ExternalServiceError):
                service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")

        mock_status.assert_not_called()
        mock_evict.assert_not_called()
        mock_audit.assert_not_called()


class TestAnonymiseCustomerLogin:
    """Erasing a customer must also end their login: the tenant_user row and the IdP account are
    where their identity still lives, and the erasure clears the record's link to them."""

    @staticmethod
    def _customer(**kw) -> dict:
        base = {"id": "cust-001", "user_id": "user-cust", "name": "Ada", "email": "ada@example.com", "anonymised_at": None}
        base.update(kw)
        return base

    def _anonymise(self, customer, login, revoke=None, calls: list[str] | None = None):
        from services.tenant_management import service

        order = calls if calls is not None else []
        revoke = revoke or MagicMock(side_effect=lambda t, u: order.append("revoke") or {**u, "status": "deactivated"})
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=customer),
            patch.object(service.repo, "get_user_by_id", return_value=login),
            patch.object(service.repo, "anonymise_customer_record", side_effect=lambda t, c: order.append("erase")),
            patch.object(service, "_revoke_login", revoke),
            patch("services.tenant_management.service.log_audit") as mock_audit,
        ):
            service.anonymise_customer(TENANT_ID, "cust-001", actor_id="admin")
        return revoke, mock_audit

    def test_the_login_is_revoked_before_the_record_is_erased(self):
        calls: list[str] = []
        revoke, _ = self._anonymise(self._customer(), _user(id="user-cust", role="customer"), calls=calls)
        assert calls == ["revoke", "erase"]
        revoke.assert_called_once()

    def test_the_revocation_is_audited_with_its_reason(self):
        _, mock_audit = self._anonymise(self._customer(), _user(id="user-cust", role="customer"))
        revoked = [c.kwargs for c in mock_audit.call_args_list if c.kwargs["entity_type"] == "tenant_user"]
        assert len(revoked) == 1
        assert revoked[0]["entity_id"] == "user-cust"
        assert revoked[0]["after_state"] == {"status": "deactivated", "reason": "customer_erasure"}

    def test_a_customer_with_no_login_is_just_erased(self):
        calls: list[str] = []
        revoke, _ = self._anonymise(self._customer(user_id=None), None, calls=calls)
        assert calls == ["erase"]
        revoke.assert_not_called()

    def test_an_already_deactivated_login_is_not_revoked_again(self):
        calls: list[str] = []
        revoke, _ = self._anonymise(self._customer(), _user(id="user-cust", status="deactivated"), calls=calls)
        assert calls == ["erase"]
        revoke.assert_not_called()

    def test_a_failed_revocation_leaves_the_customer_unerased_so_it_can_be_retried(self):
        from services.tenant_management import service

        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch.object(service.repo, "get_user_by_id", return_value=_user(id="user-cust", role="customer")),
            patch.object(service.repo, "anonymise_customer_record") as mock_erase,
            patch.object(service, "_revoke_login", side_effect=ExternalServiceError("Cognito", "unavailable")),
            patch("services.tenant_management.service.log_audit"),
        ):
            with pytest.raises(ExternalServiceError):
                service.anonymise_customer(TENANT_ID, "cust-001", actor_id="admin")

        mock_erase.assert_not_called()


# ---------------------------------------------------------------------------
# update_user — roles/primary_role (multi-role staff support, Cognito group sync fix)
# ---------------------------------------------------------------------------


class TestUpdateUserRoles:
    def test_roles_update_calls_set_user_roles_and_syncs_cognito_groups(self):
        """The actual regression test for the group-sync bug: a role change
        must reach IdentityProvider.sync_user_groups, not just the DB."""
        from services.tenant_management import service

        existing = _user(id="user-001", role="nigeria_office_staff")
        updated = {**existing, "role": "warehouse_attendant", "roles": ["warehouse_attendant"]}
        cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "set_user_roles", return_value=updated) as mock_set_roles,
            patch.object(service, "get_identity_provider", return_value=cognito),
            patch("shared.audit.log_audit"),
        ):
            result = service.update_user(TENANT_ID, "user-001", {"roles": ["warehouse_attendant"]}, actor_id="admin-1")

        mock_set_roles.assert_called_once_with(
            TENANT_ID, "user-001", ["warehouse_attendant"], "warehouse_attendant", assigned_by="admin-1"
        )
        cognito.sync_user_groups.assert_called_once_with("staff@acme.com", TENANT_ID, {"warehouse_attendant"})
        cognito.update_user_attributes.assert_called_once_with(
            username="staff@acme.com", full_name=None, role="warehouse_attendant"
        )
        cognito.global_sign_out.assert_called_once_with("staff@acme.com")
        assert result["roles"] == ["warehouse_attendant"]

    def test_a_role_change_evicts_the_cached_identity_which_holds_the_old_role(self):
        from services.tenant_management import service

        existing = _user(id="user-001", role="nigeria_office_staff")
        updated = {**existing, "role": "warehouse_attendant", "roles": ["warehouse_attendant"]}

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "set_user_roles", return_value=updated),
            patch.object(service, "get_identity_provider", return_value=MagicMock()),
            patch("shared.audit.log_audit"),
            patch("services.tenant_management.service.evict_identity_cache") as mock_evict,
        ):
            service.update_user(TENANT_ID, "user-001", {"roles": ["warehouse_attendant"]}, actor_id="admin-1")

        mock_evict.assert_called_once_with("user-001")

    def test_primary_role_defaults_to_first_of_roles_when_omitted(self):
        from services.tenant_management import service

        existing = _user(id="user-001", role="nigeria_office_staff")
        updated = {**existing, "role": "nigeria_office_staff", "roles": ["nigeria_office_staff", "warehouse_attendant"]}
        cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "set_user_roles", return_value=updated) as mock_set_roles,
            patch.object(service, "get_identity_provider", return_value=cognito),
            patch("shared.audit.log_audit"),
        ):
            service.update_user(
                TENANT_ID,
                "user-001",
                {"roles": ["nigeria_office_staff", "warehouse_attendant"]},
                actor_id="admin-1",
            )

        mock_set_roles.assert_called_once_with(
            TENANT_ID,
            "user-001",
            ["nigeria_office_staff", "warehouse_attendant"],
            "nigeria_office_staff",
            assigned_by="admin-1",
        )

    def test_explicit_primary_role_honored_over_default(self):
        from services.tenant_management import service

        existing = _user(id="user-001", role="nigeria_office_staff")
        cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "set_user_roles", return_value=existing) as mock_set_roles,
            patch.object(service, "get_identity_provider", return_value=cognito),
            patch("shared.audit.log_audit"),
        ):
            service.update_user(
                TENANT_ID,
                "user-001",
                {"roles": ["nigeria_office_staff", "warehouse_attendant"], "primary_role": "warehouse_attendant"},
                actor_id="admin-1",
            )

        mock_set_roles.assert_called_once_with(
            TENANT_ID,
            "user-001",
            ["nigeria_office_staff", "warehouse_attendant"],
            "warehouse_attendant",
            assigned_by="admin-1",
        )
        cognito.update_user_attributes.assert_called_once_with(
            username="staff@acme.com", full_name=None, role="warehouse_attendant"
        )

    def test_full_name_and_roles_together_sent_in_one_cognito_call(self):
        from services.tenant_management import service

        existing = _user(id="user-001", role="nigeria_office_staff")
        cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "update_user", return_value={**existing, "full_name": "New Name"}),
            patch.object(service.repo, "set_user_roles", return_value=existing),
            patch.object(service, "get_identity_provider", return_value=cognito),
            patch("shared.audit.log_audit"),
        ):
            service.update_user(
                TENANT_ID,
                "user-001",
                {"full_name": "New Name", "roles": ["warehouse_attendant"]},
                actor_id="admin-1",
            )

        cognito.update_user_attributes.assert_called_once_with(
            username="staff@acme.com", full_name="New Name", role="warehouse_attendant"
        )

    def test_no_roles_key_leaves_cognito_groups_untouched(self):
        """A plain full_name/locale update must not call sync_user_groups or
        global_sign_out — only an explicit roles change touches Cognito groups."""
        from services.tenant_management import service

        existing = _user(id="user-001")
        cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "update_user", return_value={**existing, "full_name": "New Name"}),
            patch.object(service, "get_identity_provider", return_value=cognito),
            patch("shared.audit.log_audit"),
        ):
            service.update_user(TENANT_ID, "user-001", {"full_name": "New Name"}, actor_id="admin-1")

        cognito.sync_user_groups.assert_not_called()
        cognito.global_sign_out.assert_not_called()
        cognito.update_user_attributes.assert_called_once_with(username="staff@acme.com", full_name="New Name", role=None)


# ---------------------------------------------------------------------------
# get_customer — customer role isolation
# ---------------------------------------------------------------------------


class TestGetCustomer:
    def test_customer_role_can_access_own_record(self):
        from services.tenant_management import service

        customer = {"id": "cust-001", "user_id": "user-cust"}
        with patch.object(service.repo, "get_customer_by_id", return_value=customer):
            result = service.get_customer(
                TENANT_ID,
                "cust-001",
                requesting_user_id="user-cust",
                is_customer_role=True,
            )

        assert result["id"] == "cust-001"

    def test_customer_role_cannot_access_others_record(self):
        from services.tenant_management import service

        customer = {"id": "cust-001", "user_id": "user-other"}
        with patch.object(service.repo, "get_customer_by_id", return_value=customer):
            with pytest.raises(ResourceNotFoundError):
                service.get_customer(
                    TENANT_ID,
                    "cust-001",
                    requesting_user_id="user-cust",
                    is_customer_role=True,
                )

    def test_staff_can_access_any_customer(self):
        from services.tenant_management import service

        customer = {"id": "cust-001", "user_id": "user-other"}
        with patch.object(service.repo, "get_customer_by_id", return_value=customer):
            result = service.get_customer(
                TENANT_ID,
                "cust-001",
                requesting_user_id="user-staff",
                is_customer_role=False,  # staff
            )

        assert result["id"] == "cust-001"

    def test_not_found_raises(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_customer_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_customer(TENANT_ID, "nonexistent")


# ---------------------------------------------------------------------------
# Customer self-registration — FK regression + tenant resolution
# ---------------------------------------------------------------------------


class TestSelfRegisterCustomer:
    def _tenant(self, **kw) -> dict:
        base = {
            "id": TENANT_ID,
            "slug": "acme",
            "status": "active",
            "destination_country": "Nigeria",
        }
        base.update(kw)
        return base

    def _cognito(self) -> MagicMock:
        cognito = MagicMock()
        cognito.create_user.return_value = "cog-sub-001"
        return cognito

    def test_creates_tenant_user_and_links_customer_user_id(self):
        """Regression test for the FK bug: customer.user_id references
        tenant_user(id), never a bare Cognito sub — self_register_customer
        must create the tenant_user row and link *its* id, not cognito_sub
        directly."""
        from services.tenant_management import service
        from services.tenant_management.models import CustomerRegistrationRequest

        portal_user = {"id": "tu-001", "cognito_sub": "cog-sub-001"}
        created_customer = {"id": "cust-001", "user_id": "tu-001", "name": "Ngozi"}
        cognito = self._cognito()

        req = CustomerRegistrationRequest(name="Ngozi", email="ngozi@example.com", phone="08012345678")

        with (
            patch.object(service.repo, "get_tenant_by_slug", return_value=self._tenant()),
            patch.object(service.repo, "get_customer_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value=portal_user) as mock_create_user,
            patch.object(service.repo, "create_customer", return_value=created_customer) as mock_create_customer,
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("shared.notifications.enqueue_notifications"),
        ):
            result = service.self_register_customer(req, slug="acme")

        # tenant_user row was created for the Cognito sub (the FK the old
        # code skipped entirely).
        mock_create_user.assert_called_once()
        assert mock_create_user.call_args[0][1]["cognito_sub"] == "cog-sub-001"
        assert mock_create_user.call_args[0][1]["role"] == "customer"
        # tenant_id must be present — repository.create_tenant_user's SQL
        # requires it (%(tenant_id)s) and a missing key is a KeyError at the
        # DB layer, not caught by a mocked repo.create_tenant_user.
        assert mock_create_user.call_args[0][1]["tenant_id"] == TENANT_ID

        # customer.user_id links to the tenant_user row's id, not the raw sub.
        create_customer_data = mock_create_customer.call_args[0][1]
        assert create_customer_data["user_id"] == "tu-001"
        assert result is None, (
            "the caller must not be handed the new record: it would differ from the answer for an existing email"
        )

    def test_resolves_tenant_from_explicit_slug(self):
        from services.tenant_management import service
        from services.tenant_management.models import CustomerRegistrationRequest

        cognito = self._cognito()
        req = CustomerRegistrationRequest(name="Ngozi", email="ngozi@example.com", phone="08012345678")

        with (
            patch.object(service.repo, "get_tenant_by_slug", return_value=self._tenant()) as mock_get_slug,
            patch.object(service.repo, "get_tenant_by_custom_domain") as mock_get_domain,
            patch.object(service.repo, "get_customer_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value={"id": "tu-001"}),
            patch.object(service.repo, "create_customer", return_value={"id": "cust-001"}),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("shared.notifications.enqueue_notifications"),
        ):
            service.self_register_customer(req, slug="acme", host="api.shipx.example.com")

        mock_get_slug.assert_called_once_with("acme")
        mock_get_domain.assert_not_called()

    def test_unknown_slug_raises_not_found(self):
        from services.tenant_management import service
        from services.tenant_management.models import CustomerRegistrationRequest

        req = CustomerRegistrationRequest(name="Ngozi", email="ngozi@example.com", phone="08012345678")
        with patch.object(service.repo, "get_tenant_by_slug", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.self_register_customer(req, slug="unknown")

    # ---- an email that already has an account (audit SEC-04) -------------------------------------
    #
    # The endpoint is public. A distinct answer for an existing email lets anyone test whether a person is
    # a customer of a given shipping company, so the answer is the same and the owner is told by email.

    @staticmethod
    def _request():
        from services.tenant_management.models import CustomerRegistrationRequest

        return CustomerRegistrationRequest(name="Attacker Typed Name", email="ngozi@example.com", phone="08012345678")

    def _register_existing(self, existing_customer=None, cognito_duplicate=False, enqueue=None):
        """Run a registration for an email that already has an account; return the mocks that matter."""
        from services.tenant_management import service

        cognito = self._cognito()
        if cognito_duplicate:
            cognito.create_user.side_effect = DuplicateResourceError("user", "ngozi@example.com")
        enqueue = enqueue or MagicMock()
        with (
            patch.object(service.repo, "get_tenant_by_slug", return_value=self._tenant()),
            patch.object(service.repo, "get_customer_by_email", return_value=existing_customer),
            patch.object(service.repo, "create_tenant_user") as create_user,
            patch.object(service.repo, "create_customer") as create_customer,
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit") as audit,
            patch("services.tenant_management.service.login_url", return_value="https://app.shipx.test/login"),
            patch("shared.notifications.enqueue_notifications", enqueue),
        ):
            result = service.self_register_customer(self._request(), slug="acme", request_id="req-1")
        return result, cognito, create_user, create_customer, audit, enqueue

    def test_an_existing_customer_email_is_answered_like_a_new_one_and_creates_nothing(self):
        result, cognito, create_user, create_customer, audit, _ = self._register_existing({"id": "c1", "name": "Ngozi"})

        assert result is None
        cognito.create_user.assert_not_called()
        create_user.assert_not_called()
        create_customer.assert_not_called()
        audit.assert_not_called()

    def test_the_owner_of_an_existing_email_is_told_by_email_only(self):
        _, _, _, _, _, enqueue = self._register_existing({"id": "c1", "name": "Ngozi"})

        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        assert kwargs["event_type"] == "registration_existing_account"
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["recipient"] == {"email": "ngozi@example.com", "phone": "", "whatsapp": "", "name": "Ngozi"}
        assert kwargs["template_data"] == {"name": "Ngozi", "login_link": "https://app.shipx.test/login"}

    def test_the_name_in_the_email_is_the_accounts_not_what_the_registrant_typed(self):
        """What the registrant typed is attacker-controlled and must not be put in front of the account's owner."""
        _, _, _, _, _, enqueue = self._register_existing({"id": "c1", "name": "Ngozi"})
        assert "Attacker Typed Name" not in json.dumps(enqueue.call_args.kwargs)

    def test_an_email_that_has_an_account_elsewhere_on_the_platform_is_answered_the_same(self):
        """The identity provider is shared by every tenant, so its duplicate error leaks the same fact."""
        result, cognito, create_user, create_customer, audit, enqueue = self._register_existing(cognito_duplicate=True)

        assert result is None
        cognito.create_user.assert_called_once()
        cognito.add_user_to_group.assert_not_called()
        create_user.assert_not_called()
        create_customer.assert_not_called()
        audit.assert_not_called()
        enqueue.assert_called_once()
        assert enqueue.call_args.kwargs["template_data"]["name"] == "", "nothing is known about the other account"

    def test_a_failed_notification_does_not_change_the_answer(self):
        enqueue = MagicMock(side_effect=RuntimeError("queue unavailable"))
        result, *_ = self._register_existing({"id": "c1", "name": "Ngozi"}, enqueue=enqueue)
        assert result is None

    def test_a_missing_base_url_sends_nothing_and_still_answers_the_same(self):
        from services.tenant_management import service

        with (
            patch.object(service.repo, "get_tenant_by_slug", return_value=self._tenant()),
            patch.object(service.repo, "get_customer_by_email", return_value={"id": "c1", "name": "Ngozi"}),
            patch("services.tenant_management.service.login_url", side_effect=service.MissingBaseUrlError("no base url")),
            patch("shared.notifications.enqueue_notifications") as enqueue,
        ):
            assert service.self_register_customer(self._request(), slug="acme") is None
        enqueue.assert_not_called()

    def test_a_tenant_that_does_not_exist_is_still_reported(self):
        """Only the email's status is hidden. A bad company link is the visitor's own mistake to fix."""
        from services.tenant_management import service

        with patch.object(service.repo, "get_tenant_by_slug", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.self_register_customer(self._request(), slug="nope")


class TestSelfRegisterResponsesAreIdentical:
    """The finding's 'done when': responses for new and existing emails are identical in status and body."""

    @staticmethod
    def _post(body: dict) -> dict:
        from services.tenant_management import handler

        event = {
            "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": "/v1/register/acme"}},
            "headers": {"host": "api.shipx.test"},
            "body": json.dumps(body),
            "cookies": [],
        }
        return handler.lambda_handler(event, None)

    def _answer(self, existing: bool) -> dict:
        from services.tenant_management import service

        tenant = {"id": TENANT_ID, "status": "active", "destination_country": "Nigeria"}
        cognito = MagicMock()
        cognito.create_user.return_value = "cog-sub-001"
        with (
            patch.object(service.repo, "get_tenant_by_slug", return_value=tenant),
            patch.object(service.repo, "get_customer_by_email", return_value={"id": "c1", "name": "Ngozi"} if existing else None),
            patch.object(service.repo, "create_tenant_user", return_value={"id": "tu-001"}),
            patch.object(
                service.repo, "create_customer", return_value={"id": "c-new", "name": "Ngozi", "email": "ngozi@example.com"}
            ),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("services.tenant_management.service.login_url", return_value="https://app.shipx.test/login"),
            patch("shared.notifications.enqueue_notifications"),
        ):
            return self._post({"name": "Ngozi", "email": "ngozi@example.com", "phone": "08012345678"})

    def test_status_and_body_do_not_depend_on_whether_the_email_exists(self):
        new, existing = self._answer(existing=False), self._answer(existing=True)

        assert new["statusCode"] == existing["statusCode"] == 202
        assert new["body"] == existing["body"]

    def test_the_answer_carries_no_record_and_no_location(self):
        resp = self._answer(existing=False)

        assert "Location" not in resp["headers"]
        assert json.loads(resp["body"]) == {"data": {"status": "received"}}

    def test_the_answer_does_not_echo_the_email(self):
        assert "ngozi@example.com" not in self._answer(existing=True)["body"]


# ---------------------------------------------------------------------------
# Customer account-creation invites
# ---------------------------------------------------------------------------


class TestIssueCustomerInvite:
    def _customer(self, **kw) -> dict:
        base = {"id": "cust-001", "name": "Ngozi", "phone": "+2348012345678", "user_id": None}
        base.update(kw)
        return base

    def test_issues_invite_for_customer_without_login(self):
        from services.tenant_management import service

        invite_row = {
            "id": "inv-001",
            "expires_at": "2026-08-30T00:00:00+00:00",
            "sent_to_masked": "+23480****678",
        }
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites") as mock_delete,
            patch("shared.invites.create_invite", return_value=invite_row) as mock_create,
            patch("shared.notifications.enqueue_notifications"),
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.shipx.test"}, clear=False),
            patch("shared.notifications.primary_channel", return_value="whatsapp"),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        mock_delete.assert_called_once_with(TENANT_ID, "cust-001")
        mock_create.assert_called_once()
        assert result["id"] == "inv-001"
        # The reported channel must be the one the notification layer actually
        # uses. This was hardcoded to "sms" and kept passing after the switch to
        # WhatsApp-first, telling staff the link went out over a channel it
        # never touched.
        assert result["sent_channel"] == "whatsapp"
        assert result["delivery_suppressed"] is False

    def test_reported_channel_follows_the_notification_layer(self):
        """sent_channel is delegated, not guessed: with no WhatsApp queue
        configured the same customer must be reported as SMS."""
        from services.tenant_management import service

        invite_row = {
            "id": "inv-002",
            "expires_at": "2026-08-30T00:00:00+00:00",
            "sent_to_masked": "+23480****678",
        }
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row),
            patch("shared.notifications.enqueue_notifications"),
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.should_notify", return_value=True),
            patch.dict("os.environ", {"SQS_WHATSAPP_QUEUE_URL": ""}, clear=False),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.shipx.test"}, clear=False),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        assert result["sent_channel"] == "sms"

    def test_reports_suppressed_delivery_instead_of_claiming_it_sent(self):
        """Outside production the recipient guard blocks non-allowlisted
        contacts. Reporting sent_channel="sms" then would tell staff a message
        went out that never did, and they would not know to share the link
        another way."""
        from services.tenant_management import service

        invite_row = {
            "id": "inv-002",
            "token": "raw-token",
            "expires_at": "2026-09-03T00:00:00Z",
            "sent_to_masked": "+23480****678",
        }
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row),
            patch("shared.notifications.enqueue_notifications") as mock_enqueue,
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.shipx.test"}, clear=False),
            patch("shared.notifications.is_recipient_allowed", return_value=False),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        assert result["sent_channel"] is None
        assert result["delivery_suppressed"] is True
        # The invite itself is still valid — staff can deliver the link by hand.
        assert result["id"] == "inv-002"
        # Still enqueued: the recipient guard lives inside enqueue_notifications,
        # which is what suppresses the send. This asserts the invite path does
        # not second-guess it.
        mock_enqueue.assert_called_once()

    def test_link_is_absolute_so_it_is_clickable_in_an_email(self):
        """The reported bug: every invite link was the relative path
        "/invite/<token>".

        `CUSTOMER_PORTAL_BASE_URL` was read with a "" default and set in no
        environment — not AWS Terraform, not Azure Terraform, not .env.local —
        so the link in every invite email and WhatsApp message was unopenable.
        """
        from services.tenant_management import service

        invite_row = {"id": "inv-003", "expires_at": "2026-08-30T00:00:00+00:00", "sent_to_masked": "x"}
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row),
            patch("shared.invites.mint_token", return_value="tok-abc"),
            patch("shared.notifications.enqueue_notifications") as mock_enqueue,
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.primary_channel", return_value="whatsapp"),
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.shipx.test"}, clear=False),
            patch("services.tenant_management.service.log_audit"),
        ):
            service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        link = mock_enqueue.call_args.kwargs["template_data"]["invite_link"]
        assert link == "https://app.shipx.test/invite/tok-abc"

    def test_customer_portal_base_url_overrides_the_app_base(self):
        """A separately hosted customer portal can be pointed at without
        changing where staff activation links go."""
        from services.tenant_management import service

        invite_row = {"id": "inv-004", "expires_at": "2026-08-30T00:00:00+00:00", "sent_to_masked": "x"}
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row),
            patch("shared.invites.mint_token", return_value="tok-xyz"),
            patch("shared.notifications.enqueue_notifications") as mock_enqueue,
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.primary_channel", return_value="whatsapp"),
            patch.dict(
                "os.environ",
                {
                    "APP_BASE_URL": "https://staff.shipx.test",
                    "CUSTOMER_PORTAL_BASE_URL": "https://my.shipx.test/",
                },
                clear=False,
            ),
            patch("services.tenant_management.service.log_audit"),
        ):
            service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        # Trailing slash stripped — "https://my.shipx.test//invite/t" is a
        # different path and some routers 404 it.
        assert mock_enqueue.call_args.kwargs["template_data"]["invite_link"] == "https://my.shipx.test/invite/tok-xyz"

    def test_no_base_url_sends_nothing_and_does_not_claim_it_did(self):
        """With no base URL there is no usable link, so nothing is sent.

        The alternative — emailing "/invite/<token>" — consumes the single-use
        token, records the invite as delivered, and leaves the customer with a
        dead link and staff with no reason to follow up. That is what used to
        happen in every environment.
        """
        from services.tenant_management import service

        invite_row = {"id": "inv-005", "expires_at": "2026-08-30T00:00:00+00:00", "sent_to_masked": None}
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row) as mock_create,
            patch("shared.notifications.enqueue_notifications") as mock_enqueue,
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.primary_channel", return_value="whatsapp"),
            patch.dict(
                "os.environ",
                {"APP_BASE_URL": "", "CUSTOMER_PORTAL_BASE_URL": "", "ENTRA_REDIRECT_URI": ""},
                clear=False,
            ),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        mock_enqueue.assert_not_called()
        assert result["sent_channel"] is None
        assert result["delivery_suppressed"] is True
        # The row is still written — it is what a resend works from once the
        # base URL is configured — but with no channel recorded.
        assert mock_create.call_args.kwargs["sent_channel"] is None

    def test_relative_base_url_is_rejected_not_silently_skipped(self):
        """A base URL that is set but relative is a misconfiguration.

        Falling through to the next candidate would quietly send links to
        whichever host happened to be configured elsewhere.
        """
        from services.tenant_management import service

        invite_row = {"id": "inv-006", "expires_at": "2026-08-30T00:00:00+00:00", "sent_to_masked": None}
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch("shared.invites.delete_unconsumed_invites"),
            patch("shared.invites.create_invite", return_value=invite_row),
            patch("shared.notifications.enqueue_notifications") as mock_enqueue,
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.primary_channel", return_value="whatsapp"),
            patch.dict(
                "os.environ",
                {"CUSTOMER_PORTAL_BASE_URL": "/portal", "APP_BASE_URL": "https://app.shipx.test"},
                clear=False,
            ),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

        mock_enqueue.assert_not_called()
        assert result["delivery_suppressed"] is True

    def test_customer_already_has_account_raises(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_customer_by_id", return_value=self._customer(user_id="tu-001")):
            with pytest.raises(BusinessRuleViolationError):
                service.issue_customer_invite(TENANT_ID, "cust-001", actor_id="staff-1")

    def test_not_found_raises(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_customer_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.issue_customer_invite(TENANT_ID, "nonexistent", actor_id="staff-1")


class TestAcceptCustomerInvite:
    def _invite(self, **kw) -> dict:
        from datetime import UTC, datetime, timedelta

        base = {
            "id": "inv-001",
            "tenant_id": TENANT_ID,
            "customer_id": "cust-001",
            "consumed_at": None,
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
        base.update(kw)
        return base

    def _customer(self, **kw) -> dict:
        base = {"id": "cust-001", "name": "Ngozi", "user_id": None}
        base.update(kw)
        return base

    def test_accept_creates_tenant_user_and_links_customer(self):
        """Regression test for the FK bug on the invite-claim path too:
        accept_customer_invite must create a tenant_user row and link its id
        to customer.user_id, then mark the invite consumed."""
        from services.tenant_management import service
        from services.tenant_management.models import AcceptCustomerInviteRequest

        portal_user = {"id": "tu-002", "cognito_sub": "cog-sub-002"}
        cognito = MagicMock()
        cognito.create_user_with_password.return_value = "cog-sub-002"

        req = AcceptCustomerInviteRequest(email="ngozi@example.com", password="Sup3rSecret!")

        with (
            patch("shared.invites.get_invite_by_token", return_value=self._invite()),
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch.object(service.repo, "get_customer_by_email", return_value=None),
            patch("services.tenant_management.service.get_identity_provider", return_value=cognito),
            patch.object(service.repo, "create_tenant_user", return_value=portal_user) as mock_create_user,
            patch.object(
                service.repo,
                "update_customer",
                return_value={"id": "cust-001", "user_id": "tu-002", "email": "ngozi@example.com"},
            ) as mock_update,
            patch("shared.invites.consume_invite", return_value={"id": "inv-001"}) as mock_consume,
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.accept_customer_invite("raw-token", req)

        assert mock_create_user.call_args[0][1]["cognito_sub"] == "cog-sub-002"
        assert mock_create_user.call_args[0][1]["tenant_id"] == TENANT_ID
        assert mock_update.call_args[0][2]["user_id"] == "tu-002"
        mock_consume.assert_called_once_with(TENANT_ID, "inv-001")
        assert result["user_id"] == "tu-002"

    def test_expired_token_raises_not_found(self):
        from datetime import UTC, datetime, timedelta

        from services.tenant_management import service
        from services.tenant_management.models import AcceptCustomerInviteRequest

        expired = self._invite(expires_at=datetime.now(UTC) - timedelta(hours=1))
        req = AcceptCustomerInviteRequest(email="ngozi@example.com", password="Sup3rSecret!")
        with patch("shared.invites.get_invite_by_token", return_value=expired):
            with pytest.raises(ResourceNotFoundError):
                service.accept_customer_invite("raw-token", req)

    def test_consumed_token_raises_not_found(self):
        from datetime import UTC, datetime

        from services.tenant_management import service
        from services.tenant_management.models import AcceptCustomerInviteRequest

        consumed = self._invite(consumed_at=datetime.now(UTC))
        req = AcceptCustomerInviteRequest(email="ngozi@example.com", password="Sup3rSecret!")
        with patch("shared.invites.get_invite_by_token", return_value=consumed):
            with pytest.raises(ResourceNotFoundError):
                service.accept_customer_invite("raw-token", req)

    def test_unknown_token_raises_not_found(self):
        from services.tenant_management import service
        from services.tenant_management.models import AcceptCustomerInviteRequest

        req = AcceptCustomerInviteRequest(email="ngozi@example.com", password="Sup3rSecret!")
        with patch("shared.invites.get_invite_by_token", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.accept_customer_invite("raw-token", req)


# ---------------------------------------------------------------------------
# Customer locale (P2-1) — notification language write path
# ---------------------------------------------------------------------------


class TestUpdateCustomerLocale:
    def _customer(self) -> dict:
        return {"id": "cust-001", "user_id": "user-cust", "locale": "en", "anonymised_at": None}

    def test_valid_locale_passed_to_repo(self):
        from services.tenant_management import service

        updated = {**self._customer(), "locale": "zh"}
        with (
            patch.object(service.repo, "get_customer_by_id", return_value=self._customer()),
            patch.object(service.repo, "update_customer", return_value=updated) as mock_update,
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.update_customer(TENANT_ID, "cust-001", {"locale": "zh"}, actor_id="staff-1")

        assert mock_update.call_args[0][2] == {"locale": "zh"}
        assert result["locale"] == "zh"

    def test_unsupported_locale_rejected(self):
        from services.tenant_management import service

        with pytest.raises(BusinessRuleViolationError):
            service.update_customer(TENANT_ID, "cust-001", {"locale": "fr"}, actor_id="staff-1")

    def test_customer_self_service_allowlist_includes_locale(self):
        """The handler's restricted PATCH surface must let customers set their own language."""
        import inspect

        from services.tenant_management import handler

        source = inspect.getsource(handler._customer_routes)
        # The allowlist literal in the customer-role PATCH branch.
        assert '"locale"' in source, "customer self-service allowlist must include locale"

    def test_locale_in_customer_update_fields(self):
        from services.tenant_management.repository import _CUSTOMER_UPDATE_FIELDS

        assert "locale" in _CUSTOMER_UPDATE_FIELDS


# ---------------------------------------------------------------------------
# Default configs
# ---------------------------------------------------------------------------


class TestDefaultConfigs:
    def test_default_dollar_rate_markup_is_zero(self):
        # The base rate itself is no longer a default config value — it's
        # fetched live from Bybit (shared/fx_rate.py). A new tenant only
        # gets a default *markup* of zero (pass the base rate through
        # unchanged) so nobody's pricing silently jumps on rollout.
        from services.tenant_management.service import DEFAULT_CONFIGS

        assert DEFAULT_CONFIGS["dollar_rate_markup"]["markup_type"] == "percentage"
        assert DEFAULT_CONFIGS["dollar_rate_markup"]["markup_value"] == 0

    def test_default_grace_period_is_14_days(self):
        from services.tenant_management.service import DEFAULT_CONFIGS

        assert DEFAULT_CONFIGS["storage_fee"]["grace_period_days"] == 14

    def test_default_daily_fee_is_500(self):
        from services.tenant_management.service import DEFAULT_CONFIGS

        assert DEFAULT_CONFIGS["storage_fee"]["daily_fee_per_carton_ngn"] == 500

    def test_default_cbm_rate_is_45_flat_usd(self):
        from services.tenant_management.service import DEFAULT_CONFIGS

        cbm_cfg = DEFAULT_CONFIGS["cbm_rate_per_unit"]
        assert cbm_cfg["currency"] == "usd"
        assert cbm_cfg["rate_mode"] == "flat"
        assert cbm_cfg["carton_rate"] == 45.00
        assert cbm_cfg["bag_rate"] == 45.00
        assert cbm_cfg["bale_rate"] == 45.00

    def test_dispute_escalation_default_days_is_5(self):
        from services.tenant_management.service import DEFAULT_CONFIGS

        assert DEFAULT_CONFIGS["dispute_escalation"]["auto_escalate_days"] == 5

    def test_refund_staff_limit_is_50_usd(self):
        from services.tenant_management.service import DEFAULT_CONFIGS

        assert DEFAULT_CONFIGS["refund_threshold_usd"]["staff_limit"] == 50


# ---------------------------------------------------------------------------
# Webhook config
# ---------------------------------------------------------------------------


class TestWebhookConfig:
    def test_get_tenant_config_masks_webhook_secret(self):
        from services.tenant_management import service

        configs = [
            {
                "config_key": "webhook_config",
                "config_value": {
                    "enabled": True,
                    "url": "https://example.com/hook",
                    "secret": "super-secret",
                    "events": ["container.status_updated"],
                },
            },
        ]
        with patch.object(service.repo, "get_all_configs", return_value=configs):
            result = service.get_tenant_config(TENANT_ID)
        assert result["webhook_config"]["secret"] == "****"
        assert result["webhook_config"]["url"] == "https://example.com/hook"

    def test_get_tenant_config_no_webhook_config_unaffected(self):
        from services.tenant_management import service

        configs = [
            {"config_key": "branding_config", "config_value": {"company_name": "ACME"}},
        ]
        with patch.object(service.repo, "get_all_configs", return_value=configs):
            result = service.get_tenant_config(TENANT_ID)
        assert "webhook_config" not in result

    def test_update_tenant_config_webhook_preserves_secret(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateTenantConfigRequest, WebhookConfigRequest, WebhookEventType

        existing = {"enabled": False, "url": "", "secret": "old-secret", "events": []}
        configs = [{"config_key": "webhook_config", "config_value": existing}]
        upserted = {}

        def capture_upsert(tid, key, value, updated_by=None):
            upserted[key] = value
            return value

        with (
            patch.object(service.repo, "get_all_configs", return_value=configs),
            patch.object(service.repo, "upsert_config", side_effect=capture_upsert),
            patch("shared.audit.log_audit"),
        ):
            req = UpdateTenantConfigRequest(
                webhook_config=WebhookConfigRequest(
                    endpoint_url="https://erp.example.com/hook",
                    enabled=True,
                    events=[WebhookEventType.container_status_updated],
                )
            )
            service.update_tenant_config(TENANT_ID, req, actor_id="user-1")

        assert upserted["webhook_config"]["secret"] == "old-secret"
        assert upserted["webhook_config"]["url"] == "https://erp.example.com/hook"
        assert upserted["webhook_config"]["enabled"] is True

    def test_update_tenant_config_webhook_generates_secret_if_missing(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateTenantConfigRequest, WebhookConfigRequest

        with (
            patch.object(service.repo, "get_all_configs", return_value=[]),
            patch.object(service.repo, "upsert_config", return_value=None),
            patch("shared.audit.log_audit"),
        ):
            req = UpdateTenantConfigRequest(
                webhook_config=WebhookConfigRequest(
                    endpoint_url="https://erp.example.com/hook",
                    enabled=True,
                    events=[],
                )
            )
            # Should not raise — generates secret automatically
            service.update_tenant_config(TENANT_ID, req, actor_id="user-1")

    def test_update_tenant_config_saves_bank_transfer_config(self):
        """Ground-truth gap found live: MyBillingDetail.tsx's "Manual bank
        transfer" panel used to show one hardcoded bank account to every
        tenant's customers. This is the write path for the real per-tenant
        setting that replaces it."""
        from services.tenant_management import service
        from services.tenant_management.models import BankTransferConfigRequest, UpdateTenantConfigRequest

        upserted = {}

        def capture_upsert(tid, key, value, updated_by=None):
            upserted[key] = value
            return value

        with (
            patch.object(service.repo, "get_all_configs", return_value=[]),
            patch.object(service.repo, "upsert_config", side_effect=capture_upsert),
        ):
            req = UpdateTenantConfigRequest(
                bank_transfer_config=BankTransferConfigRequest(
                    bank_name="First Bank of Nigeria",
                    account_name="Acme Shipping Ltd",
                    account_number="3012345678",
                    sort_code="011-152352",
                    instructions="Use your invoice number as the payment description",
                )
            )
            service.update_tenant_config(TENANT_ID, req, actor_id="user-1")

        assert upserted["bank_transfer_config"]["bank_name"] == "First Bank of Nigeria"
        assert upserted["bank_transfer_config"]["account_number"] == "3012345678"

    def test_webhook_config_request_rejects_http_url(self):
        from pydantic import ValidationError

        from services.tenant_management.models import WebhookConfigRequest

        with pytest.raises(ValidationError):
            WebhookConfigRequest(endpoint_url="http://not-secure.com/hook", enabled=True, events=[])

    def test_webhook_config_request_rejects_unknown_event(self):
        from pydantic import ValidationError

        from services.tenant_management.models import WebhookConfigRequest

        with pytest.raises(ValidationError):
            WebhookConfigRequest(endpoint_url="https://example.com/hook", enabled=True, events=["unknown.event"])

    def test_rotate_webhook_secret_returns_new_secret(self):
        from services.tenant_management import service

        existing = {"enabled": True, "url": "https://example.com/hook", "secret": "old-secret", "events": []}
        configs = [{"config_key": "webhook_config", "config_value": existing}]

        with (
            patch.object(service.repo, "get_all_configs", return_value=configs),
            patch.object(service.repo, "upsert_config", return_value=None),
            patch("shared.audit.log_audit"),
        ):
            result = service.rotate_webhook_secret(TENANT_ID, actor_id="user-1")

        assert "secret" in result
        assert result["secret"] != "old-secret"
        assert len(result["secret"]) == 64  # 32 bytes hex

    def test_rotate_webhook_secret_differs_from_old(self):
        from services.tenant_management import service

        existing = {"secret": "aaaa" * 16, "enabled": True, "url": "https://example.com/hook", "events": []}
        configs = [{"config_key": "webhook_config", "config_value": existing}]
        captured = {}

        def capture_upsert(tid, key, value, updated_by=None):
            captured[key] = value
            return value

        with (
            patch.object(service.repo, "get_all_configs", return_value=configs),
            patch.object(service.repo, "upsert_config", side_effect=capture_upsert),
            patch("shared.audit.log_audit"),
        ):
            result = service.rotate_webhook_secret(TENANT_ID, actor_id="user-1")

        assert captured["webhook_config"]["secret"] == result["secret"]
        assert result["secret"] != "aaaa" * 16

    def test_test_webhook_delivery_returns_result(self):
        from services.tenant_management import service

        with (
            patch(
                "services.tenant_management.service.test_fire_tenant_webhook",
                return_value={"success": True, "status_code": 200, "error": None},
            ),
            patch("shared.audit.log_audit"),
        ):
            result = service.test_webhook_delivery(TENANT_ID, actor_id="user-1")

        assert result["success"] is True
        assert result["status_code"] == 200

    def test_test_webhook_delivery_surfaces_error(self):
        from services.tenant_management import service

        with (
            patch(
                "services.tenant_management.service.test_fire_tenant_webhook",
                return_value={"success": False, "status_code": None, "error": "Connection refused"},
            ),
            patch("shared.audit.log_audit"),
        ):
            result = service.test_webhook_delivery(TENANT_ID, actor_id="user-1")

        assert result["success"] is False
        assert "Connection refused" in result["error"]


class TestPaystackConfig:
    """Multi-tenant Paystack (2026-07-19) — each tenant connects their own
    secret key. Encrypted at rest (shared/encryption.py), never returned to
    any client (contrast with webhook_config's masked-plaintext '****')."""

    VALID_TEST_KEY = "sk_test_1ca1d9f3f5278d5014396d126483ace85f2c3afb"
    VALID_LIVE_KEY = "sk_live_9f3b8c1a2d4e5f60718293a4b5c6d7e8f9012345"

    def test_get_tenant_config_strips_encrypted_key_entirely(self):
        """Not masked to '****' like the webhook secret — removed outright.
        There's no rotate-and-show-once flow for a key the tenant supplied
        themselves, so nothing about it should ever round-trip to a client."""
        from services.tenant_management import service

        configs = [
            {
                "config_key": "paystack_config",
                "config_value": {
                    "enabled": True,
                    "secret_key_encrypted": "gAAAAA-fake-ciphertext",
                    "last4": "3afb",
                    "environment": "test",
                    "configured_by": "user-1",
                    "configured_at": "2026-07-19T00:00:00Z",
                },
            }
        ]
        with patch.object(service.repo, "get_all_configs", return_value=configs):
            result = service.get_tenant_config(TENANT_ID)

        assert "secret_key_encrypted" not in result["paystack_config"]
        assert result["paystack_config"]["last4"] == "3afb"
        assert result["paystack_config"]["environment"] == "test"

    def test_get_tenant_config_no_paystack_config_unaffected(self):
        from services.tenant_management import service

        configs = [{"config_key": "branding_config", "config_value": {"company_name": "ACME"}}]
        with patch.object(service.repo, "get_all_configs", return_value=configs):
            result = service.get_tenant_config(TENANT_ID)
        assert "paystack_config" not in result

    def test_update_paystack_config_encrypts_and_derives_metadata(self):
        from services.tenant_management import service
        from services.tenant_management.models import PaystackConfigRequest

        captured = {}

        def capture_upsert(tid, key, value, updated_by=None):
            captured[key] = value
            return value

        with (
            patch.object(service.repo, "upsert_config", side_effect=capture_upsert),
            patch("services.tenant_management.service.log_audit") as mock_audit,
        ):
            req = PaystackConfigRequest(secret_key=self.VALID_TEST_KEY)
            result = service.update_paystack_config(TENANT_ID, req, actor_id="user-1")

        assert captured["paystack_config"]["secret_key_encrypted"] is not None
        assert captured["paystack_config"]["last4"] == "3afb"
        assert captured["paystack_config"]["environment"] == "test"
        assert captured["paystack_config"]["enabled"] is True
        # The returned (client-facing) result never carries the key at all.
        assert "secret_key_encrypted" not in result
        assert result["last4"] == "3afb"
        # Audit log never sees the plaintext or ciphertext key.
        mock_audit.assert_called_once()
        after_state = mock_audit.call_args.kwargs["after_state"]
        assert "secret_key" not in str(after_state)

    def test_update_paystack_config_detects_live_environment(self):
        from services.tenant_management import service
        from services.tenant_management.models import PaystackConfigRequest

        with (
            patch.object(service.repo, "upsert_config", return_value=None),
            patch("shared.audit.log_audit"),
        ):
            req = PaystackConfigRequest(secret_key=self.VALID_LIVE_KEY)
            result = service.update_paystack_config(TENANT_ID, req, actor_id="user-1")

        assert result["environment"] == "live"

    def test_update_paystack_config_always_fully_replaces(self):
        """Unlike webhook_config, there is nothing to preserve across a
        resubmission — a new key always fully replaces the old one."""
        from services.tenant_management import service
        from services.tenant_management.models import PaystackConfigRequest

        captured = {}

        def capture_upsert(tid, key, value, updated_by=None):
            captured[key] = value
            return value

        with (
            patch.object(service.repo, "upsert_config", side_effect=capture_upsert),
            patch("shared.audit.log_audit"),
        ):
            req = PaystackConfigRequest(secret_key=self.VALID_TEST_KEY)
            service.update_paystack_config(TENANT_ID, req, actor_id="user-2")

        assert captured["paystack_config"]["configured_by"] == "user-2"

    def test_paystack_config_request_rejects_malformed_key(self):
        from pydantic import ValidationError

        from services.tenant_management.models import PaystackConfigRequest

        with pytest.raises(ValidationError):
            PaystackConfigRequest(secret_key="not-a-real-paystack-key")

    def test_paystack_config_request_rejects_short_key(self):
        from pydantic import ValidationError

        from services.tenant_management.models import PaystackConfigRequest

        with pytest.raises(ValidationError):
            PaystackConfigRequest(secret_key="sk_test_short")

    def test_delete_paystack_config_disables(self):
        from services.tenant_management import service

        with (
            patch.object(service.repo, "delete_config", return_value=None) as mock_delete,
            patch("shared.audit.log_audit"),
        ):
            result = service.delete_paystack_config(TENANT_ID, actor_id="user-1")

        mock_delete.assert_called_once_with(TENANT_ID, "paystack_config")
        assert result == {"enabled": False}

    def test_test_paystack_connection_requires_configured_key(self):
        from services.tenant_management import service
        from shared.exceptions import BusinessRuleViolationError

        with patch.object(service.repo, "get_all_configs", return_value=[]):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.test_paystack_connection(TENANT_ID, actor_id="user-1")
        assert exc_info.value.rule_id == "PAYMENT_GATEWAY_NOT_CONFIGURED"

    def test_test_paystack_connection_calls_live_api_with_decrypted_key(self):
        from services.tenant_management import service

        configs = [
            {
                "config_key": "paystack_config",
                "config_value": {
                    "enabled": True,
                    "secret_key_encrypted": self.VALID_TEST_KEY,  # dev fallback: unencrypted passthrough
                    "last4": "3afb",
                    "environment": "test",
                },
            }
        ]
        with (
            patch.object(service.repo, "get_all_configs", return_value=configs),
            patch("services.payment_release.paystack.test_connection") as mock_test,
            patch("shared.audit.log_audit"),
        ):
            result = service.test_paystack_connection(TENANT_ID, actor_id="user-1")

        mock_test.assert_called_once_with(self.VALID_TEST_KEY)
        assert result["success"] is True
        assert result["environment"] == "test"

    def test_test_paystack_connection_propagates_rejection(self):
        from services.tenant_management import service
        from shared.exceptions import ExternalServiceError

        configs = [
            {
                "config_key": "paystack_config",
                "config_value": {"enabled": True, "secret_key_encrypted": "bad-key", "last4": "0000", "environment": "test"},
            }
        ]
        with (
            patch.object(service.repo, "get_all_configs", return_value=configs),
            patch("services.payment_release.paystack.test_connection", side_effect=ExternalServiceError("Paystack", "rejected")),
        ):
            with pytest.raises(ExternalServiceError):
                service.test_paystack_connection(TENANT_ID, actor_id="user-1")


# ---------------------------------------------------------------------------
# Locale management
# ---------------------------------------------------------------------------


class TestLocale:
    def test_update_user_persists_locale(self):
        from services.tenant_management import service

        existing = _user(id="user-001", cognito_sub="cog-001")
        updated = {**existing, "locale": "zh"}

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "update_user", return_value=updated),
            patch.object(service, "get_identity_provider"),
            patch("shared.audit.log_audit"),
        ):
            result = service.update_user(TENANT_ID, "user-001", {"locale": "zh"}, actor_id="admin-1")

        assert result["locale"] == "zh"

    def test_update_user_rejects_invalid_locale(self):
        from services.tenant_management import service

        existing = _user()
        with (
            patch.object(service, "get_user", return_value=existing),
            patch("shared.audit.log_audit"),
        ):
            with pytest.raises(Exception) as exc_info:
                service.update_user(TENANT_ID, "user-001", {"locale": "fr"}, actor_id="admin-1")
        assert "UNSUPPORTED_LOCALE" in str(exc_info.value.rule_id)

    def test_update_user_locale_not_pushed_to_cognito(self):
        from services.tenant_management import service

        existing = _user(id="user-001")
        updated = {**existing, "locale": "zh"}
        mock_cognito = MagicMock()

        with (
            patch.object(service, "get_user", return_value=existing),
            patch.object(service.repo, "update_user", return_value=updated),
            patch.object(service, "get_identity_provider", return_value=mock_cognito),
            patch("shared.audit.log_audit"),
        ):
            service.update_user(TENANT_ID, "user-001", {"locale": "zh"}, actor_id="admin-1")

        # locale is a DB-only field — Cognito must not be updated
        mock_cognito.update_user_attributes.assert_not_called()

    def test_supported_locales_are_en_and_zh(self):
        from services.tenant_management.repository import _SUPPORTED_LOCALES

        assert "en" in _SUPPORTED_LOCALES
        assert "zh" in _SUPPORTED_LOCALES
        assert "fr" not in _SUPPORTED_LOCALES

    def test_notification_caller_passes_locale(self):
        """Verify tracking service passes locale= to enqueue_notifications (static check)."""
        import os

        service_path = os.path.join(os.path.dirname(__file__), "..", "..", "services", "tracking", "service.py")
        with open(service_path) as fh:
            source = fh.read()
        assert "locale=" in source, "services/tracking/service.py must pass locale= to enqueue_notifications"


# ---------------------------------------------------------------------------
# GET /v1/tenant/config — staff read access (handler-level guard)
# ---------------------------------------------------------------------------
# Widened 2026-07-11 so printable documents (packing list / release note) can
# render branding_config for every staff role that prints them. Writes and the
# webhook sub-routes must stay tenant_admin-only.


class TestTenantConfigReadAccess:
    def _event(self, method: str, path: str = "/v1/tenant/config") -> dict:
        return {
            "requestContext": {
                "requestId": "req-cfg-001",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def _ctx(self, role):
        from shared.tenant_context import TenantContext

        return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)

    def _call(self, method: str, role, path: str = "/v1/tenant/config") -> dict:
        from services.tenant_management import handler
        from shared.tenant_context import UserRole as _UserRole

        assert isinstance(role, _UserRole)
        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(role)),
            patch(
                "services.tenant_management.handler.service.get_tenant_config",
                return_value={"branding_config": {"display_name": "ACME"}},
            ),
        ):
            return handler.lambda_handler(self._event(method, path), None)

    @pytest.mark.parametrize(
        "role_name",
        ["tenant_admin", "china_office_staff", "nigeria_office_staff", "warehouse_attendant"],
    )
    def test_all_staff_roles_can_read_config(self, role_name):
        from shared.tenant_context import UserRole

        result = self._call("GET", UserRole(role_name))
        assert result["statusCode"] == 200

    def test_customer_can_read_config(self):
        """Widened 2026-09-06: MyBillingDetail.tsx's "Manual bank transfer"
        panel needs this tenant's real bank_transfer_config (ground-truth gap
        — it previously showed every tenant's customers the same hardcoded
        bank account). Safe to widen: every write and the webhook sub-routes
        stay behind the tenant_admin assert; this response already masks
        webhook_config.secret and strips paystack_config's secret key
        entirely."""
        from shared.tenant_context import UserRole

        result = self._call("GET", UserRole.CUSTOMER)
        assert result["statusCode"] == 200

    def test_write_stays_tenant_admin_only(self):
        from shared.tenant_context import UserRole

        result = self._call("PUT", UserRole.NIGERIA_OFFICE_STAFF)
        assert result["statusCode"] == 403

    def test_webhook_subroute_not_widened(self):
        from shared.tenant_context import UserRole

        result = self._call("POST", UserRole.WAREHOUSE_ATTENDANT, path="/v1/tenant/config/webhook/rotate-secret")
        assert result["statusCode"] == 403


# ---------------------------------------------------------------------------
# GET /v1/tenant/activity — tenant-scoped audit feed (audit gap B6)
# ---------------------------------------------------------------------------


class TestTenantActivityFeed:
    def _event(self, method: str, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-act-1",
                "http": {"method": method, "path": "/v1/tenant/activity"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def _ctx(self, role):
        from shared.tenant_context import TenantContext

        return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)

    def test_admin_gets_tenant_scoped_activity(self):
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        rows = [{"id": "a1", "action": "CREATE", "entity_type": "packing_list", "actor_name": "Amara"}]
        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=(rows, None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("GET"), None)

        assert resp["statusCode"] == 200
        # tenant_id is passed positionally; actor_id defaults to None
        assert mock_list.call_args[0][0] == TENANT_ID
        assert mock_list.call_args[1]["actor_id"] is None

    def test_actor_id_filter_passed_through(self):
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("GET", {"actor_id": "staff-9"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["actor_id"] == "staff-9"

    def test_entity_type_filter_passed_through(self):
        """New (2026-09-07) — the tenant-admin Activity Log page filters by
        entity_type (e.g. "payment_claim") so a money/goods audit review
        doesn't have to page through unrelated staff/config changes."""
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("GET", {"entity_type": "payment_claim"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["entity_type"] == ["payment_claim"]

    def test_entity_type_category_filter_sends_multiple_types(self):
        """A category (e.g. "Money") maps to several entity_types at once —
        comma-separated on the wire, same contract as GET /v1/containers's
        multi-status filter."""
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(
                self._event("GET", {"entity_type": "billing,payment_claim,payment_record,refund_request"}), None
            )

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["entity_type"] == ["billing", "payment_claim", "payment_record", "refund_request"]

    def test_action_filter_passed_through(self):
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("GET", {"action": "STATUS_CHANGE"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["action"] == "STATUS_CHANGE"

    def test_search_query_passed_through(self):
        """q searches actor name OR record id — pasting a UUID finds every
        action ever taken on that specific record."""
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("GET", {"q": "Emeka"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["q"] == "Emeka"

    def test_date_range_filters_passed_through(self):
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(
                self._event("GET", {"created_after": "2026-09-01", "created_before": "2026-09-07"}), None
            )

        assert resp["statusCode"] == 200
        assert mock_list.call_args[1]["created_after"] == "2026-09-01"
        assert mock_list.call_args[1]["created_before"] == "2026-09-07"

    def test_sort_direction_defaults_to_desc_and_is_overridable(self):
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=([], None, False)) as mock_list,
        ):
            handler.lambda_handler(self._event("GET"), None)
            assert mock_list.call_args[1]["sort_direction"] == "desc"

            handler.lambda_handler(self._event("GET", {"sort": "asc"}), None)
            assert mock_list.call_args[1]["sort_direction"] == "asc"

    def test_activity_rows_include_before_after_state(self):
        """Ground-truth gap found live: the original 'lean projection' (no
        before/after JSON) meant even a tenant_admin couldn't see *what*
        changed — only that something did. A money/goods audit trail needs
        the actual amounts and statuses, not just a timestamp."""
        from services.tenant_management import handler, service
        from shared.tenant_context import UserRole

        rows = [
            {
                "id": "a1",
                "action": "UPDATE",
                "entity_type": "payment_claim",
                "actor_name": "Emeka",
                "before_state": {"status": "pending"},
                "after_state": {"status": "confirmed"},
            }
        ]
        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_tenant_activity", return_value=(rows, None, False)),
        ):
            resp = handler.lambda_handler(self._event("GET"), None)

        body = json.loads(resp["body"])
        assert body["data"][0]["after_state"] == {"status": "confirmed"}

    def test_non_admin_roles_are_denied(self):
        from services.tenant_management import handler
        from shared.tenant_context import UserRole

        for role in (UserRole.NIGERIA_OFFICE_STAFF, UserRole.CHINA_OFFICE_STAFF, UserRole.CUSTOMER):
            with patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(role)):
                resp = handler.lambda_handler(self._event("GET"), None)
            assert resp["statusCode"] == 403, f"{role} should be denied"


# ---------------------------------------------------------------------------
# Charge types — wire-contract mapping (amount_ngn <-> default_amount_ngn)
# and usage counts (§4.4, B8).
# ---------------------------------------------------------------------------


class TestChargeTypes:
    def test_create_maps_amount_ngn_to_db_column_and_back(self):
        """Inbound amount_ngn stores as default_amount_ngn; response speaks amount_ngn."""
        from services.tenant_management import service

        stored = {
            "id": "ct-1",
            "name": "Customs exam",
            "description": "Port examination fee",
            "default_amount_ngn": Decimal("15000.00"),
            "is_active": True,
        }
        with (
            patch.object(service.repo, "create_charge_type", return_value=stored) as mock_create,
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.create_charge_type(
                TENANT_ID,
                {"name": "Customs exam", "amount_ngn": "15000", "description": "Port examination fee"},
                actor_id="admin-1",
            )

        # Repo received the DB column name, never the wire name.
        sent = mock_create.call_args[0][1]
        assert sent["default_amount_ngn"] == "15000"
        assert "amount_ngn" not in sent
        # Response is the wire shape.
        assert result["amount_ngn"] == Decimal("15000.00")
        assert result["usage_count"] == 0
        assert "default_amount_ngn" not in result

    def test_list_serializes_usage_count_and_amount(self):
        from services.tenant_management import service

        rows = [
            {
                "id": "ct-1",
                "name": "Customs",
                "description": None,
                "default_amount_ngn": Decimal("5000"),
                "is_active": True,
                "usage_count": 7,
            },
            {
                "id": "ct-2",
                "name": "Handling",
                "description": "x",
                "default_amount_ngn": Decimal("2500"),
                "is_active": True,
                "usage_count": 0,
            },
        ]
        with patch.object(service.repo, "list_charge_types", return_value=rows):
            out = service.list_charge_types(TENANT_ID)

        assert [c["usage_count"] for c in out] == [7, 0]
        assert out[0]["amount_ngn"] == Decimal("5000")
        assert all("default_amount_ngn" not in c for c in out)

    def test_update_maps_amount_ngn(self):
        from services.tenant_management import service

        existing = {"id": "ct-1", "name": "Customs", "default_amount_ngn": Decimal("5000"), "is_active": True}
        updated = {**existing, "default_amount_ngn": Decimal("7500")}
        with (
            patch.object(service.repo, "get_charge_type_by_id", return_value=existing),
            patch.object(service.repo, "update_charge_type", return_value=updated) as mock_update,
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.update_charge_type(TENANT_ID, "ct-1", {"amount_ngn": "7500"}, actor_id="admin-1")

        assert mock_update.call_args[0][2]["default_amount_ngn"] == "7500"
        assert result["amount_ngn"] == Decimal("7500")

    def test_deactivate_writes_audit_entry(self):
        """Ground-truth gap found while auditing log coverage: create/update
        both write an audit_log entry — deactivate was the one silently
        missing, so a tenant admin's activity view had no record a billing
        charge type was ever turned off."""
        from services.tenant_management import service

        existing = {"id": "ct-1", "name": "Customs", "default_amount_ngn": Decimal("5000"), "is_active": True}
        deactivated = {**existing, "is_active": False}
        with (
            patch.object(service.repo, "get_charge_type_by_id", return_value=existing),
            patch.object(service.repo, "update_charge_type", return_value=deactivated),
            patch("services.tenant_management.service.log_audit") as mock_audit,
        ):
            service.deactivate_charge_type(TENANT_ID, "ct-1", actor_id="admin-1")

        assert mock_audit.call_args.kwargs["entity_type"] == "charge_type"
        assert mock_audit.call_args.kwargs["after_state"]["is_active"] is False


class TestTenantActivityExcludesPlatformOnlyRecords:
    """Reported directly by the user: a platform admin's own actions on a
    tenant (impersonation) must never be visible to that tenant's own
    admins — regardless of what filters they request. Belt-and-suspenders
    on top of impersonation.py now logging to platform_audit_log instead."""

    def test_impersonation_session_excluded_even_with_no_filters(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID)

        query = mock_exec.call_args[0][1]
        assert "a.entity_type NOT IN ('impersonation_session')" in query

    def test_impersonation_session_excluded_even_if_explicitly_requested(self):
        """A tenant admin cannot bypass the exclusion by asking for it by name."""
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, entity_type=["impersonation_session"])

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "a.entity_type NOT IN ('impersonation_session')" in query
        # The explicit ANY() filter still runs too — the NOT IN exclusion
        # combines with it via AND, so the net result is correctly empty.
        assert params["entity_types"] == ["impersonation_session"]


class TestListTenantActivityFiltersRepository:
    """repository.list_tenant_activity — the actual SQL each filter produces.
    New (2026-09-07): category (multi entity_type), action, search, date
    range, and sort direction — the Activity Log page needs all five to be
    real, combinable filters, not just a single dropdown."""

    def test_multiple_entity_types_use_any(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, entity_type=["billing", "payment_claim", "refund_request"])

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "a.entity_type = ANY(%(entity_types)s)" in query
        assert params["entity_types"] == ["billing", "payment_claim", "refund_request"]

    def test_action_filter_in_query(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, action="STATUS_CHANGE")

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "a.action = %(action)s" in query
        assert params["action"] == "STATUS_CHANGE"

    def test_search_matches_actor_name_or_entity_id(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, q="Emeka")

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "u.full_name ILIKE %(q)s" in query
        assert "a.entity_id::text ILIKE %(q)s" in query
        assert params["q"] == "%Emeka%"

    def test_date_range_both_bounds(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, created_after="2026-09-01", created_before="2026-09-07")

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "a.created_at >= %(created_after)s" in query
        assert "a.created_at <= %(created_before)s" in query
        assert params["created_after"] == "2026-09-01"
        assert params["created_before"] == "2026-09-07"

    def test_sort_direction_ascending(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID, sort_direction="asc")

        query = mock_exec.call_args[0][1]
        assert "ORDER BY created_at ASC" in query

    def test_sort_direction_defaults_to_descending(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(TENANT_ID)

        query = mock_exec.call_args[0][1]
        assert "ORDER BY created_at DESC" in query

    def test_filters_combine_with_and_not_or(self):
        """All active filters must narrow the result set together — a
        category + a date range + a search term is an AND, never an OR that
        would silently widen what an admin thinks they're looking at."""
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_tenant_activity(
                TENANT_ID,
                entity_type=["payment_claim"],
                action="UPDATE",
                q="Emeka",
                created_after="2026-09-01",
            )

        query = mock_exec.call_args[0][1]
        assert "OR" not in query.split("WHERE")[1].split("ORDER BY")[0].replace(
            "u.full_name ILIKE %(q)s OR a.entity_id::text ILIKE %(q)s", ""
        )


# ---------------------------------------------------------------------------
# repository.set_user_roles / get_user_roles (migration 039 — multi-role staff)
# ---------------------------------------------------------------------------


class TestSetUserRoles:
    def test_replaces_roles_transactionally_and_mirrors_primary(self):
        """One DELETE + one INSERT per role + one UPDATE mirroring the primary
        role into tenant_user.role, all in a single execute_transaction call —
        the transactional guarantee the plan calls for."""
        from services.tenant_management import repository as repo

        mirrored_row = {"id": "user-001", "tenant_id": TENANT_ID, "role": "nigeria_office_staff"}
        with patch.object(repo, "execute_transaction") as mock_txn:
            # 1 delete + 2 inserts + 1 update = 4 results; only the update RETURNs.
            mock_txn.return_value = [None, None, None, mirrored_row]
            result = repo.set_user_roles(
                TENANT_ID,
                "user-001",
                ["nigeria_office_staff", "warehouse_attendant"],
                "nigeria_office_staff",
                assigned_by="admin-1",
            )

        assert result["role"] == "nigeria_office_staff"
        assert result["roles"] == ["nigeria_office_staff", "warehouse_attendant"]

        (call_tenant_id, queries), _kwargs = mock_txn.call_args
        assert call_tenant_id == TENANT_ID
        assert len(queries) == 4  # DELETE + 2x INSERT + UPDATE

        delete_sql, delete_params = queries[0]
        assert "DELETE FROM tenant_user_role" in delete_sql
        assert delete_params == {"tenant_id": TENANT_ID, "user_id": "user-001"}

        insert_params = [q[1] for q in queries[1:3]]
        assert {p["role"] for p in insert_params} == {"nigeria_office_staff", "warehouse_attendant"}
        primary_flags = {p["role"]: p["is_primary"] for p in insert_params}
        assert primary_flags == {"nigeria_office_staff": True, "warehouse_attendant": False}
        assert all(p["assigned_by"] == "admin-1" for p in insert_params)

        update_sql, update_params = queries[3]
        assert "UPDATE tenant_user SET role" in update_sql
        assert update_params == {"role": "nigeria_office_staff", "tenant_id": TENANT_ID, "user_id": "user-001"}

    def test_returns_none_when_user_does_not_exist(self):
        from services.tenant_management import repository as repo

        with patch.object(repo, "execute_transaction", return_value=[None, None, None]):
            result = repo.set_user_roles(TENANT_ID, "missing-user", ["customer"], "customer")

        assert result is None

    def test_get_user_roles_orders_primary_first(self):
        from services.tenant_management import repository as repo

        rows = [{"role": "nigeria_office_staff"}, {"role": "warehouse_attendant"}]
        with patch.object(repo, "execute_with_tenant", return_value=rows) as mock_read:
            result = repo.get_user_roles(TENANT_ID, "user-001")

        assert result == ["nigeria_office_staff", "warehouse_attendant"]
        query, params = mock_read.call_args[0][1], mock_read.call_args[0][2]
        assert "ORDER BY is_primary DESC" in query
        assert params == (TENANT_ID, "user-001")


class TestListUsersReadAccessWidening:
    """RecordPickupModal needs a warehouse attendant to be able to pick the
    Customer Service Officer / Accounting Officer who co-signed a pickup —
    both are just tenant_user names off GET /v1/tenant/users, previously
    tenant_admin-only like every other /v1/tenant/users method."""

    def _event(self) -> dict:
        return {
            "requestContext": {
                "requestId": "req-users-001",
                "http": {"method": "GET", "path": "/v1/tenant/users"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def _ctx(self, role):
        from shared.tenant_context import TenantContext

        return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)

    def _call(self, role) -> dict:
        from services.tenant_management import handler

        with (
            patch("services.tenant_management.handler.get_tenant_context", return_value=self._ctx(role)),
            patch("services.tenant_management.handler.service.list_users", return_value=[]),
        ):
            return handler.lambda_handler(self._event(), None)

    def test_warehouse_attendant_can_list_users(self):
        from shared.tenant_context import UserRole

        resp = self._call(UserRole.WAREHOUSE_ATTENDANT)
        assert resp["statusCode"] == 200

    def test_nigeria_office_staff_can_list_users(self):
        from shared.tenant_context import UserRole

        resp = self._call(UserRole.NIGERIA_OFFICE_STAFF)
        assert resp["statusCode"] == 200

    def test_customer_still_cannot_list_users(self):
        from shared.tenant_context import UserRole

        resp = self._call(UserRole.CUSTOMER)
        assert resp["statusCode"] == 403

    def test_china_office_staff_still_cannot_list_users(self):
        """Deliberately not widened to china_office_staff — they never touch
        release-note pickups."""
        from shared.tenant_context import UserRole

        resp = self._call(UserRole.CHINA_OFFICE_STAFF)
        assert resp["statusCode"] == 403


class TestCustomerStats:
    """GET /v1/customers/stats — tenant-wide aggregates, SQL-computed so the
    list page's stat cards stay correct past the first loaded page."""

    def test_service_delegates_with_tenant_id(self):
        from services.tenant_management import service

        stub = {"total": 70, "active": 70, "anonymised": 0, "with_whatsapp": 1, "shipments": 372}
        with patch.object(service.repo, "get_customer_stats", return_value=stub) as m:
            result = service.get_customer_stats(TENANT_ID)
        assert m.call_args[0][0] == TENANT_ID
        assert result["total"] == 70
        assert result["shipments"] == 372

    def test_repository_aggregates_and_maps_both_queries(self):
        from services.tenant_management import repository

        # First call → customer aggregate row; second call → packing_list count.
        rows = [
            [{"total": 70, "anonymised": 2, "active": 68, "with_whatsapp": 10}],
            [{"n": 372}],
        ]
        with patch.object(repository, "execute_with_tenant", side_effect=rows) as mock_exec:
            result = repository.get_customer_stats(TENANT_ID)

        assert result == {
            "total": 70,
            "anonymised": 2,
            "active": 68,
            "with_whatsapp": 10,
            "shipments": 372,
        }
        # Both queries scoped to the tenant.
        assert mock_exec.call_args_list[0][0][2] == (TENANT_ID,)
        assert mock_exec.call_args_list[1][0][2] == (TENANT_ID,)
        assert "FILTER (WHERE anonymised_at IS NOT NULL)" in mock_exec.call_args_list[0][0][1]
        assert "FROM packing_list" in mock_exec.call_args_list[1][0][1]

    def test_repository_handles_empty_tenant(self):
        from services.tenant_management import repository

        with patch.object(repository, "execute_with_tenant", side_effect=[[], []]):
            result = repository.get_customer_stats(TENANT_ID)
        assert result == {
            "total": 0,
            "anonymised": 0,
            "active": 0,
            "with_whatsapp": 0,
            "shipments": 0,
        }


class TestContainerCapacities:
    """Container capacity presets — ten read-only defaults merged with tenant
    custom rows; custom create/delete with validation (feature: capacity picker)."""

    def test_list_merges_defaults_and_custom_sorted_desc(self):
        from services.tenant_management import service

        custom = [{"id": "cap-1", "name": "Megabox", "capacity_cbm": 95, "recommended_cbm": 88}]
        with (
            patch.object(service.repo, "list_container_capacities", return_value=custom),
            patch.object(service.repo, "get_all_configs", return_value=[]),
        ):
            result = service.list_container_capacities(TENANT_ID)

        assert len(result) == len(service.DEFAULT_CONTAINER_CAPACITIES) + 1
        # Largest capacity first; the 95-CBM custom leads.
        assert result[0]["name"] == "Megabox"
        assert result[0]["is_custom"] is True
        assert result[0]["capacity_cbm"] == 95.0
        caps = [c["capacity_cbm"] for c in result]
        assert caps == sorted(caps, reverse=True)
        # Defaults carry a synthetic id and are not custom.
        assert all(c["id"].startswith("default:") for c in result if not c["is_custom"])

    def test_create_delegates_and_coerces(self):
        from services.tenant_management import service

        created = {"id": "cap-1", "name": "Megabox", "capacity_cbm": 95, "recommended_cbm": 88}
        with (
            patch.object(service.repo, "create_container_capacity", return_value=created) as m,
            patch.object(service, "log_audit"),
        ):
            result = service.create_container_capacity(
                TENANT_ID, {"name": " Megabox ", "capacity_cbm": "95", "recommended_cbm": "88"}, actor_id="u1"
            )
        sent = m.call_args[0][1]
        assert sent["name"] == "Megabox"  # trimmed
        assert sent["capacity_cbm"] == 95.0 and sent["recommended_cbm"] == 88.0
        assert result["is_custom"] is True

    def test_create_rejects_missing_name(self):
        from services.tenant_management import service

        with pytest.raises(ValidationError):
            service.create_container_capacity(TENANT_ID, {"capacity_cbm": 95}, actor_id="u1")

    def test_create_rejects_nonpositive_capacity(self):
        from services.tenant_management import service

        with pytest.raises(ValidationError):
            service.create_container_capacity(TENANT_ID, {"name": "X", "capacity_cbm": 0}, actor_id="u1")

    def test_create_rejects_recommended_over_capacity(self):
        from services.tenant_management import service

        with pytest.raises(ValidationError):
            service.create_container_capacity(TENANT_ID, {"name": "X", "capacity_cbm": 30, "recommended_cbm": 50}, actor_id="u1")

    def test_delete_default_is_rejected(self):
        from services.tenant_management import service

        with pytest.raises(BusinessRuleViolationError):
            service.delete_container_capacity(TENANT_ID, "default:40' High Cube (HC)", actor_id="u1")

    def test_delete_custom_delegates(self):
        from services.tenant_management import service

        with (
            patch.object(service.repo, "delete_container_capacity", return_value={"id": "cap-1"}) as m,
            patch.object(service, "log_audit"),
        ):
            service.delete_container_capacity(TENANT_ID, "cap-1", actor_id="u1")
        assert m.call_args[0][1] == "cap-1"

    def test_delete_missing_custom_raises_not_found(self):
        from services.tenant_management import service

        with patch.object(service.repo, "delete_container_capacity", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.delete_container_capacity(TENANT_ID, "cap-missing", actor_id="u1")


class TestUpdateContainerCapacity:
    """PATCH recommended CBM for defaults (override via tenant_config) and
    full edit for custom presets."""

    def test_update_default_persists_override(self):
        from services.tenant_management import service

        with (
            patch.object(service.repo, "get_all_configs", return_value=[]),
            patch.object(service.repo, "upsert_config", return_value=None) as m,
            patch.object(service, "log_audit"),
        ):
            result = service.update_container_capacity(
                TENANT_ID, "default:40' High Cube (HC)", {"recommended_cbm": 72}, actor_id="u1"
            )
        key, value = m.call_args[0][1], m.call_args[0][2]
        assert key == "container_capacity_overrides"
        assert value["40' High Cube (HC)"] == 72.0
        assert result["recommended_cbm"] == 72.0
        assert result["is_custom"] is False

    def test_update_default_rejects_over_capacity(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_all_configs", return_value=[]):
            with pytest.raises(ValidationError):
                service.update_container_capacity(TENANT_ID, "default:40' High Cube (HC)", {"recommended_cbm": 99}, actor_id="u1")

    def test_update_unknown_default_raises_not_found(self):
        from services.tenant_management import service

        with pytest.raises(ResourceNotFoundError):
            service.update_container_capacity(TENANT_ID, "default:Nonexistent", {"recommended_cbm": 10}, actor_id="u1")

    def test_clearing_default_override_reverts(self):
        from services.tenant_management import service

        cfg = [{"config_key": "container_capacity_overrides", "config_value": {"40' High Cube (HC)": 72.0}}]
        with (
            patch.object(service.repo, "get_all_configs", return_value=cfg),
            patch.object(service.repo, "upsert_config", return_value=None) as m,
            patch.object(service, "log_audit"),
        ):
            service.update_container_capacity(TENANT_ID, "default:40' High Cube (HC)", {"recommended_cbm": None}, actor_id="u1")
        # The override key is removed, reverting to the built-in recommended.
        assert "40' High Cube (HC)" not in m.call_args[0][2]

    def test_list_applies_default_override(self):
        from services.tenant_management import service

        cfg = [{"config_key": "container_capacity_overrides", "config_value": {"40' High Cube (HC)": 72.0}}]
        with (
            patch.object(service.repo, "list_container_capacities", return_value=[]),
            patch.object(service.repo, "get_all_configs", return_value=cfg),
        ):
            result = service.list_container_capacities(TENANT_ID)
        hc = next(c for c in result if c["name"] == "40' High Cube (HC)")
        assert hc["recommended_cbm"] == 72.0

    def test_update_custom_edits_fields(self):
        from services.tenant_management import service

        existing = {"id": "cap-1", "name": "Box", "capacity_cbm": 50, "recommended_cbm": 40}
        updated = {"id": "cap-1", "name": "Box2", "capacity_cbm": 55, "recommended_cbm": 45}
        with (
            patch.object(service.repo, "get_container_capacity_by_id", return_value=existing),
            patch.object(service.repo, "update_container_capacity", return_value=updated) as m,
            patch.object(service, "log_audit"),
        ):
            result = service.update_container_capacity(
                TENANT_ID, "cap-1", {"name": "Box2", "capacity_cbm": "55", "recommended_cbm": "45"}, actor_id="u1"
            )
        sent = m.call_args[0][2]
        assert sent == {"name": "Box2", "capacity_cbm": 55.0, "recommended_cbm": 45.0}
        assert result["is_custom"] is True

    def test_update_custom_rejects_recommended_over_capacity(self):
        from services.tenant_management import service

        existing = {"id": "cap-1", "name": "Box", "capacity_cbm": 50, "recommended_cbm": 40}
        with patch.object(service.repo, "get_container_capacity_by_id", return_value=existing):
            with pytest.raises(ValidationError):
                service.update_container_capacity(TENANT_ID, "cap-1", {"recommended_cbm": 80}, actor_id="u1")

    def test_update_missing_custom_raises_not_found(self):
        from services.tenant_management import service

        with patch.object(service.repo, "get_container_capacity_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.update_container_capacity(TENANT_ID, "cap-x", {"recommended_cbm": 10}, actor_id="u1")
