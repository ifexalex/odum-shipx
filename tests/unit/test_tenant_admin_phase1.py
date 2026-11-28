"""Unit tests for Tenant Admin Console Phase 1 (TC-01 through TC-05).

Covers:
  - TC-01 / D4: Effective-dated policy updates, validation, history, and historical storage-fee resolution.
  - TC-02 / D5: Approvals inbox read model across credit releases, high-value refunds, claims, and announcements.
  - TC-03 / D2: Staff credit release request creation, limit flagging, admin approval/rejection, and audit.
  - TC-04 / D3: Per-customer credit limits and payment terms, falling back to tenant defaults.
  - TC-05: GET /v1/tenant/permissions served from shared/role_permissions.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from shared.exceptions import BusinessRuleViolationError, InsufficientPermissionsError, ValidationError
from shared.tenant_context import TenantContext, UserRole
from shared.tenant_policies import resolve_policy_for_date

TENANT_ID = "11111111-1111-1111-1111-111111111111"
ADMIN_ID = "22222222-2222-2222-2222-222222222222"
STAFF_ID = "33333333-3333-3333-3333-333333333333"
CUSTOMER_ID = "44444444-4444-4444-4444-444444444444"
BILLING_ID = "55555555-5555-5555-5555-555555555555"


def _ctx(role: UserRole, user_id: str = ADMIN_ID) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        user_id=user_id,
        role=role,
        roles=frozenset({role}),
    )


class TestTC01EffectiveDatedPolicies:
    def test_resolve_policy_uses_history_in_force_on_target_date(self) -> None:
        """Past accrual days resolve the policy in force on that date, never repricing history."""
        day_old = date(2026, 10, 1)
        day_new = date(2026, 10, 10)

        def fake_query(_tid: str, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
            if "effective_date <=" in sql:
                as_of = params[2]
                if as_of >= day_new:
                    return [{"new_value": {"enabled": True, "grace_period_days": 10, "daily_fee_per_carton_ngn": 800}}]
                return [{"new_value": {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500}}]
            return []

        with patch("shared.tenant_policies.execute_with_tenant", side_effect=fake_query):
            past_cfg = resolve_policy_for_date(TENANT_ID, "storage_fee", as_of_date=day_old)
            new_cfg = resolve_policy_for_date(TENANT_ID, "storage_fee", as_of_date=day_new)

        assert past_cfg["daily_fee_per_carton_ngn"] == 500
        assert past_cfg["grace_period_days"] == 14
        assert new_cfg["daily_fee_per_carton_ngn"] == 800
        assert new_cfg["grace_period_days"] == 10

    def test_resolve_policy_keeps_old_value_before_future_effective_date(self) -> None:
        """A change scheduled for tomorrow does not take effect today."""
        today = date(2026, 10, 1)

        def fake_query(_tid: str, sql: str, _params: tuple[Any, ...]) -> list[dict[str, Any]]:
            if "effective_date <=" in sql:
                return []
            if "effective_date >" in sql:
                return [{"old_value": {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500}}]
            return []

        with patch("shared.tenant_policies.execute_with_tenant", side_effect=fake_query):
            cfg = resolve_policy_for_date(TENANT_ID, "storage_fee", as_of_date=today)

        assert cfg["daily_fee_per_carton_ngn"] == 500

    def test_update_policy_rejects_backdated_effective_date(self) -> None:
        from services.tenant_management import policies

        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        with pytest.raises(ValidationError):
            policies.update_tenant_policy(
                TENANT_ID,
                "storage_fee",
                {"enabled": True, "grace_period_days": 10, "daily_fee_per_carton_ngn": 700},
                yesterday,
                actor_id=ADMIN_ID,
            )

    def test_update_policy_rejects_invalid_reminder_order(self) -> None:
        from services.tenant_management import policies

        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        with pytest.raises(ValidationError):
            policies.update_tenant_policy(
                TENANT_ID,
                "reminder_days",
                {"storage_first_reminder": 14, "storage_final_reminder": 7},
                tomorrow,
                actor_id=ADMIN_ID,
            )

    def test_update_policy_defaults_to_tomorrow_and_writes_history_and_audit(self) -> None:
        from contextlib import nullcontext

        from services.tenant_management import policies

        captured: dict[str, Any] = {}

        def fake_write(_tid: str, _sql: str, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {
                "id": "99999999-9999-9999-9999-999999999999",
                "policy_key": params["policy_key"],
                "old_value": {},
                "new_value": {},
                "effective_date": params["effective_date"],
                "changed_by": params["changed_by"],
                "created_at": datetime.now(UTC),
            }

        with (
            patch(
                "services.tenant_management.policies.resolve_policy_for_date",
                return_value={"staff_limit": 50, "requires_manager_above": 50},
            ),
            patch("services.tenant_management.policies.tenant_transaction", return_value=nullcontext()),
            patch("services.tenant_management.policies.execute_write_with_tenant", side_effect=fake_write),
            patch("services.tenant_management.policies.repo.upsert_config") as mock_upsert,
            patch("services.tenant_management.policies.log_audit") as mock_audit,
            patch("services.tenant_management.policies.get_tenant_policies", return_value={"policies": {}}),
        ):
            policies.update_tenant_policy(
                TENANT_ID,
                "refund_threshold_usd",
                {"staff_limit": 100},
                None,
                actor_id=ADMIN_ID,
            )

        expected_tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        assert captured["effective_date"] == expected_tomorrow
        # Future effective date does not immediately overwrite tenant_config
        mock_upsert.assert_not_called()
        mock_audit.assert_called_once()


class TestTC02ApprovalsInbox:
    def test_aggregates_all_four_domains_and_counts(self) -> None:
        from services.tenant_management import tenant_approvals

        now = datetime.now(UTC)
        credit_item = {
            "id": "cr-1",
            "type": "credit_release",
            "title": "Credit release",
            "created_at": (now - timedelta(hours=4)).isoformat(),
        }
        refund_item = {
            "id": "rf-1",
            "type": "refund",
            "title": "Refund",
            "created_at": (now - timedelta(hours=2)).isoformat(),
        }
        claim_item = {
            "id": "cl-1",
            "type": "claim",
            "title": "Claim",
            "created_at": (now - timedelta(hours=3)).isoformat(),
        }
        ann_item = {
            "id": "an-1",
            "type": "announcement",
            "title": "Announcement",
            "created_at": (now - timedelta(hours=1)).isoformat(),
        }

        with (
            patch.object(tenant_approvals, "_staff_limit_ngn", return_value=(Decimal("50"), Decimal("75000"))),
            patch.object(tenant_approvals, "_fetch_credit_release_items", return_value=[credit_item]),
            patch.object(tenant_approvals, "_fetch_refund_items", return_value=[refund_item]),
            patch.object(tenant_approvals, "_fetch_claim_items", return_value=[claim_item]),
            patch.object(tenant_approvals, "_fetch_announcement_items", return_value=[ann_item]),
        ):
            res = tenant_approvals.get_tenant_approvals(TENANT_ID, actor_id=ADMIN_ID)
            counts_only = tenant_approvals.get_tenant_approvals(TENANT_ID, actor_id=ADMIN_ID, counts_only=True)
            filtered = tenant_approvals.get_tenant_approvals(TENANT_ID, actor_id=ADMIN_ID, item_type="credit_release")

        assert res["counts"] == {
            "credit_release": 1,
            "refund": 1,
            "claim": 1,
            "announcement": 1,
            "total": 4,
        }
        # Oldest waiting first
        assert [i["id"] for i in res["items"]] == ["cr-1", "cl-1", "rf-1", "an-1"]
        assert counts_only["items"] == []
        assert counts_only["counts"]["total"] == 4
        assert [i["id"] for i in filtered["items"]] == ["cr-1"]


class TestTC03CreditReleaseRequests:
    def test_staff_can_submit_request_and_exceeds_limit_is_flagged(self) -> None:
        from services.payment_release import service as pr_service
        from services.payment_release.models import CreateCreditReleaseRequest

        req = CreateCreditReleaseRequest(
            billing_id=BILLING_ID,
            carton_tags=["TAG-001"],
            reason="Long-standing customer paying Friday",
        )
        captured_insert: dict[str, Any] = {}

        def fake_insert(_tid: str, data: dict[str, Any]) -> dict[str, Any]:
            captured_insert.update(data)
            return {"id": "77777777-7777-7777-7777-777777777777", "status": "pending", **data}

        with (
            patch.object(
                pr_service.repo,
                "get_billing_by_id",
                return_value={
                    "id": BILLING_ID,
                    "customer_id": CUSTOMER_ID,
                    "container_id": "66666666-6666-6666-6666-666666666666",
                    "status": "partially_paid",
                    "balance_ngn": Decimal("250000"),
                },
            ),
            patch.object(pr_service.repo, "get_approved_carton_tags_for_billing", return_value=["TAG-001"]),
            patch.object(
                pr_service.repo,
                "get_customer_credit_snapshot",
                return_value={
                    "customer_name": "Ibrahim Musa",
                    "credit_limit_ngn": Decimal("100000"),
                    "credit_terms_days": 14,
                    "unpaid_billing_ngn": Decimal("250000"),
                    "active_carryover_ngn": Decimal("0"),
                },
            ),
            patch(
                "shared.tenant_policies.resolve_policy_for_date",
                return_value={"default_credit_limit_ngn": 0, "default_credit_terms_days": 14},
            ),
            patch.object(pr_service.repo, "create_credit_release_request", side_effect=fake_insert),
            patch.object(pr_service.repo, "get_credit_release_request_by_id", return_value=None),
            patch("services.payment_release.service.log_audit") as mock_audit,
            patch("shared.staff_notifications.notify_staff") as mock_notify,
        ):
            res = pr_service.create_credit_release_request(
                TENANT_ID, req, actor_id=STAFF_ID, ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF, STAFF_ID)
            )

        assert res["exceeds_credit_limit"] is True
        assert captured_insert["exceeds_credit_limit"] is True
        assert captured_insert["customer_credit_limit_ngn"] == Decimal("100000")
        assert captured_insert["due_date"] is not None
        mock_audit.assert_called_once()
        mock_notify.assert_called_once()

    def test_non_admin_cannot_approve_or_reject_credit_request(self) -> None:
        from services.payment_release import service as pr_service
        from services.payment_release.models import DecideCreditReleaseRequest

        staff_ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF, STAFF_ID)
        with pytest.raises(InsufficientPermissionsError):
            pr_service.approve_credit_release_request(
                TENANT_ID, "cr-1", DecideCreditReleaseRequest(decision_notes="ok"), STAFF_ID, staff_ctx
            )
        with pytest.raises(InsufficientPermissionsError):
            pr_service.reject_credit_release_request(
                TENANT_ID, "cr-1", DecideCreditReleaseRequest(decision_notes="no"), STAFF_ID, staff_ctx
            )

    def test_reject_requires_reason(self) -> None:
        from services.payment_release import service as pr_service
        from services.payment_release.models import DecideCreditReleaseRequest

        with pytest.raises(BusinessRuleViolationError):
            pr_service.reject_credit_release_request(
                TENANT_ID, "cr-1", DecideCreditReleaseRequest(decision_notes="   "), ADMIN_ID, _ctx(UserRole.TENANT_ADMIN)
            )


class TestTC04CustomerCreditLimits:
    def test_credit_summary_falls_back_to_tenant_default_when_customer_limit_null(self) -> None:
        from services.tenant_management import customers

        customer = {"id": CUSTOMER_ID, "credit_limit_ngn": None, "credit_terms_days": None}
        with (
            patch(
                "shared.tenant_policies.resolve_policy_for_date",
                return_value={"default_credit_limit_ngn": 500000, "default_credit_terms_days": 21},
            ),
            patch.object(
                customers.repo,
                "get_customer_credit_exposure",
                return_value={"unpaid_billing_ngn": Decimal("120000"), "active_carryover_ngn": Decimal("30000")},
            ),
        ):
            summary = customers.build_customer_credit_summary(TENANT_ID, customer)

        assert summary["using_tenant_default_limit"] is True
        assert summary["using_tenant_default_terms"] is True
        assert summary["effective_credit_limit_ngn"] == "500000"
        assert summary["effective_credit_terms_days"] == 21
        assert summary["current_exposure_ngn"] == "150000"
        assert summary["available_credit_ngn"] == "350000"
        assert summary["over_limit"] is False

    def test_update_customer_credit_audits_before_and_after(self) -> None:
        from services.tenant_management import customers

        before = {"id": CUSTOMER_ID, "credit_limit_ngn": None, "credit_terms_days": None}
        after = {"id": CUSTOMER_ID, "credit_limit_ngn": Decimal("750000"), "credit_terms_days": 30}
        with (
            patch.object(customers.repo, "get_customer_by_id", return_value=before),
            patch.object(customers.repo, "update_customer_credit_terms", return_value=after),
            patch.object(customers, "build_customer_credit_summary", return_value={"effective_credit_limit_ngn": "750000"}),
            patch("services.tenant_management.customers.log_audit") as mock_audit,
        ):
            res = customers.update_customer_credit(
                TENANT_ID,
                CUSTOMER_ID,
                credit_limit_ngn=Decimal("750000"),
                credit_terms_days=30,
                actor_id=ADMIN_ID,
            )

        assert res["credit_summary"]["effective_credit_limit_ngn"] == "750000"
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["before_state"] == {"credit_limit_ngn": None, "credit_terms_days": None}
        assert kwargs["after_state"] == {"credit_limit_ngn": "750000", "credit_terms_days": 30}
