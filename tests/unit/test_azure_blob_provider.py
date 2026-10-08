"""Integration tests for the Azure Blob StorageProvider adapter.

Runs against **real Azure Blob Storage** when `AZURE_STORAGE_CONNECTION_STRING`
is set in the environment (e.g. `terraform output -raw storage_connection_string`
from `infrastructure/azure`), otherwise against **Azurite** (Microsoft's official
local emulator, in `docker-compose.local.yml`). Either way these exercise real
SDK call shapes and real SAS round-trips — the Azure equivalent of the
moto-backed `test_storage_provider.py`.

Skips automatically when neither is available, so the suite stays green without
them. Run locally against Azurite: `docker compose -f docker-compose.local.yml
up -d azurite`; against your Azure account: `export AZURE_STORAGE_CONNECTION_STRING=$(terraform -chdir=infrastructure/azure output -raw storage_connection_string)`.
"""
import os
import socket
import uuid

import pytest

pytest.importorskip("azure.storage.blob")

from shared.providers.base import StorageProvider, UploadTicket  # noqa: E402

# A real connection string from the environment wins; else the well-known public
# Azurite dev account (not a secret).
_AZURITE_CONN = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)
_REAL_CONN = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
_CONN = _REAL_CONN or _AZURITE_CONN


def _azurite_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 10000), timeout=1):
            return True
    except OSError:
        return False


# Real account → always run; else require Azurite on :10000.
pytestmark = pytest.mark.skipif(
    not _REAL_CONN and not _azurite_up(),
    reason="No AZURE_STORAGE_CONNECTION_STRING and Azurite not running on :10000",
)


@pytest.fixture
def blob_provider(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", _CONN)

    from azure.storage.blob import BlobServiceClient

    container = f"test-{uuid.uuid4().hex}"
    svc = BlobServiceClient.from_connection_string(_CONN)
    svc.create_container(container)

    from shared.providers.azure.blob import BlobStorageProvider

    try:
        yield BlobStorageProvider(container)
    finally:
        svc.delete_container(container)


class TestBlobStorageProvider:
    def test_satisfies_the_storage_protocol(self, blob_provider):
        assert isinstance(blob_provider, StorageProvider)

    def test_put_then_get_round_trips_bytes(self, blob_provider):
        key = "tenant-1/exports/report.xlsx"
        blob_provider.put_object(key, b"spreadsheet-bytes", content_type="application/octet-stream")
        assert blob_provider.get_object(key) == b"spreadsheet-bytes"

    def test_object_size_matches_body_and_is_none_when_absent(self, blob_provider):
        key = "tenant-1/imports/x.xlsx"
        blob_provider.put_object(key, b"12345", content_type="text/plain")
        assert blob_provider.object_size(key) == 5
        assert blob_provider.object_size("tenant-1/imports/missing.xlsx") is None

    def test_presigned_upload_is_a_put_ticket_with_blob_type_header(self, blob_provider):
        ticket = blob_provider.presigned_upload("tenant-1/claims/c1/evidence.png", content_type="image/png", expires_in=3600)
        assert isinstance(ticket, UploadTicket)
        assert ticket.method == "PUT"
        # The Azure-required blob-type header rides in upload_headers so the
        # frontend's generic PUT satisfies it (parity with the S3 contract).
        assert ticket.headers == {"Content-Type": "image/png", "x-ms-blob-type": "BlockBlob"}
        # Works for both Azurite (http://127.0.0.1:10000/...) and real Azure
        # (https://<account>.blob.core.windows.net/...): the blob path + a SAS.
        assert "tenant-1/claims/c1/evidence.png" in ticket.url
        assert "sig=" in ticket.url

    def test_presigned_upload_url_actually_accepts_a_browser_put(self, blob_provider):
        """End-to-end: the ticket a browser would use really uploads to Azurite."""
        import requests

        key = "tenant-1/claims/c1/evidence.png"
        ticket = blob_provider.presigned_upload(key, content_type="image/png", expires_in=3600)

        resp = requests.put(ticket.url, data=b"\x89PNG-bytes", headers=ticket.headers, timeout=10)
        assert resp.status_code == 201, resp.text

        assert blob_provider.get_object(key) == b"\x89PNG-bytes"

    def test_presigned_get_url_actually_serves_the_blob(self, blob_provider):
        import requests

        key = "tenant-1/doc.pdf"
        blob_provider.put_object(key, b"pdf-body", content_type="application/pdf")

        url = blob_provider.presigned_get_url(key, expires_in=300)
        resp = requests.get(url, timeout=10)
        assert resp.status_code == 200
        assert resp.content == b"pdf-body"

    def test_presigned_get_url_sets_content_disposition(self, blob_provider):
        import requests

        key = "tenant-1/doc.pdf"
        blob_provider.put_object(key, b"pdf-body", content_type="application/pdf")

        url = blob_provider.presigned_get_url(key, expires_in=300, response_content_disposition='attachment; filename="safe.pdf"')
        resp = requests.get(url, timeout=10)
        assert resp.headers.get("Content-Disposition") == 'attachment; filename="safe.pdf"'

    def test_delete_prefix_removes_only_matching_keys_and_counts_them(self, blob_provider):
        blob_provider.put_object("tenant-1/a.txt", b"a", content_type="text/plain")
        blob_provider.put_object("tenant-1/nested/b.txt", b"b", content_type="text/plain")
        blob_provider.put_object("tenant-2/c.txt", b"c", content_type="text/plain")

        deleted = blob_provider.delete_prefix("tenant-1/")

        assert deleted == 2
        assert blob_provider.object_size("tenant-1/a.txt") is None
        assert blob_provider.object_size("tenant-1/nested/b.txt") is None
        assert blob_provider.object_size("tenant-2/c.txt") == 1


class TestStorageFactorySelectsAzure:
    def test_azure_cloud_returns_blob_provider(self, monkeypatch):
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", _CONN)

        import shared.providers as providers
        from shared.providers.azure.blob import BlobStorageProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_storage_providers", {})
        monkeypatch.setenv("BLOB_CONTAINER_NAME", "logistics-assets")

        provider = providers.get_storage_provider()
        assert isinstance(provider, BlobStorageProvider)
