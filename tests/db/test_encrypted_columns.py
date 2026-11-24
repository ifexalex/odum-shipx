"""Encrypted columns hold a ciphertext, not the plaintext's width (migration 071).

With encryption on, `encrypt_field` returns a few hundred characters for a 10-digit account number. These columns
were VARCHAR(50), (100) and (255), so every encrypted write would have been refused. Local dev stores plaintext, so
only a write of ciphertext-sized values against the real schema shows it.
"""

from unittest.mock import patch

import pytest

from services.refunds import repository as refund_repo
from tests.db.support import _rows

pytestmark = pytest.mark.db

#: Longer than any width the columns had, and about what AWS KMS produces.
CIPHERTEXT = "Q" * 600


def test_a_refund_stores_an_encrypted_bank_account(admin, world):
    with patch.object(refund_repo, "encrypt_field", side_effect=lambda v: None if v is None else CIPHERTEXT):
        row = refund_repo.create_refund_request(
            world["tenant"],
            {
                "tenant_id": world["tenant"],
                "customer_id": world["customers"][0],
                "billing_id": None,
                "damage_claim_id": None,
                "refund_type": "overpayment",
                "amount_ngn": 25000,
                "reason": "",
                "status": "pending_review",
                "customer_choice": "immediate_refund",
                "requested_by": None,
                "bank_name": "Zenith Bank",
                "account_number": "0123456789",
                "account_name": "Ngozi Okonkwo",
            },
        )
    [(number, name, bank)] = _rows(
        admin, "SELECT account_number, account_name, bank_name FROM refund_request WHERE id = %s", (str(row["id"]),)
    )
    assert number == CIPHERTEXT and name == CIPHERTEXT and bank == "Zenith Bank"


def test_the_columns_are_text(admin):
    rows = _rows(
        admin,
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE (table_name, column_name) IN "
        "(('refund_request', 'account_number'), ('refund_request', 'account_name'), ('pickup_record', 'id_number')) "
        "ORDER BY 1, 2",
        (),
    )
    assert rows == [
        ("pickup_record", "id_number", "text"),
        ("refund_request", "account_name", "text"),
        ("refund_request", "account_number", "text"),
    ]
