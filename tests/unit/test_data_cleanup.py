"""The 90-day tenant data cleanup (`services/scheduled/data_cleanup.py`)."""

from unittest.mock import MagicMock, patch

from services.scheduled import data_cleanup

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
