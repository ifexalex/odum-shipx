"""Regression unit tests for the full business-logic & security audit remediation (Batches D, A, B, C)."""

import hashlib
import hmac
import json
from contextlib import nullcontext
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    BusinessRuleViolationError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BILLING_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CUSTOMER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CONTAINER_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def _ctx(
    role: UserRole = UserRole.TENANT_ADMIN,
    roles: frozenset[UserRole] | None = None,
) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        role=role,
        roles=roles or frozenset({role}),
    )


# ---------------------------------------------------------------------------
# Batch D: Auth, Tenancy, Shared Core & Tenant Management
# ---------------------------------------------------------------------------


class TestBatchDCoreAndTenancy:
    @pytest.mark.parametrize(
        "unsafe_url",
        [
            "https://localhost./hook",
            "https://169.254.169.254./latest/meta-data",
            "https://100.64.0.1/internal",
            "https://198.18.0.1/bench",
            "http://hooks.example.com/webhook",
        ],
    )
    def test_url_safety_blocks_trailing_dot_cgnat_and_benchmark_ips(self, unsafe_url: str) -> None:
        from shared.url_safety import UnsafeUrlError, validate_public_https_url

        with pytest.raises(UnsafeUrlError):
            validate_public_https_url(unsafe_url)

    def test_idempotency_extracts_case_insensitive_header_and_scopes_storage_key(self) -> None:
        from shared.idempotency import _is_non_cacheable_path, _scoped_storage_key, get_idempotency_key

        event = {"headers": {"Idempotency-Key": "  idem-123  "}}
        assert get_idempotency_key(event) == "idem-123"

        key_a = _scoped_storage_key("idem-123", actor_id="u1", method="POST", path="/v1/refunds")
        key_b = _scoped_storage_key("idem-123", actor_id="u1", method="POST", path="/v1/claims")
        key_c = _scoped_storage_key("idem-123", actor_id="u2", method="POST", path="/v1/refunds")
        assert key_a != key_b
        assert key_a != key_c
        assert _is_non_cacheable_path("/v1/tenant/config/webhook/rotate-secret") is True
        assert _is_non_cacheable_path(f"/v1/release-notes/{BILLING_ID}/pickup-code") is True

    def test_rate_models_reject_nan_and_infinity(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        from services.tenant_management.models import (
            CbmRateCurrency,
            CbmRateMode,
            MarkupType,
            UpdateCbmRateRequest,
            UpdateDollarRateMarkupRequest,
        )

        with pytest.raises(PydanticValidationError):
            UpdateCbmRateRequest(
                currency=CbmRateCurrency.usd,
                rate_mode=CbmRateMode.flat,
                carton_rate=Decimal("NaN"),
            )
        with pytest.raises(PydanticValidationError):
            UpdateDollarRateMarkupRequest(
                markup_type=MarkupType.percentage,
                markup_value=Decimal("Infinity"),
            )


# ---------------------------------------------------------------------------
# Batch A: Refunds, Claims, Billing & Payment Release
# ---------------------------------------------------------------------------


class TestBatchAFinancialLogic:
    def test_adjust_billing_preserves_cancelled_waived_and_settles_overpayment(self) -> None:
        from shared.billing_money import adjust_billing, settle_overpayment_refund

        with patch("shared.billing_money.execute_write_with_tenant", return_value={"id": BILLING_ID}) as mock_write:
            adjust_billing(TENANT_ID, BILLING_ID, Decimal("-500"))
        sql = mock_write.call_args.args[1]
        assert "WHEN b.status IN ('unpaid', 'partially_paid', 'paid', 'overpaid') THEN" in sql
        assert "ELSE b.status" in sql

        with patch("shared.billing_money.execute_write_with_tenant", return_value={"id": BILLING_ID}) as mock_settle:
            settle_overpayment_refund(TENANT_ID, BILLING_ID, Decimal("1000"))
        settle_sql = mock_settle.call_args.args[1]
        assert "SET amount_paid_ngn = b.amount_paid_ngn - locked.settle_amount" in settle_sql

    def test_refund_create_caps_cumulative_refunds_at_overpaid_and_paid_amounts(self) -> None:
        from services.refunds import service as refund_service
        from services.refunds.models import CreateRefundRequest, CustomerChoice, RefundType

        req = CreateRefundRequest(
            billing_id=BILLING_ID,
            customer_id=CUSTOMER_ID,
            amount_requested_ngn=Decimal("6000"),
            notes="Overpayment refund",
            refund_type=RefundType.overpayment,
            customer_choice=CustomerChoice.immediate_refund,
            account_number="0123456789",
            bank_name="GTBank",
            account_name="Ngozi",
        )
        billing_row = {
            "id": BILLING_ID,
            "customer_id": CUSTOMER_ID,
            "status": "overpaid",
            "amount_paid_ngn": Decimal("15000"),
            "total_ngn": Decimal("10000"),
        }
        with (
            patch.object(refund_service.repo, "get_billing_by_id", return_value=billing_row),
            patch.object(refund_service.repo, "sum_active_refunds_for_billing", return_value=Decimal("2000")),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                refund_service.create_refund(TENANT_ID, req, USER_ID, _ctx(UserRole.NIGERIA_OFFICE_STAFF))
            assert exc_info.value.rule_id == "REFUND_EXCEEDS_OVERPAYMENT"

    def test_claim_resolve_rejects_discount_on_cancelled_invoice_and_requires_positive_amount(self) -> None:
        from services.claims import service as claims_service
        from services.claims.models import ResolutionType, ResolveClaimRequest

        req = ResolveClaimRequest(
            resolution_type=ResolutionType.discount,
            amount_ngn=Decimal("5000"),
            reason="Damaged outer carton",
        )
        claim_row = {
            "id": "claim-1",
            "status": "inspection_complete",
            "customer_id": CUSTOMER_ID,
            "container_id": CONTAINER_ID,
            "billing_id": BILLING_ID,
        }
        cancelled_billing = {"id": BILLING_ID, "status": "cancelled", "total_ngn": Decimal("20000")}
        with (
            patch.object(claims_service.repo, "get_damage_claim_by_id", return_value=claim_row),
            patch.object(claims_service.repo, "get_billing_by_id", return_value=cancelled_billing),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                claims_service.resolve_claim(TENANT_ID, "claim-1", req, USER_ID, _ctx(UserRole.TENANT_ADMIN))
            assert exc_info.value.rule_id == "INVALID_BILLING_STATUS"

    def test_carryover_exempt_rejects_already_applied_carryover(self) -> None:
        from services.billing import service as billing_service
        from services.billing.models import ExemptCarryoverRequest

        req = ExemptCarryoverRequest(exemption_reason="Goodwill waiver")
        carryover = {"id": "co-1", "status": "applied", "amount_ngn": Decimal("5000")}
        with (
            patch.object(billing_service, "tenant_transaction", return_value=nullcontext()),
            patch.object(billing_service.repo, "get_carryover_by_id", return_value=carryover),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                billing_service.exempt_carryover(TENANT_ID, "co-1", req, _ctx(UserRole.TENANT_ADMIN))
            assert exc_info.value.rule_id == "CARRYOVER_NOT_OUTSTANDING"

    def test_release_note_rejects_cancelled_billing_and_unknown_carton_tags(self) -> None:
        from services.payment_release import service as pr_service
        from services.payment_release.models import GenerateReleaseNoteRequest

        req = GenerateReleaseNoteRequest(
            billing_id=BILLING_ID,
            carton_tags=["CTN-1"],
        )
        cancelled_billing = {
            "id": BILLING_ID,
            "customer_id": CUSTOMER_ID,
            "container_id": CONTAINER_ID,
            "status": "cancelled",
            "total_ngn": Decimal("10000"),
            "amount_paid_ngn": Decimal("10000"),
            "total_cbm": Decimal("5"),
            "total_cartons": 2,
        }
        with (
            patch.object(pr_service.repo, "get_billing_by_id", return_value=cancelled_billing),
            patch.object(pr_service.repo, "get_default_warehouse", return_value={"id": "wh-1", "is_active": True}),
            patch.object(pr_service.repo, "get_approved_carton_tags_for_billing", return_value=["CTN-1"]),
            patch.object(pr_service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(pr_service, "tenant_transaction", return_value=nullcontext()),
            patch.object(pr_service.repo, "lock_billing", return_value=cancelled_billing),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                pr_service.generate_release_note(TENANT_ID, req, USER_ID, _ctx(UserRole.NIGERIA_OFFICE_STAFF))
            assert exc_info.value.rule_id == "BILLING_CANCELLED"

        paid_billing = {**cancelled_billing, "status": "paid"}
        with (
            patch.object(pr_service.repo, "get_billing_by_id", return_value=paid_billing),
            patch.object(pr_service.repo, "get_default_warehouse", return_value={"id": "wh-1", "is_active": True}),
            patch.object(pr_service.repo, "get_approved_carton_tags_for_billing", return_value=["CTN-2"]),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                pr_service.generate_release_note(TENANT_ID, req, USER_ID, _ctx(UserRole.NIGERIA_OFFICE_STAFF))
            assert exc_info.value.rule_id == "INVALID_CARTON_TAGS"


# ---------------------------------------------------------------------------
# Batch B: Cargo Lifecycle & Excel
# ---------------------------------------------------------------------------


class TestBatchBCargoAndExcel:
    def test_cbm_rate_handles_none_and_plural_package_units_safely(self) -> None:
        from shared.cbm_rate import compute_cbm_charge, get_cbm_rate_config, normalize_package_unit

        assert normalize_package_unit("Bags") == "bag"
        assert normalize_package_unit("BALES") == "bale"
        assert normalize_package_unit("Small Bale") == "bale"

        with patch(
            "shared.cbm_rate.execute_with_tenant",
            return_value=[
                {
                    "config_value": {
                        "currency": "USD",
                        "rate_mode": "per_package_type",
                        "carton_rate": "450",
                        "bag_rate": None,
                        "bale_rate": "bad",
                    }
                }
            ],
        ):
            cfg = get_cbm_rate_config(TENANT_ID)
        assert cfg["currency"] == "usd"
        assert cfg["carton_rate"] == Decimal("450")
        assert cfg["bag_rate"] == Decimal("450")
        assert cfg["bale_rate"] == Decimal("450")

        charge = compute_cbm_charge({"bags": Decimal("2"), "bales": Decimal("1")}, cfg)
        assert charge["amount"] == Decimal("1350.00")

    def test_phone_normalizes_double_zero_international_prefix(self) -> None:
        from shared.phone import normalize_phone

        assert normalize_phone("008613800138000", "Nigeria") == "+8613800138000"

    def test_packing_list_submit_blocks_empty_items_and_non_loading_container(self) -> None:
        from services.packing_list import service as pl_service

        pl_row = {"id": "pl-1", "status": "draft", "container_id": CONTAINER_ID}
        with (
            patch.object(pl_service.repo, "get_packing_list_by_id", return_value=pl_row),
            patch.object(pl_service.repo, "get_container_by_id", return_value={"id": CONTAINER_ID, "status": "sealed"}),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                pl_service.submit_packing_list("pl-1", TENANT_ID, _ctx(UserRole.CHINA_OFFICE_STAFF))
            assert exc_info.value.rule_id == "CONTAINER_NOT_LOADING"

        with (
            patch.object(pl_service.repo, "get_packing_list_by_id", return_value=pl_row),
            patch.object(pl_service.repo, "get_container_by_id", return_value={"id": CONTAINER_ID, "status": "loading"}),
            patch.object(pl_service.repo, "list_packing_list_items", return_value=[]),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                pl_service.submit_packing_list("pl-1", TENANT_ID, _ctx(UserRole.CHINA_OFFICE_STAFF))
            assert exc_info.value.rule_id == "EMPTY_PACKING_LIST"

    def test_manifest_verify_request_rejects_pending_or_empty_discrepancies(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        from services.manifest.models import VerifyManifestRequest

        with pytest.raises(PydanticValidationError):
            VerifyManifestRequest(verification_status="pending")  # type: ignore[arg-type]
        with pytest.raises(PydanticValidationError):
            VerifyManifestRequest(verification_status="discrepancies_found", discrepancies=[])

    def test_tracking_status_transition_enforces_role_before_state_and_guards_unapproved_pls(self) -> None:
        from services.tracking import service as tracking_service

        container_row = {"id": CONTAINER_ID, "status": "loading", "container_number": "MSKU1234567"}
        # Nigeria staff is not allowed on loading -> *; should get 403 InsufficientPermissionsError, not IllegalTransitionError
        with patch.object(tracking_service.repo, "get_container_by_id", return_value=container_row):
            with pytest.raises(InsufficientPermissionsError):
                tracking_service.update_container_status(
                    TENANT_ID,
                    CONTAINER_ID,
                    "at_warehouse",
                    {},
                    USER_ID,
                    _ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )

        # Sealing with unapproved packing lists is blocked even if approved packing lists exist
        with (
            patch.object(tracking_service.repo, "get_container_by_id", return_value=container_row),
            patch.object(tracking_service.repo, "count_approved_packing_lists", return_value=1),
            patch.object(tracking_service.repo, "count_unapproved_packing_lists", return_value=2),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                tracking_service.update_container_status(
                    TENANT_ID,
                    CONTAINER_ID,
                    "sealed",
                    {},
                    USER_ID,
                    _ctx(UserRole.CHINA_OFFICE_STAFF),
                )
            assert exc_info.value.rule_id == "UNAPPROVED_PACKING_LISTS_REMAIN"

    def test_excel_formula_defusing_handles_leading_whitespace_and_clean_id_str(self) -> None:
        from services.excel._tables import csv_safe
        from services.excel.import_manifest import _clean_id_str

        assert csv_safe("  =CMD()").startswith("'")
        assert csv_safe("\n+1+1").startswith("'")
        assert _clean_id_str("2348012345678.0") == "2348012345678"


# ---------------------------------------------------------------------------
# Batch C: Notifications, Scheduled Jobs, Queue Worker, Metering & Search
# ---------------------------------------------------------------------------


class TestBatchCNotificationsJobsMeteringSearch:
    def test_primary_color_rejects_css_injection_and_template_blocks_attribute_traversal(self) -> None:
        from services.notification import service as notif_service
        from services.notification.tenant_branding import get_primary_color

        assert get_primary_color({"primary_color": "red;background:url(x)"}) == "#1A5276"
        assert get_primary_color({"primary_color": "#0A6E4A"}) == "#0A6E4A"

        # Attribute traversal attempt in custom SMS override must fall back safely
        msg = notif_service.format_sms(
            "shipment_update",
            {"company_name": "Acme"},
            {"tracking_code": "TRK-1"},
            template_override="Hello {company_name.__class__}",
        )
        assert "__class__" not in msg
        assert msg == "Acme: You have a notification regarding your shipment."

    def test_redact_secrets_masks_activation_and_invite_links_and_blocks_retry(self) -> None:
        from services.notification import service as notif_service

        data = {"name": "Ngozi", "activation_link": "https://app.shipx.test/activate/secret-tok"}
        body = "Activate here: https://app.shipx.test/activate/secret-tok"
        redacted_data, redacted_body = notif_service.redact_secrets(data, body)
        assert redacted_data["activation_link"] == notif_service.REDACTED
        assert "secret-tok" not in (redacted_body or "")

        for event_type in ("account_activation", "customer_invite"):
            with patch(
                "services.notification.repository.get_log_by_id",
                return_value={"id": "log-1", "status": "failed", "event_type": event_type, "channel": "email"},
            ):
                with pytest.raises(BusinessRuleViolationError) as exc_info:
                    notif_service.retry_notification(TENANT_ID, "log-1", USER_ID)
                assert exc_info.value.rule_id == "NOTIFICATION_NOT_RETRYABLE"

    def test_whatsapp_webhook_verifies_hmac_signature_when_secret_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from services.notification import handler as notif_handler

        secret = "meta-app-secret-123"
        monkeypatch.setenv("META_WHATSAPP_APP_SECRET", secret)
        body = json.dumps({"entry": []})

        bad_event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/webhooks/whatsapp"}},
            "headers": {"X-Hub-Signature-256": "sha256=deadbeef"},
            "body": body,
        }
        assert notif_handler.webhook_handler(bad_event, None)["statusCode"] == 401

        good_sig = "sha256=" + hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        good_event = {
            "requestContext": {"http": {"method": "POST", "path": "/v1/webhooks/whatsapp"}},
            "headers": {"X-Hub-Signature-256": good_sig},
            "body": body,
        }
        assert notif_handler.webhook_handler(good_event, None)["statusCode"] == 200

    def test_queue_worker_raises_on_batch_item_failures(self) -> None:
        from services.queue_worker import worker

        failing_handler = MagicMock(return_value={"batchItemFailures": [{"itemIdentifier": "msg-1"}]})
        with pytest.raises(RuntimeError, match="batchItemFailures"):
            worker.process_message(failing_handler, "{}", "msg-1")

    def test_metering_unwraps_eventbridge_envelope_and_validates_period(self) -> None:
        from services.metering import service as metering_service

        envelope = json.dumps(
            {
                "source": "logistics.metering",
                "detail-type": "UsageRecorded",
                "detail": {
                    "tenant_id": TENANT_ID,
                    "metric_type": "api_calls",
                    "value": 3,
                    "occurred_at": "2026-11-23T12:00:00Z",
                },
            }
        )
        with patch.object(metering_service.repo, "upsert_usage_record") as mock_upsert:
            metering_service.process_usage_event(envelope)
            mock_upsert.assert_called_once()
            assert mock_upsert.call_args.args[0] == TENANT_ID
            assert mock_upsert.call_args.args[1] == "api_calls"
            assert mock_upsert.call_args.args[2] == 3.0

        # Non-UsageRecorded EventBridge event is ignored without raising or writing
        other_envelope = json.dumps(
            {
                "source": "logistics.scheduled",
                "detail-type": "DisputeEscalated",
                "detail": {"dispute_id": "d1"},
            }
        )
        with patch.object(metering_service.repo, "upsert_usage_record") as mock_upsert:
            metering_service.process_usage_event(other_envelope)
            mock_upsert.assert_not_called()

        # Invalid period format -> 422 ValidationError; missing tenant -> 404 ResourceNotFoundError
        with pytest.raises(ValidationError):
            metering_service.get_tenant_usage(TENANT_ID, "2026-13")

        with patch.object(metering_service.repo, "get_tenant_info", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                metering_service.get_tenant_usage(TENANT_ID, "2026-11")

    def test_search_unions_kinds_for_multi_role_staff(self) -> None:
        from services.search import repository as search_repo
        from services.search import service as search_service

        multi_ctx = _ctx(
            role=UserRole.CHINA_OFFICE_STAFF,
            roles=frozenset({UserRole.CHINA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT}),
        )
        with (
            patch.object(search_repo, "search_containers", return_value=[]) as mock_containers,
            patch.object(search_repo, "search_shipments", return_value=[]) as mock_shipments,
            patch.object(search_repo, "search_release_notes", return_value=[]) as mock_notes,
            patch.object(search_repo, "search_invoices", return_value=[]) as mock_invoices,
        ):
            search_service.search(TENANT_ID, "MSKU123", multi_ctx)
            mock_containers.assert_called_once()
            mock_shipments.assert_called_once()
            mock_notes.assert_called_once()
            mock_invoices.assert_not_called()


class TestPaymentReleaseHardeningGuards:
    def test_reissue_release_note_guards(self) -> None:
        from services.payment_release import service as pr_svc

        expired_note = {
            "id": "note-1",
            "status": "expired",
            "billing_id": BILLING_ID,
            "is_on_credit": False,
            "carton_tags": ["TAG-1", "TAG-2"],
            "total_cartons": 2,
            "packages_released": 2,
        }
        # Not found
        with patch("services.payment_release.service.repo.get_release_note_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                pr_svc.reissue_release_note(TENANT_ID, "note-missing", USER_ID, _ctx())

        # Locked row no longer expired
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=expired_note),
            patch("services.payment_release.service.repo.get_billing_by_id", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value={"status": "picked_up"}),
        ):
            with pytest.raises(BusinessRuleViolationError, match="expired"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

        # Cancelled billing
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=expired_note),
            patch("services.payment_release.service.repo.get_billing_by_id", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=expired_note),
            patch("services.payment_release.service.repo.lock_billing", return_value={"status": "cancelled", "balance_ngn": "0"}),
        ):
            with pytest.raises(BusinessRuleViolationError, match="cancelled"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

        # Unpaid billing balance
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=expired_note),
            patch(
                "services.payment_release.service.repo.get_billing_by_id",
                return_value={"status": "unpaid", "balance_ngn": "5000"},
            ),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=expired_note),
            patch("services.payment_release.service.repo.lock_billing", return_value={"status": "unpaid", "balance_ngn": "5000"}),
        ):
            with pytest.raises(BusinessRuleViolationError, match="unpaid"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

        # Already reissued
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=expired_note),
            patch("services.payment_release.service.repo.get_billing_by_id", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=expired_note),
            patch("services.payment_release.service.repo.lock_billing", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.has_active_child_release_note", return_value=True),
        ):
            with pytest.raises(BusinessRuleViolationError, match="already been re-issued"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

        # All tagged cartons already picked up
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=expired_note),
            patch("services.payment_release.service.repo.get_billing_by_id", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=expired_note),
            patch("services.payment_release.service.repo.lock_billing", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.has_active_child_release_note", return_value=False),
            patch("services.payment_release.service.repo.get_picked_carton_tags", return_value=["TAG-1", "TAG-2"]),
        ):
            with pytest.raises(BusinessRuleViolationError, match="already been picked up"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

        # Untagged note with all cartons already picked up
        untagged_note = {**expired_note, "carton_tags": [], "total_cartons": 3}
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=untagged_note),
            patch("services.payment_release.service.repo.get_billing_by_id", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.get_tenant_short", return_value="ACME"),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=untagged_note),
            patch("services.payment_release.service.repo.lock_billing", return_value={"status": "paid", "balance_ngn": "0"}),
            patch("services.payment_release.service.repo.has_active_child_release_note", return_value=False),
            patch("services.payment_release.service.repo.sum_cartons_picked_for_release_note", return_value=3),
        ):
            with pytest.raises(BusinessRuleViolationError, match="already been picked up"):
                pr_svc.reissue_release_note(TENANT_ID, "note-1", USER_ID, _ctx())

    def test_record_pickup_hardening_guards(self) -> None:
        from services.payment_release import service as pr_svc
        from services.payment_release.models import RecordPickupRequest
        from shared.exceptions import IllegalTransitionError

        active_note = {
            "id": "note-2",
            "status": "active",
            "billing_id": BILLING_ID,
            "customer_id": CUSTOMER_ID,
            "valid_until": "2099-01-01T00:00:00+00:00",
            "carton_tags": ["TAG-1", "TAG-2"],
            "total_cartons": 2,
        }
        base_req = RecordPickupRequest(collected_by_name="Jane Doe", cartons_released=1)

        # Not found
        with patch("services.payment_release.service.repo.get_release_note_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                pr_svc.record_pickup(TENANT_ID, "note-missing", base_req, USER_ID, _ctx())

        # Non-active status
        with patch(
            "services.payment_release.service.repo.get_release_note_by_id", return_value={**active_note, "status": "expired"}
        ):
            with pytest.raises(IllegalTransitionError):
                pr_svc.record_pickup(TENANT_ID, "note-2", base_req, USER_ID, _ctx())

        # Expired timestamp
        with patch(
            "services.payment_release.service.repo.get_release_note_by_id",
            return_value={**active_note, "valid_until": "2020-01-01T00:00:00+00:00"},
        ):
            with pytest.raises(BusinessRuleViolationError, match="expired"):
                pr_svc.record_pickup(TENANT_ID, "note-2", base_req, USER_ID, _ctx())

        # Missing delegate details
        delegate_req = RecordPickupRequest(is_delegate=True, cartons_released=1)
        with patch("services.payment_release.service.repo.get_release_note_by_id", return_value=active_note):
            with pytest.raises(BusinessRuleViolationError, match="Delegate details required"):
                pr_svc.record_pickup(TENANT_ID, "note-2", delegate_req, USER_ID, _ctx())

        # Tag count mismatch
        mismatch_req = RecordPickupRequest(collected_by_name="Jane Doe", cartons_released=2, carton_tags_picked=["TAG-1"])
        with patch("services.payment_release.service.repo.get_release_note_by_id", return_value=active_note):
            with pytest.raises(BusinessRuleViolationError, match="must match cartons_released"):
                pr_svc.record_pickup(TENANT_ID, "note-2", mismatch_req, USER_ID, _ctx())

        # Locked row inactive
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=active_note),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value={"status": "picked_up"}),
        ):
            with pytest.raises(IllegalTransitionError):
                pr_svc.record_pickup(TENANT_ID, "note-2", base_req, USER_ID, _ctx())

        # Invalid carton tag not on note
        invalid_tag_req = RecordPickupRequest(collected_by_name="Jane Doe", cartons_released=1, carton_tags_picked=["TAG-999"])
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=active_note),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=active_note),
        ):
            with pytest.raises(BusinessRuleViolationError, match="not on this release note"):
                pr_svc.record_pickup(TENANT_ID, "note-2", invalid_tag_req, USER_ID, _ctx())

        # Duplicate already-picked tag
        dup_tag_req = RecordPickupRequest(collected_by_name="Jane Doe", cartons_released=1, carton_tags_picked=["TAG-1"])
        with (
            patch("services.payment_release.service.repo.get_release_note_by_id", return_value=active_note),
            patch("services.payment_release.service.tenant_transaction", return_value=nullcontext()),
            patch("services.payment_release.service.repo.lock_release_note", return_value=active_note),
            patch("services.payment_release.service.repo.get_picked_carton_tags", return_value=["TAG-1"]),
        ):
            with pytest.raises(BusinessRuleViolationError, match="already picked up"):
                pr_svc.record_pickup(TENANT_ID, "note-2", dup_tag_req, USER_ID, _ctx())
