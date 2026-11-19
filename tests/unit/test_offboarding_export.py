"""The offboarding export (audit BE-10): the archive, the hourly job and the export record's SQL."""

import io
import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from services.scheduled import offboarding_export as job
from shared import tenant_export
from shared.tenant_data import TENANT_TABLES

TENANT = "11111111-1111-1111-1111-111111111111"
EXPORT = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

TENANT_ROW = {
    "id": UUID(TENANT),
    "company_name": "Acme Shipping",
    "slug": "acme",
    "status": "offboarded",
    "offboarded_at": datetime(2026, 11, 1, tzinfo=UTC),
}

_ROWS = {
    "billing": [{"id": "b1", "tenant_id": TENANT, "total_ngn": Decimal("1500.50"), "billed_at": NOW}],
    "release_note": [{"id": "r1", "tenant_id": TENANT, "reference_number": "RN-1", "pickup_code_hash": "f" * 64}],
    "customer_invite": [{"id": "i1", "tenant_id": TENANT, "token_hash": "a" * 64, "sent_to_masked": "***1234"}],
    "pickup_record": [{"id": "p1", "tenant_id": TENANT, "id_number": "ENC(A1234567)"}],
    "refund_request": [{"id": "f1", "tenant_id": TENANT, "account_number": "ENC(0123456789)", "account_name": None}],
    "tenant_config": [
        {"tenant_id": TENANT, "config_key": "webhook_config", "config_value": {"url": "https://x.test", "secret": "whsec"}},
        {"tenant_id": TENANT, "config_key": "paystack_config", "config_value": {"last4": "4321", "secret_key_encrypted": "e"}},
    ],
    "packing_list_item": [{"id": "pli1", "packing_list_id": "pl1", "description": "=1+1"}],
}


def _fake_read(tenant_id, sql, params):
    assert tenant_id == TENANT and params == (TENANT,), "every table is read in the tenant's own RLS scope"
    for entry in TENANT_TABLES:
        if sql == entry.select_sql():
            return [dict(row) for row in _ROWS.get(entry.name, [])]
    raise AssertionError(f"unexpected SQL: {sql}")


def _decrypt(token):
    assert token.startswith("ENC(")
    return token[4:-1]


def _archive() -> tuple[zipfile.ZipFile, dict[str, int]]:
    with (
        patch.object(job, "execute_with_tenant", side_effect=_fake_read),
        patch.object(job, "decrypt_field", side_effect=_decrypt),
    ):
        data, counts = job.build_archive(TENANT_ROW, EXPORT, NOW)
    return zipfile.ZipFile(io.BytesIO(data)), counts


def _table(archive: zipfile.ZipFile, name: str) -> list[dict]:
    return [json.loads(line) for line in archive.read(f"tables/{name}.jsonl").decode().splitlines()]


class TestTheArchive:
    def test_it_holds_every_table_in_the_inventory_with_its_row_count(self):
        archive, counts = _archive()
        names = set(archive.namelist())
        assert {f"tables/{e.name}.jsonl" for e in TENANT_TABLES} <= names
        assert {"manifest.json", "README.txt", "tenant.jsonl"} <= names
        assert counts == {e.name: len(_ROWS.get(e.name, [])) for e in TENANT_TABLES}

    def test_the_manifest_describes_the_export(self):
        archive, _ = _archive()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "shipx-tenant-export" and manifest["format_version"] == 1
        assert manifest["export_id"] == EXPORT and manifest["tenant"]["id"] == TENANT
        assert manifest["tables"]["billing"] == {
            "file": "tables/billing.jsonl",
            "rows": 1,
            "omitted_columns": [],
            "decrypted_columns": [],
        }
        assert manifest["tables"]["release_note"]["omitted_columns"] == ["pickup_code_hash"]

    def test_values_keep_their_exact_form(self):
        archive, _ = _archive()
        [row] = _table(archive, "billing")
        assert row["total_ngn"] == "1500.50" and row["billed_at"] == "2026-11-17T12:00:00+00:00"
        [tenant] = [json.loads(line) for line in archive.read("tenant.jsonl").decode().splitlines()]
        assert tenant["id"] == TENANT and tenant["company_name"] == "Acme Shipping"

    def test_hashes_of_codes_and_tokens_are_left_out(self):
        archive, _ = _archive()
        assert "pickup_code_hash" not in _table(archive, "release_note")[0]
        assert "token_hash" not in _table(archive, "customer_invite")[0]
        raw = b"".join(archive.read(n) for n in archive.namelist())
        assert b"f" * 64 not in raw and b"a" * 64 not in raw

    def test_gateway_and_webhook_secrets_are_left_out(self):
        archive, _ = _archive()
        configs = {row["config_key"]: row["config_value"] for row in _table(archive, "tenant_config")}
        assert configs == {"webhook_config": {"url": "https://x.test"}, "paystack_config": {"last4": "4321"}}

    def test_encrypted_fields_are_handed_over_readable(self):
        archive, _ = _archive()
        assert _table(archive, "pickup_record")[0]["id_number"] == "A1234567"
        refund = _table(archive, "refund_request")[0]
        assert refund["account_number"] == "0123456789" and refund["account_name"] is None

    def test_a_field_that_cannot_be_decrypted_fails_the_export_instead_of_handing_over_ciphertext(self):
        with (
            patch.object(job, "execute_with_tenant", side_effect=_fake_read),
            patch.object(job, "decrypt_field", side_effect=RuntimeError("kms down")),
            pytest.raises(RuntimeError),
        ):
            job.build_archive(TENANT_ROW, EXPORT, NOW)

    def test_text_is_written_as_text_not_as_a_spreadsheet_formula(self):
        archive, _ = _archive()
        assert _table(archive, "packing_list_item")[0]["description"] == "=1+1"  # JSON: no cell to evaluate

    def test_an_unknown_value_type_fails_loudly(self):
        with pytest.raises(TypeError):
            job._jsonl([{"x": object()}])


def _claimed(**overrides) -> dict:
    return {"id": UUID(EXPORT), "tenant_id": UUID(TENANT), "status": "running", "attempts": 1, **overrides}


class TestRunExport:
    def _run(self, *, tenant=TENANT_ROW, build=None, completed=True):
        storage = MagicMock()
        with (
            patch.object(job, "_get_tenant", return_value=tenant),
            patch.object(job, "build_archive", side_effect=build or (lambda *a: (b"zip-bytes", {"billing": 2, "customer": 3}))),
            patch.object(job, "get_storage_provider", return_value=storage),
            patch.object(job.tenant_export, "mark_completed", return_value={"id": EXPORT} if completed else None) as done,
            patch.object(job.tenant_export, "mark_failed") as failed,
            patch.object(job.tenant_export, "mark_cancelled") as cancelled,
            patch.object(job, "insert_platform_audit") as audit,
        ):
            outcome = job.run_export(_claimed())
        return outcome, storage, done, failed, cancelled, audit

    def test_the_archive_is_written_to_the_tenants_export_folder_and_recorded(self):
        outcome, storage, done, failed, _, audit = self._run()
        assert outcome == "completed"
        key = f"{TENANT}/exports/offboarding/{EXPORT}.zip"
        storage.put_object.assert_called_once_with(key, b"zip-bytes", content_type="application/zip")
        kwargs = done.call_args.kwargs
        assert kwargs["key"] == key and kwargs["size_bytes"] == 9 and kwargs["row_counts"] == {"billing": 2, "customer": 3}
        assert len(kwargs["sha256"]) == 64
        failed.assert_not_called()
        assert audit.call_args.kwargs["action"] == "TENANT_DATA_EXPORTED"
        assert audit.call_args.kwargs["actor_id"] is None and audit.call_args.kwargs["target_tenant_id"] == TENANT
        assert audit.call_args.kwargs["details"]["rows"] == 5

    def test_a_tenant_that_is_no_longer_offboarded_is_not_exported(self):
        outcome, storage, done, _, cancelled, audit = self._run(tenant={**TENANT_ROW, "status": "active"})
        assert outcome == "cancelled"
        cancelled.assert_called_once_with(EXPORT)
        storage.put_object.assert_not_called()
        done.assert_not_called()
        audit.assert_not_called()

    def test_a_failure_is_recorded_by_type_only_and_does_not_raise(self, caplog):
        def boom(*_):
            raise ValueError("row 5: Ngozi Okafor, +2348012345678")

        with caplog.at_level("DEBUG"):
            outcome, storage, done, failed, _, audit = self._run(build=boom)
        assert outcome == "failed"
        failed.assert_called_once_with(EXPORT, "ValueError")
        logged = "\n".join(r.getMessage() + str(r.exc_info or "") + str(r.exc_text or "") for r in caplog.records)
        assert "ValueError" in logged and "test_offboarding_export.py" in logged
        assert "Ngozi" not in logged and "2348012345678" not in logged
        storage.put_object.assert_not_called()
        done.assert_not_called()
        audit.assert_not_called()

    def test_finishing_an_export_someone_else_took_over_counts_as_a_failure(self):
        outcome, _, _, failed, _, audit = self._run(completed=False)
        assert outcome == "failed"
        failed.assert_called_once()
        audit.assert_not_called()


class TestTheJobLoop:
    def test_it_writes_every_due_export_then_stops(self):
        claims = [_claimed(), _claimed(), None]
        with (
            patch.object(job.tenant_export, "claim_next", side_effect=claims),
            patch.object(job, "run_export", side_effect=["completed", "failed"]) as run,
        ):
            counts = job.lambda_handler({}, None)
        assert counts == {"completed": 1, "failed": 1, "cancelled": 0}
        assert run.call_count == 2

    def test_it_stops_claiming_when_its_time_is_spent(self):
        with (
            patch.object(job, "_TIME_BUDGET_SECONDS", -1),
            patch.object(job.tenant_export, "claim_next") as claim,
        ):
            assert job.lambda_handler({}, None) == {"completed": 0, "failed": 0, "cancelled": 0}
        claim.assert_not_called()


def _sql(call) -> str:
    return " ".join(call.args[1].split())


class TestTheExportRecord:
    def test_keys_live_in_the_tenants_own_export_folder(self):
        assert tenant_export.object_key(TENANT, EXPORT) == f"{TENANT}/exports/offboarding/{EXPORT}.zip"

    @pytest.mark.parametrize("bad", ["../x", "", "not-a-uuid", f"{TENANT}/.."])
    def test_ids_that_are_not_uuids_never_become_keys(self, bad):
        with pytest.raises(ValueError):
            tenant_export.object_key(bad, EXPORT)
        with pytest.raises(ValueError):
            tenant_export.object_key(TENANT, bad)

    def test_queueing_is_platform_scoped_and_skips_a_tenant_with_one_open(self):
        with patch.object(tenant_export, "execute_write_with_tenant", return_value=None) as write:
            assert tenant_export.queue_export(TENANT, "admin-1") is None
        assert write.call_args.args[0] == "PLATFORM"
        assert "ON CONFLICT (tenant_id) WHERE status IN ('pending', 'running') DO NOTHING" in _sql(write.call_args)

    def test_claiming_takes_one_due_export_without_blocking_another_worker(self):
        with patch.object(tenant_export, "execute_write_with_tenant", return_value=None) as write:
            tenant_export.claim_next()
        sql = _sql(write.call_args)
        assert "status = 'pending'" in sql
        assert "(status = 'failed' AND attempts < %(max_attempts)s)" in sql
        assert "(status = 'running' AND started_at < NOW() - make_interval(mins => %(stale_minutes)s))" in sql
        assert "FOR UPDATE SKIP LOCKED" in sql and "attempts = e.attempts + 1" in sql and sql.endswith("RETURNING e.*")
        assert write.call_args.args[2] == {"max_attempts": 3, "stale_minutes": 60}

    def test_only_a_running_export_can_complete_or_fail(self):
        with patch.object(tenant_export, "execute_write_with_tenant", return_value=None) as write:
            tenant_export.mark_completed(EXPORT, key="k", size_bytes=1, sha256="0" * 64, row_counts={}, completed_at=NOW)
            tenant_export.mark_failed(EXPORT, "ValueError" * 50)
        completed, failed = (_sql(c) for c in write.call_args_list)
        assert "WHERE id = %(id)s AND status = 'running'" in completed and "RETURNING *" in completed
        assert "WHERE id = %(id)s AND status = 'running'" in failed
        assert len(write.call_args_list[1].args[2]["error"]) == 200

    def test_only_an_export_since_the_latest_offboarding_counts_as_done(self):
        with patch.object(tenant_export, "execute_with_tenant", return_value=[]) as read:
            assert tenant_export.has_completed_export(TENANT, since=NOW) is False
        assert "status = 'completed' AND requested_at >= %s" in _sql(read.call_args)
        assert read.call_args.args[2] == (TENANT, NOW)

    def test_cancelling_is_committed_and_leaves_completed_exports_alone(self):
        with patch.object(tenant_export, "execute_write_with_tenant_many", return_value=[]) as write:
            tenant_export.cancel_open_exports(TENANT)
        sql = _sql(write.call_args)
        assert "status IN ('pending', 'running', 'failed')" in sql and sql.endswith("RETURNING id")
