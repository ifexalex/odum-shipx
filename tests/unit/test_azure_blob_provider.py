"""Unit tests for the Azure Blob StorageProvider adapter — fully mocked.

Hermetic: no Azurite, no network, no real Azure. A small in-memory fake stands
in for the Blob container client (put/get/size/delete round-trip in a dict), and
`generate_blob_sas` is patched to a fixed token — so the adapter's logic and the
SDK call shapes are verified without any external service. Real end-to-end proof
against Azurite or a live account lives in `scripts/azure_smoke.py`, not pytest.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("azure.storage.blob")

from shared.providers.base import StorageProvider, UploadTicket  # noqa: E402

_DUMMY_CONN = "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=a2V5;BlobEndpoint=https://acct.blob.core.windows.net/;"


class _FakeBlobClient:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    @property
    def url(self):
        return f"https://acct.blob.core.windows.net/cont/{self._key}"

    def get_blob_properties(self):
        from azure.core.exceptions import ResourceNotFoundError

        if self._key not in self._store:
            raise ResourceNotFoundError(f"missing {self._key}")
        return SimpleNamespace(size=len(self._store[self._key]))


class _FakeDownload:
    def __init__(self, data):
        self._data = data

    def readall(self):
        return self._data


class _FakeContainerClient:
    """In-memory stand-in for azure.storage.blob ContainerClient."""

    def __init__(self, store):
        self._store = store

    def get_blob_client(self, key):
        return _FakeBlobClient(self._store, key)

    def upload_blob(self, name, data, overwrite, content_settings):  # noqa: ARG002
        self._store[name] = data

    def download_blob(self, key):
        return _FakeDownload(self._store[key])

    def list_blobs(self, name_starts_with):
        return [SimpleNamespace(name=k) for k in list(self._store) if k.startswith(name_starts_with)]

    def delete_blob(self, name, delete_snapshots):  # noqa: ARG002
        self._store.pop(name, None)


@pytest.fixture
def blob_provider(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", _DUMMY_CONN)
    import azure.storage.blob as asb

    # generate_blob_sas is imported inside the adapter's methods — patch at source.
    monkeypatch.setattr(asb, "generate_blob_sas", lambda **kwargs: "sv=2024&sig=FAKESIG")

    from shared.providers.azure.blob import BlobStorageProvider

    provider = BlobStorageProvider("cont")
    # One shared in-memory store so put/get/size/delete + SAS-url methods agree.
    store: dict = {}
    monkeypatch.setattr(provider, "_container_client", lambda: _FakeContainerClient(store))
    return provider


class TestBlobStorageProvider:
    def test_satisfies_the_storage_protocol(self, blob_provider):
        assert isinstance(blob_provider, StorageProvider)

    def test_put_then_get_round_trips_bytes(self, blob_provider):
        blob_provider.put_object("tenant-1/x.xlsx", b"spreadsheet", content_type="application/octet-stream")
        assert blob_provider.get_object("tenant-1/x.xlsx") == b"spreadsheet"

    def test_object_size_matches_body_and_is_none_when_absent(self, blob_provider):
        blob_provider.put_object("tenant-1/x.xlsx", b"12345", content_type="text/plain")
        assert blob_provider.object_size("tenant-1/x.xlsx") == 5
        assert blob_provider.object_size("tenant-1/missing.xlsx") is None

    def test_presigned_upload_is_a_put_ticket_with_blob_type_header(self, blob_provider):
        ticket = blob_provider.presigned_upload("tenant-1/claims/c1/evidence.png", content_type="image/png", expires_in=3600)
        assert isinstance(ticket, UploadTicket)
        assert ticket.method == "PUT"
        # The Azure-required blob-type header rides in upload_headers so the
        # frontend's generic PUT satisfies it (parity with the S3 contract).
        assert ticket.headers == {"Content-Type": "image/png", "x-ms-blob-type": "BlockBlob"}
        assert "tenant-1/claims/c1/evidence.png" in ticket.url
        assert "sig=" in ticket.url

    def test_presigned_get_url_signs_the_key(self, blob_provider):
        url = blob_provider.presigned_get_url("tenant-1/doc.pdf", expires_in=300)
        assert "tenant-1/doc.pdf" in url
        assert "sig=" in url

    def test_presigned_get_url_passes_content_disposition_to_sas(self, blob_provider, monkeypatch):
        import azure.storage.blob as asb

        captured: dict = {}
        monkeypatch.setattr(asb, "generate_blob_sas", lambda **kwargs: captured.update(kwargs) or "sig=x")
        blob_provider.presigned_get_url(
            "tenant-1/doc.pdf", expires_in=300, response_content_disposition='attachment; filename="safe.pdf"'
        )
        assert captured["content_disposition"] == 'attachment; filename="safe.pdf"'

    def test_delete_object_removes_only_that_key(self, blob_provider):
        blob_provider.put_object("tenant-1/a.png", b"a", content_type="image/png")
        blob_provider.put_object("tenant-1/a.png2", b"b", content_type="image/png")
        blob_provider.delete_object("tenant-1/a.png")
        assert blob_provider.object_size("tenant-1/a.png") is None
        assert blob_provider.object_size("tenant-1/a.png2") == 1

    def test_delete_object_of_a_missing_blob_is_not_an_error(self, blob_provider, monkeypatch):
        from azure.core.exceptions import ResourceNotFoundError

        def missing(name, delete_snapshots):  # noqa: ARG001
            raise ResourceNotFoundError("gone")

        client = blob_provider._container_client()
        monkeypatch.setattr(client, "delete_blob", missing)
        monkeypatch.setattr(blob_provider, "_container_client", lambda: client)
        blob_provider.delete_object("tenant-1/missing.png")

    def test_delete_prefix_removes_only_matching_keys_and_counts_them(self, blob_provider):
        blob_provider.put_object("tenant-1/a.txt", b"a", content_type="text/plain")
        blob_provider.put_object("tenant-1/nested/b.txt", b"b", content_type="text/plain")
        blob_provider.put_object("tenant-2/c.txt", b"c", content_type="text/plain")

        deleted = blob_provider.delete_prefix("tenant-1/")

        assert deleted == 2
        assert blob_provider.object_size("tenant-1/a.txt") is None
        assert blob_provider.object_size("tenant-2/c.txt") == 1


class TestStorageFactorySelectsAzure:
    def test_azure_cloud_returns_blob_provider(self, monkeypatch):
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", _DUMMY_CONN)

        import shared.providers as providers
        from shared.providers.azure.blob import BlobStorageProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_storage_providers", {})
        monkeypatch.setenv("BLOB_CONTAINER_NAME", "logistics-assets")

        provider = providers.get_storage_provider()
        assert isinstance(provider, BlobStorageProvider)
