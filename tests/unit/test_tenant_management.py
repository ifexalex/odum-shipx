"""Unit tests for services.tenant_management.service — tenant CRUD, user management, config."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    UsageLimitExceededError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


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


class TestUpdateDollarRate:
    def test_updates_rate_and_returns_previous(self):
        from services.tenant_management import service

        config_rows = [
            {"config_key": "dollar_rate", "config_value": {"rate": 1500.00, "currency_pair": "USD_NGN", "effective_from": "2026-01-01"}},
        ]

        req = MagicMock()
        req.rate = Decimal("1600.00")
        req.currency_pair = "USD_NGN"

        with (
            patch.object(service.repo, "get_all_configs", return_value=config_rows),
            patch.object(service.repo, "upsert_config"),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.update_dollar_rate(TENANT_ID, req, actor_id="admin")

        assert result["previous_rate"] == 1500.00
        assert float(result["rate"]) == 1600.00

    def test_logs_audit_with_before_after(self):
        from services.tenant_management import service

        config_rows = [
            {"config_key": "dollar_rate", "config_value": {"rate": 1500.00, "currency_pair": "USD_NGN", "effective_from": ""}},
        ]

        req = MagicMock()
        req.rate = Decimal("1700.00")
        req.currency_pair = "USD_NGN"

        with (
            patch.object(service.repo, "get_all_configs", return_value=config_rows),
            patch.object(service.repo, "upsert_config"),
            patch("services.tenant_management.service.log_audit") as mock_audit,
        ):
            service.update_dollar_rate(TENANT_ID, req, actor_id="admin")

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args[1]
        assert kwargs["action"] == "UPDATE"
        assert "dollar_rate" in kwargs["before_state"]
        assert "dollar_rate" in kwargs["after_state"]


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

        tenant = _tenant(subscription_tier="starter")  # limit = 10

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=10),
        ):
            req = MagicMock()
            req.email = "new@acme.com"
            with pytest.raises(UsageLimitExceededError):
                service.create_user(TENANT_ID, req, actor_id="admin")

    def test_duplicate_email_raises(self):
        from services.tenant_management import service

        tenant = _tenant(subscription_tier="business")

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value={"id": "existing-001"}),
        ):
            req = MagicMock()
            req.email = "existing@acme.com"
            with pytest.raises(DuplicateResourceError):
                service.create_user(TENANT_ID, req, actor_id="admin")

    def test_creates_user_and_provisions_cognito(self):
        from services.tenant_management import service

        tenant = _tenant(subscription_tier="business")
        user = _user()
        cognito = self._setup_cognito()

        req = MagicMock()
        req.email = "newstaff@acme.com"
        req.full_name = "New Staff"
        req.role = MagicMock()
        req.role.value = "nigeria_office_staff"

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant),
            patch.object(service.repo, "count_active_users", return_value=5),
            patch.object(service.repo, "get_user_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value=user),
            patch("services.tenant_management.service.get_cognito_client", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
            patch("services.tenant_management.service.record_usage"),
        ):
            result = service.create_user(TENANT_ID, req, actor_id="admin")

        assert result["email"] == "staff@acme.com"
        cognito.create_user.assert_called_once()
        cognito.create_group_if_not_exists.assert_called_once()
        cognito.add_user_to_group.assert_called_once()

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
            patch("services.tenant_management.service.get_cognito_client", return_value=cognito),
            patch("services.tenant_management.service.log_audit"),
        ):
            result = service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")

        assert result["status"] == "deactivated"
        cognito.disable_user.assert_called_once_with("cog-001")

    def test_already_deactivated_raises(self):
        from services.tenant_management import service

        user = _user(status="deactivated")
        with patch.object(service.repo, "get_user_by_id", return_value=user):
            with pytest.raises(BusinessRuleViolationError):
                service.deactivate_user(TENANT_ID, "user-001", actor_id="admin")


# ---------------------------------------------------------------------------
# get_customer — customer role isolation
# ---------------------------------------------------------------------------


class TestGetCustomer:
    def test_customer_role_can_access_own_record(self):
        from services.tenant_management import service

        customer = {"id": "cust-001", "user_id": "user-cust"}
        with patch.object(service.repo, "get_customer_by_id", return_value=customer):
            result = service.get_customer(
                TENANT_ID, "cust-001",
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
                    TENANT_ID, "cust-001",
                    requesting_user_id="user-cust",
                    is_customer_role=True,
                )

    def test_staff_can_access_any_customer(self):
        from services.tenant_management import service

        customer = {"id": "cust-001", "user_id": "user-other"}
        with patch.object(service.repo, "get_customer_by_id", return_value=customer):
            result = service.get_customer(
                TENANT_ID, "cust-001",
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
# Default configs
# ---------------------------------------------------------------------------


class TestDefaultConfigs:
    def test_default_dollar_rate_is_1550(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["dollar_rate"]["rate"] == 1550.00

    def test_default_grace_period_is_14_days(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["storage_fee"]["grace_period_days"] == 14

    def test_default_daily_fee_is_500(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["storage_fee"]["daily_fee_per_carton_ngn"] == 500

    def test_default_cbm_rate_usd_is_45(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["cbm_rate_per_unit"]["rate_usd"] == 45.00

    def test_dispute_escalation_default_days_is_5(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["dispute_escalation"]["auto_escalate_days"] == 5

    def test_refund_staff_limit_is_50_usd(self):
        from services.tenant_management.service import DEFAULT_CONFIGS
        assert DEFAULT_CONFIGS["refund_threshold_usd"]["staff_limit"] == 50
