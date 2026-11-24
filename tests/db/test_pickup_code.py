"""A release note's pickup code against a real database (audit UX-09).

The mocked tests cover the policy. Only a database shows that the new columns exist and constrain what they should, that
the failed-attempt counter really is atomic and persists between requests, and that only a hash is ever stored.
"""

import uuid

import pytest

from services.payment_release import repository as repo
from services.payment_release import service
from shared import pickup_code
from shared.exceptions import BusinessRuleViolationError
from shared.tenant_context import TenantContext, UserRole
from tests.db.support import _make_invoice

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("PICKUP_CODE_PEPPER", "db-test-pepper-0123456789abcdef")


@pytest.fixture
def note(world, admin):
    """An active release note for customer 0."""
    billing_id = _make_invoice(admin, world, index=0)
    note_id = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO release_note (id, tenant_id, billing_id, customer_id, container_id, reference_number, status, carton_tags, total_cartons) "
            "VALUES (%s, %s, %s, %s, %s, 'RN-PC-1', 'active', ARRAY['T1'], 1)",
            (note_id, world["tenant"], billing_id, world["customers"][0], world["containers"][0]),
        )
    return note_id


def _row(admin, note_id):
    with admin.cursor() as cur:
        cur.execute(
            "SELECT pickup_code_hash, pickup_code_issued_at, pickup_code_failed_attempts FROM release_note WHERE id = %s",
            (note_id,),
        )
        return cur.fetchone()


def _ctx(world):
    return TenantContext(tenant_id=world["tenant"], user_id=world["user"], role=UserRole.WAREHOUSE_ATTENDANT)


class TestRepository:
    def test_a_note_starts_with_no_code_and_no_failures(self, admin, note):
        assert _row(admin, note) == (None, None, 0)

    def test_storing_a_code_sets_the_hash_and_the_time_and_clears_failures(self, admin, world, note):
        repo.record_failed_pickup_code(world["tenant"], note)
        digest = pickup_code.hash_code(note, "048213")
        assert repo.set_pickup_code(world["tenant"], note, digest) is not None
        stored, issued_at, failures = _row(admin, note)
        assert stored == digest and issued_at is not None and failures == 0
        assert "048213" not in stored

    def test_clearing_removes_the_code(self, admin, world, note):
        repo.set_pickup_code(world["tenant"], note, pickup_code.hash_code(note, "048213"))
        repo.set_pickup_code(world["tenant"], note, None)
        assert _row(admin, note) == (None, None, 0)

    def test_each_wrong_code_is_counted_and_the_count_persists(self, world, note):
        totals = [repo.record_failed_pickup_code(world["tenant"], note) for _ in range(3)]
        assert totals == [1, 2, 3]

    def test_a_right_code_forgets_the_failures(self, admin, world, note):
        repo.record_failed_pickup_code(world["tenant"], note)
        repo.reset_pickup_code_attempts(world["tenant"], note)
        assert _row(admin, note)[2] == 0

    def test_the_failure_count_cannot_go_negative(self, admin, note):
        with pytest.raises(Exception) as caught, admin.cursor() as cur:
            cur.execute("UPDATE release_note SET pickup_code_failed_attempts = -1 WHERE id = %s", (note,))
        assert "pickup_code_failed_attempts" in str(caught.value) or "check" in str(caught.value).lower()

    def test_another_tenant_cannot_touch_it(self, world, note):
        other = str(uuid.uuid4())
        assert repo.set_pickup_code(other, note, "x" * 64) is None
        assert repo.record_failed_pickup_code(other, note) is None


class TestAtThePickupDesk:
    def _with_code(self, world, note, code="048213"):
        repo.set_pickup_code(world["tenant"], note, pickup_code.hash_code(note, code))
        return repo.get_release_note_by_id(world["tenant"], note)

    def test_the_right_code_passes_and_the_wrong_one_is_counted_in_the_database(self, admin, world, note):
        row = self._with_code(world, note)
        service._verify_pickup_code(world["tenant"], row, "048213", world["user"], _ctx(world))
        with pytest.raises(BusinessRuleViolationError) as wrong:
            service._verify_pickup_code(world["tenant"], row, "999999", world["user"], _ctx(world))
        assert wrong.value.rule_id == "PICKUP_CODE_INVALID"
        assert _row(admin, note)[2] == 1

    def test_five_wrong_codes_lock_the_note_even_against_the_right_one(self, admin, world, note):
        self._with_code(world, note)
        for expected in ("PICKUP_CODE_INVALID",) * 4 + ("PICKUP_CODE_LOCKED",):
            row = repo.get_release_note_by_id(world["tenant"], note)  # re-read, as each request does
            with pytest.raises(BusinessRuleViolationError) as caught:
                service._verify_pickup_code(world["tenant"], row, "999999", world["user"], _ctx(world))
            assert caught.value.rule_id == expected
        row = repo.get_release_note_by_id(world["tenant"], note)
        with pytest.raises(BusinessRuleViolationError) as locked:
            service._verify_pickup_code(world["tenant"], row, "048213", world["user"], _ctx(world))
        assert locked.value.rule_id == "PICKUP_CODE_LOCKED"

    def test_a_new_code_unlocks_it_and_retires_the_old_one(self, admin, world, note):
        self._with_code(world, note)
        for _ in range(5):
            repo.record_failed_pickup_code(world["tenant"], note)
        repo.set_pickup_code(world["tenant"], note, pickup_code.hash_code(note, "135790"))
        row = repo.get_release_note_by_id(world["tenant"], note)
        service._verify_pickup_code(world["tenant"], row, "135790", world["user"], _ctx(world))
        with pytest.raises(BusinessRuleViolationError):
            service._verify_pickup_code(world["tenant"], row, "048213", world["user"], _ctx(world))

    def test_the_api_shape_says_a_code_is_needed_but_never_shows_it(self, world, note):
        row = self._with_code(world, note)
        shaped = service._fmt_release_note(row, {}, 1)
        assert shaped["pickup_code_required"] is True and shaped["pickup_code_locked"] is False
        assert row["pickup_code_hash"] not in str(shaped)
