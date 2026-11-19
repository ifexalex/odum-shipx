"""A refund to a bank account carries the account it is paid into (found missing 2026-11-17, fixed 2026-11-19).

The customer form offered "Bank account refund" but asked for no account, so accounts had nothing to pay into.
The account number and name are PII: validated, stored encrypted, masked for the customer and in the audit log.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from services.refunds import repository as repo
from services.refunds import service
from services.refunds.models import CreateRefundRequest
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CUSTOMER = TenantContext(tenant_id=TENANT, user_id="user-1", role=UserRole.CUSTOMER)
BANK = {"bank_name": "Zenith Bank", "account_number": "0123456789", "account_name": "Ngozi Okonkwo"}


def _request(**overrides: object) -> dict:
    return {
        "customer_id": "",
        "billing_id": "b1",
        "refund_type": "overpayment",
        "amount_requested_ngn": "25000",
        "customer_choice": "immediate_refund",
        **BANK,
        **overrides,
    }


class TestTheRequest:
    def test_a_bank_refund_with_its_account_is_accepted(self):
        req = CreateRefundRequest(**_request(account_number=" 0123456789 "))
        assert req.account_number == "0123456789"

    @pytest.mark.parametrize("missing", ["bank_name", "account_number", "account_name"])
    def test_a_bank_refund_without_its_account_is_refused(self, missing):
        with pytest.raises(ValidationError, match="needs bank_name, account_number and account_name"):
            CreateRefundRequest(**_request(**{missing: None}))

    @pytest.mark.parametrize("number", ["012345678", "01234567890", "01234-6789", "abcdefghij"])
    def test_an_account_number_is_ten_digits(self, number):
        with pytest.raises(ValidationError):
            CreateRefundRequest(**_request(account_number=number))

    def test_a_credit_takes_no_bank_details(self):
        CreateRefundRequest(
            **_request(customer_choice="credit_next_shipment", bank_name=None, account_number=None, account_name=None)
        )
        with pytest.raises(ValidationError, match="only taken for a refund to a bank account"):
            CreateRefundRequest(**_request(customer_choice="credit_next_shipment"))


class TestStorage:
    def test_the_account_is_encrypted_before_it_is_written(self):
        with (
            patch.object(repo, "encrypt_field", side_effect=lambda v: None if v is None else f"enc({v})") as encrypt,
            patch.object(repo, "execute_write_with_tenant", return_value={"id": "r1"}) as write,
        ):
            repo.create_refund_request(TENANT, {"tenant_id": TENANT, **BANK})
        params = write.call_args.args[2]
        assert params["account_number"] == "enc(0123456789)" and params["account_name"] == "enc(Ngozi Okonkwo)"
        assert params["bank_name"] == "Zenith Bank"
        assert encrypt.call_count == 2

    def test_a_refund_without_an_account_writes_none(self):
        """Claim-decision refunds pass no bank fields."""
        with patch.object(repo, "execute_write_with_tenant", return_value={"id": "r1"}) as write:
            repo.create_refund_request(TENANT, {"tenant_id": TENANT})
        params = write.call_args.args[2]
        assert params["account_number"] is None and params["account_name"] is None and params["bank_name"] is None


def _row(**extra: object) -> dict:
    return {
        "id": "r1",
        "status": "pending_review",
        "refund_type": "overpayment",
        "amount_ngn": Decimal("25000"),
        "customer_id": "c1",
        "billing_id": "b1",
        "customer_choice": "immediate_refund",
        "created_at": datetime(2026, 11, 19, tzinfo=UTC),
        **BANK,
        **extra,
    }


class TestWhoSeesTheAccount:
    def test_staff_see_the_whole_account(self):
        assert service._fmt_refund(_row())["bank_details"] == BANK

    def test_the_customer_sees_the_number_masked(self):
        view = service._customer_view(service._fmt_refund(_row()), wrote_the_reason=True)
        assert view["bank_details"] == {**BANK, "account_number": "******6789"}

    def test_no_account_means_no_bank_details(self):
        assert service._fmt_refund(_row(account_number=None, account_name=None, bank_name=None))["bank_details"] is None


class TestCreate:
    def test_the_audit_entry_masks_the_account(self):
        req = CreateRefundRequest(**_request())
        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "c1"}),
            patch.object(service.repo, "get_billing_by_id", return_value={"id": "b1", "customer_id": "c1"}),
            patch.object(service.repo, "create_refund_request", return_value=_row()) as create,
            patch.object(service, "log_audit") as audit,
        ):
            service.create_refund(TENANT, req, actor_id="user-1", ctx=CUSTOMER)
        assert create.call_args.args[1]["account_number"] == "0123456789"
        after = audit.call_args.kwargs["after_state"]
        assert after["account_number"] == "***" and after["account_name"] == "***"
        assert "0123456789" not in str(after) and "Ngozi" not in str(after)
