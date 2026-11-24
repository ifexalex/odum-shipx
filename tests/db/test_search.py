"""Global search against a real database (audit UX-05).

The mocked tests cover who may find what and how the text is bound. Only a database shows that the five queries are
valid SQL against the real schema, that the LIKE escaping does what it claims, that phone numbers match however they
were typed, and that a customer can never find another customer's records.
"""

import uuid

import pytest

from services.search import service
from shared.tenant_context import TenantContext, UserRole
from tests.db.support import _make_invoice

pytestmark = pytest.mark.db


def _ctx(world, role: UserRole, user_id: str | None = None) -> TenantContext:
    return TenantContext(tenant_id=world["tenant"], user_id=user_id or world["user"], role=role)


def _kinds_ids(result: dict) -> set[tuple[str, str]]:
    return {(r["kind"], r["id"]) for r in result["results"]}


@pytest.fixture
def seeded(world, admin):
    """Customer 0 and 1 each have an invoice, a packing list with a carton and a release note on their own container."""
    ids: dict = {"billing": [], "pl": [], "note": []}
    with admin.cursor() as cur:
        cur.execute(
            "UPDATE customer SET name = 'Ngozi Okonkwo', phone = '+2348012345678' WHERE id = %s", (world["customers"][0],)
        )
        cur.execute("UPDATE customer SET name = 'Chidi Eze', phone = '+2348099999999' WHERE id = %s", (world["customers"][1],))
    for i in (0, 1):
        ids["billing"].append(_make_invoice(admin, world, index=i))
        pl, note = str(uuid.uuid4()), str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) VALUES (%s, %s, %s, %s, %s, 'approved')",
                (pl, world["tenant"], world["containers"][i], world["customers"][i], f"PL-SRCH-{i}"),
            )
            cur.execute(
                "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm) VALUES (%s, 'goods', %s, %s, 1)",
                (pl, f"TAG-{i}", f"TRK-SRCH-{i}"),
            )
            cur.execute(
                "INSERT INTO release_note (id, tenant_id, billing_id, customer_id, container_id, reference_number, status, carton_tags, total_cartons) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'active', ARRAY[%s], 1)",
                (
                    note,
                    world["tenant"],
                    ids["billing"][i],
                    world["customers"][i],
                    world["containers"][i],
                    f"RN-SRCH-{i}",
                    f"TAG-{i}",
                ),
            )
        ids["pl"].append(pl)
        ids["note"].append(note)
    return ids


class TestStaffSearch:
    def test_a_container_number_finds_the_container_and_the_records_on_it(self, world, seeded):
        found = _kinds_ids(service.search(world["tenant"], "MNY0000", _ctx(world, UserRole.TENANT_ADMIN)))
        assert ("container", world["containers"][0]) in found
        assert ("shipment", seeded["pl"][0]) in found
        assert ("invoice", seeded["billing"][0]) in found
        assert ("release_note", seeded["note"][0]) in found
        assert ("shipment", seeded["pl"][1]) not in found

    def test_a_cartons_tracking_code_finds_its_shipment(self, world, seeded):
        found = _kinds_ids(service.search(world["tenant"], "TRK-SRCH-1", _ctx(world, UserRole.NIGERIA_OFFICE_STAFF)))
        assert ("shipment", seeded["pl"][1]) in found

    def test_a_release_note_reference_finds_it_and_an_exact_match_comes_first(self, world, seeded):
        result = service.search(world["tenant"], "RN-SRCH-0", _ctx(world, UserRole.WAREHOUSE_ATTENDANT))
        assert result["results"][0]["kind"] == "release_note"
        assert result["results"][0]["id"] == seeded["note"][0]

    @pytest.mark.parametrize("typed", ["08012345678", "+234 801 234 5678", "2348012345678", "801234567"])
    def test_a_phone_number_finds_the_customer_however_it_is_typed(self, world, seeded, typed):
        if len(typed) < 9:  # fewer than 6 significant digits would not be a phone lookup; this one is 9
            pytest.skip("not a phone lookup")
        found = _kinds_ids(service.search(world["tenant"], typed, _ctx(world, UserRole.TENANT_ADMIN)))
        assert ("customer", world["customers"][0]) in found
        assert ("invoice", seeded["billing"][0]) in found
        assert ("customer", world["customers"][1]) not in found

    def test_china_staff_cannot_find_anyone_by_phone(self, world, seeded):
        result = service.search(world["tenant"], "08012345678", _ctx(world, UserRole.CHINA_OFFICE_STAFF))
        assert result["results"] == []

    def test_a_name_finds_the_customers_records(self, world, seeded):
        found = _kinds_ids(service.search(world["tenant"], "okonkwo", _ctx(world, UserRole.NIGERIA_OFFICE_STAFF)))
        assert ("invoice", seeded["billing"][0]) in found
        assert ("invoice", seeded["billing"][1]) not in found

    def test_percent_and_underscore_are_literal(self, world, seeded):
        for text in ("%%", "__", "MNY%", "MNY_000_"):
            assert service.search(world["tenant"], text, _ctx(world, UserRole.TENANT_ADMIN))["results"] == [], text

    def test_a_hostile_string_is_just_text(self, world, seeded):
        result = service.search(world["tenant"], "x'; DROP TABLE customer; --", _ctx(world, UserRole.TENANT_ADMIN))
        assert result["results"] == []

    def test_another_tenants_records_are_never_found(self, world, seeded):
        other = str(uuid.uuid4())
        assert (
            service.search(other, "MNY0000", TenantContext(tenant_id=other, user_id=world["user"], role=UserRole.TENANT_ADMIN))[
                "results"
            ]
            == []
        )

    def test_an_erased_customer_is_not_found(self, world, seeded, admin):
        with admin.cursor() as cur:
            cur.execute(
                "UPDATE customer SET anonymised_at = NOW(), name = 'Anonymised', phone = NULL WHERE id = %s",
                (world["customers"][0],),
            )
        found = _kinds_ids(service.search(world["tenant"], "okonkwo", _ctx(world, UserRole.TENANT_ADMIN)))
        assert ("customer", world["customers"][0]) not in found


class TestCustomerSearch:
    @pytest.fixture
    def login(self, world, admin):
        """Give customer 0 a portal login."""
        login_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_user (id, tenant_id, email, full_name, role) VALUES (%s, %s, %s, 'Ngozi', 'customer')",
                (login_id, world["tenant"], f"ngozi-{login_id[:6]}@example.test"),
            )
            cur.execute("UPDATE customer SET user_id = %s WHERE id = %s", (login_id, world["customers"][0]))
        return login_id

    def test_a_customer_finds_their_own_records_by_container_number(self, world, seeded, login):
        found = _kinds_ids(service.search(world["tenant"], "MNY0000", _ctx(world, UserRole.CUSTOMER, login)))
        assert found == {("shipment", seeded["pl"][0]), ("invoice", seeded["billing"][0]), ("release_note", seeded["note"][0])}

    def test_a_customer_cannot_find_another_customers_records(self, world, seeded, login):
        """Another customer's container, tracking code, release note and name all come back empty."""
        for text in ("MNY0001", "TRK-SRCH-1", "RN-SRCH-1", "Chidi", "08099999999"):
            assert service.search(world["tenant"], text, _ctx(world, UserRole.CUSTOMER, login))["results"] == [], text

    def test_a_customer_never_sees_containers_or_customer_profiles(self, world, seeded, login):
        kinds = {r["kind"] for r in service.search(world["tenant"], "MNY", _ctx(world, UserRole.CUSTOMER, login))["results"]}
        assert kinds <= {"shipment", "invoice", "release_note"}
