"""The claim read a customer opens their own claim with, against a real database (audit UX-07).

It joins the claim to its customer and container, lists its evidence, and finds the latest resolution with the
refund it produced. Only a database shows the SQL is valid against the real schema and that a tenant cannot read
another tenant's claim.
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.claims import repository as repo
from services.claims import service
from shared.exceptions import ResourceNotFoundError
from shared.tenant_context import TenantContext, UserRole

pytestmark = pytest.mark.db


@pytest.fixture
def claim(world, admin):
    """A resolved claim with two evidence files, a refund resolution and its refund."""
    claim_id, refund_id = str(uuid.uuid4()), str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute("UPDATE customer SET name = 'Claimant Customer' WHERE id = %s", (world["customers"][0],))
        cur.execute(
            "INSERT INTO damage_claim (id, tenant_id, customer_id, container_id, description, status, reference, inspection_method) "
            "VALUES (%s, %s, %s, %s, 'Water damage', 'resolved', 'DC-20261110-001', 'customer_evidence')",
            (claim_id, world["tenant"], world["customers"][0], world["containers"][0]),
        )
        for name in ("a-photo.jpg", "b-video.mp4"):
            cur.execute(
                "INSERT INTO claim_evidence (damage_claim_id, file_key, file_name, file_type) VALUES (%s, %s, %s, 'image/jpeg')",
                (claim_id, f"{world['tenant']}/claims/{claim_id}/{name}", name),
            )
        cur.execute(
            "INSERT INTO refund_request (id, tenant_id, customer_id, amount_ngn, reason, status, refund_type, amount_approved_ngn) "
            "VALUES (%s, %s, %s, 30000, 'Damaged goods', 'approved', 'damage_or_loss', 25000)",
            (refund_id, world["tenant"], world["customers"][0]),
        )
        cur.execute(
            "INSERT INTO claim_resolution (tenant_id, damage_claim_id, resolution_type, resolution_amount_ngn, approval_level, "
            "approved_by, notes, refund_request_id) VALUES (%s, %s, 'refund', 30000, 'admin', %s, 'internal: repeat claimant', %s)",
            (world["tenant"], claim_id, world["user"], refund_id),
        )
    return claim_id


class TestRepository:
    def test_the_claim_carries_its_customer_and_container(self, world, claim):
        row = repo.get_damage_claim_by_id(world["tenant"], claim)
        assert row["customer_name"] == "Claimant Customer"
        assert row["container_number"] == "MNY0000"
        assert row["reference"] == "DC-20261110-001"

    def test_another_tenant_cannot_read_it(self, claim):
        assert repo.get_damage_claim_by_id(str(uuid.uuid4()), claim) is None

    def test_the_outcome_is_the_decision_and_the_refund_with_its_approved_amount(self, world, claim):
        outcome = repo.get_claim_outcome(world["tenant"], claim)
        assert outcome["resolution_type"] == "refund"
        assert Decimal(str(outcome["resolution_amount_ngn"])) == Decimal("30000")
        assert outcome["refund_status"] == "approved"
        assert Decimal(str(outcome["refund_amount_ngn"])) == Decimal("25000")  # approved, not requested

    def test_the_outcome_query_does_not_select_the_internal_record(self, world, claim):
        outcome = repo.get_claim_outcome(world["tenant"], claim)
        assert not {"notes", "approved_by", "approval_level"} & set(outcome)

    def test_the_outcome_carries_what_staff_typed_as_the_reason(self, world, claim):
        # The service decides who is shown it; the query only fetches it.
        assert repo.get_claim_outcome(world["tenant"], claim)["reason"] == "internal: repeat claimant"

    def test_a_claim_with_no_resolution_has_no_outcome(self, world, admin):
        other = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO damage_claim (id, tenant_id, customer_id, container_id, description, status) VALUES (%s, %s, %s, %s, 'x', 'filed')",
                (other, world["tenant"], world["customers"][1], world["containers"][1]),
            )
        assert repo.get_claim_outcome(world["tenant"], other) is None

    def test_evidence_lists_oldest_first(self, claim):
        assert [f["file_name"] for f in repo.list_claim_evidence(claim)] == ["a-photo.jpg", "b-video.mp4"]


class TestService:
    @staticmethod
    def _ctx(world, role, user_id=None):
        return TenantContext(tenant_id=world["tenant"], user_id=user_id or world["user"], role=role)

    def _read(self, world, claim, ctx):
        storage = MagicMock()
        storage.presigned_get_url.side_effect = lambda key, expires_in: f"https://files.example/{key}"
        with patch.object(service, "get_storage_provider", return_value=storage):
            return service.get_claim(world["tenant"], claim, ctx)

    def test_a_customer_reads_their_own_claim_in_full(self, admin, world, claim):
        customer_user = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) VALUES (%s, %s, %s, 'C', 'customer')",
                (customer_user, world["tenant"], f"c-{customer_user[:8]}@example.test"),
            )
            cur.execute("UPDATE customer SET user_id = %s WHERE id = %s", (customer_user, world["customers"][0]))
        result = self._read(world, claim, self._ctx(world, UserRole.CUSTOMER, customer_user))
        assert result["reference"] == "DC-20261110-001" and result["customer_name"] == "Claimant Customer"
        assert [f["file_name"] for f in result["evidence"]] == ["a-photo.jpg", "b-video.mp4"]
        assert result["evidence"][0]["download_url"].endswith("/a-photo.jpg")
        assert result["resolution"]["resolution_type"] == "refund"
        assert result["refund"]["status"] == "approved"
        assert "repeat claimant" not in str(result)

    def test_another_customer_gets_a_404(self, admin, world, claim):
        other_user = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) VALUES (%s, %s, %s, 'C2', 'customer')",
                (other_user, world["tenant"], f"c2-{other_user[:8]}@example.test"),
            )
            cur.execute("UPDATE customer SET user_id = %s WHERE id = %s", (other_user, world["customers"][1]))
        with pytest.raises(ResourceNotFoundError):
            self._read(world, claim, self._ctx(world, UserRole.CUSTOMER, other_user))

    def test_staff_read_the_same_claim(self, world, claim):
        result = self._read(world, claim, self._ctx(world, UserRole.NIGERIA_OFFICE_STAFF))
        assert result["id"] == claim
