"""The 90-day tenant data cleanup (`services/scheduled/data_cleanup.py`)."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from services.scheduled import data_cleanup
from shared.tenant_data import TENANT_TABLES

TENANT = "11111111-1111-1111-1111-111111111111"


class TestObjectStoragePurge:
    """The purge read TENANT_DATA_BUCKET, which no deployment sets, so it was always skipped (2026-11-17)."""

    def test_without_an_override_it_purges_the_tenant_prefix_in_the_assets_bucket(self, monkeypatch):
        monkeypatch.delenv("TENANT_DATA_BUCKET", raising=False)
        storage = MagicMock()
        storage.delete_prefix.return_value = 3
        with patch.object(data_cleanup, "get_storage_provider", return_value=storage) as provider:
            data_cleanup._delete_s3_prefix(TENANT)
        provider.assert_called_once_with(None)  # None is the default assets bucket
        storage.delete_prefix.assert_called_once_with(f"{TENANT}/")

    def test_a_separate_tenant_data_bucket_is_still_honoured(self, monkeypatch):
        monkeypatch.setenv("TENANT_DATA_BUCKET", "tenant-data")
        storage = MagicMock()
        with patch.object(data_cleanup, "get_storage_provider", return_value=storage) as provider:
            data_cleanup._delete_s3_prefix(TENANT)
        provider.assert_called_once_with("tenant-data")


OFFBOARDED_AT = datetime(2026, 8, 1, tzinfo=UTC)


class TestNoDeletionWithoutAnExport:
    """Audit BE-10: the tenant's data is handed over before it is destroyed."""

    def _run(self, has_export: bool):
        tenants = [{"id": TENANT, "offboarded_at": OFFBOARDED_AT}]
        with (
            patch.object(data_cleanup, "_get_offboarded_tenants", return_value=tenants),
            patch.object(data_cleanup.tenant_export, "has_completed_export", return_value=has_export) as check,
            patch.object(data_cleanup, "_delete_tenant") as delete,
        ):
            result = data_cleanup.lambda_handler({}, None)
        return result, check, delete

    def test_a_tenant_with_no_completed_export_is_not_deleted(self, caplog):
        with caplog.at_level("WARNING"):
            result, check, delete = self._run(has_export=False)
        delete.assert_not_called()
        assert result == {"deleted": 0, "errors": 0, "refused": 1}
        assert any("Refusing to delete tenant" in r.getMessage() for r in caplog.records)

    def test_the_export_must_be_from_the_latest_offboarding(self):
        _, check, _ = self._run(has_export=False)
        check.assert_called_once_with(TENANT, since=OFFBOARDED_AT)

    def test_a_tenant_with_a_completed_export_is_deleted(self):
        result, _, delete = self._run(has_export=True)
        delete.assert_called_once()
        assert result == {"deleted": 1, "errors": 0, "refused": 0}


class TestDeletingATenant:
    def _delete(self, *, storage_fails: bool = False, tenant_row_found: bool = True):
        calls: list[str] = []
        storage = MagicMock()
        if storage_fails:
            storage.delete_prefix.side_effect = RuntimeError("storage down")
        else:
            storage.delete_prefix.side_effect = lambda prefix: calls.append("storage") or 0

        @contextmanager
        def transaction(tenant_id):
            assert tenant_id == "PLATFORM"
            calls.append("begin")
            yield
            calls.append("commit")

        def write(tenant_id, sql, params):
            assert tenant_id == "PLATFORM" and params == {"tenant_id": TENANT}
            calls.append(" ".join(sql.split()))
            if sql.startswith("DELETE FROM tenant WHERE") and not tenant_row_found:
                return None
            return {"id": TENANT}

        with (
            patch.object(data_cleanup, "get_storage_provider", return_value=storage),
            patch.object(data_cleanup, "tenant_transaction", transaction),
            patch.object(data_cleanup, "execute_write_with_tenant", side_effect=write),
            patch.object(data_cleanup, "_delete_cognito_users", side_effect=lambda t: calls.append("cognito")),
            patch.object(data_cleanup, "log_audit"),
        ):
            data_cleanup._delete_tenant(TENANT, {"offboarded_at": OFFBOARDED_AT})
        return calls

    def test_every_inventoried_table_is_deleted_children_first_inside_one_transaction(self):
        calls = self._delete()
        begin, commit = calls.index("begin"), calls.index("commit")
        deletes = [c for c in calls[begin:commit] if c.startswith("DELETE FROM") and "impersonation" not in c]
        expected = [" ".join(e.delete_sql().split()) for e in reversed(TENANT_TABLES)]
        assert deletes[: len(expected)] == expected
        assert deletes[-1] == "DELETE FROM tenant WHERE id = %(tenant_id)s RETURNING id"

    def test_the_platforms_records_are_cleared_before_the_tenant_row(self):
        calls = self._delete()
        tenant_delete = calls.index("DELETE FROM tenant WHERE id = %(tenant_id)s RETURNING id")
        assert calls.index("DELETE FROM impersonation_session WHERE target_tenant_id = %(tenant_id)s RETURNING 1") < tenant_delete
        assert any(c.startswith("UPDATE platform_audit_log SET target_tenant_id = NULL") for c in calls[:tenant_delete])

    def test_files_go_first(self):
        assert self._delete()[0] == "storage"

    def test_storage_failure_deletes_no_rows(self):
        recorded: list[str] = []
        storage = MagicMock()
        storage.delete_prefix.side_effect = RuntimeError("storage down")
        with (
            patch.object(data_cleanup, "get_storage_provider", return_value=storage),
            patch.object(data_cleanup, "execute_write_with_tenant", side_effect=lambda *a: recorded.append(a[1])),
            pytest.raises(RuntimeError),
        ):
            data_cleanup._delete_tenant(TENANT, {"offboarded_at": OFFBOARDED_AT})
        assert recorded == []

    def test_cognito_users_go_after_the_rows_are_committed(self):
        calls = self._delete()
        assert calls.index("cognito") > calls.index("commit")

    def test_a_tenant_row_that_is_already_gone_rolls_the_transaction_back(self):
        with pytest.raises(RuntimeError):
            self._delete(tenant_row_found=False)
