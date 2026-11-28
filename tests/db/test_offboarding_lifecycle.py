"""Offboarding end to end against a real database and object storage (audit BE-10).

A tenant with rows in many tables (several of which the old cleanup list did not know) is offboarded, its export is
written to storage and read back, and then the 90-day cleanup deletes it. This is the only test that runs the
inventory's delete order against real foreign keys.

Storage is the local Moto S3 (``AWS_ENDPOINT_URL``, ``S3_BUCKET_NAME``); skipped when it is not reachable.
"""

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tests.db.support import _make_invoice, _rows
from tests.patching import patch_tenant_management

pytestmark = pytest.mark.db

WEBHOOK_SECRET = "whsec_should_never_leave_the_database"
PAYSTACK_SECRET = "enc_paystack_key_should_never_leave"
PICKUP_HASH = "f" * 64
INVITE_HASH = "a" * 64


@pytest.fixture
def storage():
    from shared.providers import get_storage_provider

    provider = get_storage_provider()
    try:
        provider.put_object("probe/offboarding-test.txt", b"ok", content_type="text/plain")
    except Exception as exc:  # noqa: BLE001 - any storage failure means: not available here
        pytest.skip(f"object storage not reachable: {type(exc).__name__}")
    return provider


@pytest.fixture
def populated(admin, world):
    """Rows in tables across the inventory, including ones the old cleanup list missed."""
    tenant, customer, container = world["tenant"], world["customers"][0], world["containers"][0]
    billing_id = _make_invoice(admin, world)
    ids = {k: str(uuid.uuid4()) for k in ("pl", "pli", "rn", "warehouse", "credit")}
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_config (tenant_id, config_key, config_value) VALUES "
            "(%s, 'webhook_config', %s), (%s, 'paystack_config', %s)",
            (
                tenant,
                json.dumps({"url": "https://hooks.test", "secret": WEBHOOK_SECRET}),
                tenant,
                json.dumps({"last4": "4321", "secret_key_encrypted": PAYSTACK_SECRET}),
            ),
        )
        cur.execute("INSERT INTO warehouse (id, tenant_id, name) VALUES (%s, %s, 'Lagos Island')", (ids["warehouse"], tenant))
        cur.execute(
            "INSERT INTO packing_list (id, tenant_id, reference, container_id, customer_id) VALUES (%s, %s, 'PL-1', %s, %s)",
            (ids["pl"], tenant, container, customer),
        )
        cur.execute(
            "INSERT INTO packing_list_item (id, packing_list_id, tracking_code, description, carton_tag) "
            "VALUES (%s, %s, 'TRK-1', '=1+1', 'CT-1')",
            (ids["pli"], ids["pl"]),
        )
        cur.execute(
            "INSERT INTO misc_charge (billing_id, charge_type, description, amount_ngn) VALUES (%s, 'other', 'Handling', 500)",
            (billing_id,),
        )
        cur.execute(
            "INSERT INTO release_note (id, tenant_id, customer_id, billing_id, container_id, reference_number, pickup_code_hash) "
            "VALUES (%s, %s, %s, %s, %s, 'RN-1', %s)",
            (ids["rn"], tenant, customer, billing_id, container, PICKUP_HASH),
        )
        cur.execute(
            "INSERT INTO pickup_record (release_note_id, customer_id, tenant_id, id_number) VALUES (%s, %s, %s, 'A1234567')",
            (ids["rn"], customer, tenant),
        )
        cur.execute(
            "INSERT INTO payment_claim (tenant_id, customer_id, billing_id, amount_ngn, evidence_file_name, evidence_file_key) "
            "VALUES (%s, %s, %s, 1000, 'receipt.pdf', %s)",
            (tenant, customer, billing_id, f"{tenant}/payment-claims/receipt.pdf"),
        )
        cur.execute(
            "INSERT INTO customer_invite (tenant_id, customer_id, token_hash, expires_at) VALUES (%s, %s, %s, NOW() + INTERVAL '1 day')",
            (tenant, customer, INVITE_HASH),
        )
        cur.execute(
            "INSERT INTO refund_request (id, tenant_id, customer_id, amount_ngn, amount_approved_ngn, reason, status, refund_type, "
            "customer_choice) VALUES (%s, %s, %s, 2000, 2000, 'credit', 'applied_as_credit', 'overpayment', 'credit_next_shipment')",
            (ids["credit"], tenant, customer),
        )
        cur.execute(
            "INSERT INTO staff_notification (tenant_id, title, entity_type, event_type) VALUES (%s, 'Hello', 'billing', 'payment_due')",
            (tenant,),
        )
        cur.execute(
            "INSERT INTO notification_log (tenant_id, channel, event_type, status) VALUES (%s, 'sms', 'payment_due', 'sent')",
            (tenant,),
        )
        cur.execute(
            "INSERT INTO container_document (tenant_id, container_id, filename, s3_key, document_type) "
            "VALUES (%s, %s, 'bl.pdf', %s, 'bill_of_lading')",
            (tenant, container, f"{tenant}/containers/bl.pdf"),
        )
        cur.execute(
            "INSERT INTO rate_history (tenant_id, rate_type, rate_value) VALUES (%s, 'dollar_rate', '{\"rate\": 1550}')",
            (tenant,),
        )
        cur.execute(
            "INSERT INTO impersonation_session (platform_admin_id, target_tenant_id, target_user_id, expires_at) "
            "VALUES ('platform-admin', %s, %s, NOW())",
            (tenant, world["user"]),
        )
        cur.execute(
            "INSERT INTO platform_audit_log (action, target_tenant_id, details) VALUES ('TEST', %s, '{\"x\": 1}')", (tenant,)
        )
    yield world
    # If a test stopped half-way, take everything out in the inventory's order so `world` can drop the tenant.
    from shared.tenant_data import TENANT_TABLES

    with admin.cursor() as cur:
        for entry in reversed(TENANT_TABLES):
            cur.execute(entry.delete_sql(), {"tenant_id": tenant})
        cur.execute("DELETE FROM impersonation_session WHERE target_tenant_id = %s", (tenant,))
        cur.execute("UPDATE platform_audit_log SET target_tenant_id = NULL WHERE target_tenant_id = %s", (tenant,))
        cur.execute("DELETE FROM tenant_offboarding_export WHERE tenant_id = %s", (tenant,))


def _offboard(tenant_id: str) -> None:
    from services.tenant_management import service

    with (
        patch_tenant_management("get_identity_provider", return_value=MagicMock()),
        patch("shared.auth._tenant_status_cache", MagicMock()),
    ):
        service.offboard_tenant(tenant_id, actor_id="platform-admin-test", reason="Contract ended")


def _write_export(tenant_id: str) -> dict:
    from services.scheduled import offboarding_export
    from shared import tenant_export

    claimed = tenant_export.claim_next()
    assert claimed is not None and str(claimed["tenant_id"]) == tenant_id, "another export was queued in this database"
    assert offboarding_export.run_export(claimed) == "completed"
    return tenant_export.latest_export(tenant_id)


def test_offboarding_exports_everything_and_cleanup_then_deletes_it_all(admin, populated, storage):
    tenant = populated["tenant"]
    _offboard(tenant)
    [(status,)] = _rows(admin, "SELECT status FROM tenant_offboarding_export WHERE tenant_id = %s", (tenant,))
    assert status == "pending"

    export = _write_export(tenant)
    assert export["status"] == "completed" and export["object_key"].startswith(f"{tenant}/exports/offboarding/")

    archive = zipfile.ZipFile(io.BytesIO(storage.get_object(export["object_key"])))
    manifest = json.loads(archive.read("manifest.json"))
    rows = {name: table["rows"] for name, table in manifest["tables"].items()}
    for table in ("warehouse", "packing_list_item", "misc_charge", "payment_claim", "pickup_record", "staff_notification"):
        assert rows[table] >= 1, table
    raw = b"".join(archive.read(name) for name in archive.namelist())
    for secret in (WEBHOOK_SECRET, PAYSTACK_SECRET, PICKUP_HASH, INVITE_HASH):
        assert secret.encode() not in raw, secret
    pickup = json.loads(archive.read("tables/pickup_record.jsonl").decode().splitlines()[0])
    assert pickup["id_number"] == "A1234567"
    [(audit_action,)] = _rows(
        admin, "SELECT action FROM platform_audit_log WHERE target_tenant_id = %s AND action = 'TENANT_DATA_EXPORTED'", (tenant,)
    )
    assert audit_action == "TENANT_DATA_EXPORTED"

    # Ninety days later: the cleanup finds a completed export and deletes everything, in the inventory's order.
    from services.scheduled import data_cleanup
    from shared import tenant_export
    from shared.tenant_data import TENANT_TABLES

    offboarded_at = datetime.now(UTC) - timedelta(days=100)
    with admin.cursor() as cur:
        cur.execute("UPDATE tenant SET offboarded_at = %s WHERE id = %s", (offboarded_at, tenant))
        cur.execute("UPDATE tenant_offboarding_export SET requested_at = %s WHERE tenant_id = %s", (offboarded_at, tenant))
    assert tenant_export.has_completed_export(tenant, since=offboarded_at)

    with patch.object(data_cleanup, "_delete_cognito_users"), patch.object(data_cleanup, "log_audit"):
        data_cleanup._delete_tenant(tenant, {"offboarded_at": offboarded_at})

    assert _rows(admin, "SELECT COUNT(*) FROM tenant WHERE id = %s", (tenant,))[0][0] == 0
    for entry in TENANT_TABLES:
        sql = entry.select_sql().replace("SELECT child.*", "SELECT COUNT(*)").replace("SELECT *", "SELECT COUNT(*)")
        assert _rows(admin, sql, (tenant,))[0][0] == 0, entry.name
    assert _rows(admin, "SELECT COUNT(*) FROM impersonation_session WHERE target_tenant_id = %s", (tenant,))[0][0] == 0
    with pytest.raises(Exception):  # noqa: B017,PT011 - the provider's own not-found error, which differs by cloud
        storage.get_object(export["object_key"])


def test_cleanup_refuses_a_tenant_whose_export_has_not_completed(admin, populated):
    from shared import tenant_export

    tenant = populated["tenant"]
    _offboard(tenant)
    [(offboarded_at,)] = _rows(admin, "SELECT offboarded_at FROM tenant WHERE id = %s", (tenant,))
    assert tenant_export.has_completed_export(tenant, since=offboarded_at) is False
