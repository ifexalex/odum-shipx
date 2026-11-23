"""Azure Blob Storage provider — the Azure analogue of `aws/s3.py`.

Implements the `StorageProvider` port against Azure Blob Storage, so the same
`services/*` code runs unchanged when `CLOUD_PROVIDER=azure`. Bound to one
container (the Azure equivalent of an S3 bucket).

Auth: a connection string (`AZURE_STORAGE_CONNECTION_STRING`) — used by local
Azurite and shared-key production — or an account URL + `DefaultAzureCredential`
(managed identity). Presigned URLs use a shared-key SAS when a key is available;
the managed-identity path would use a user-delegation SAS (noted inline).

Upload contract parity: the normalized PUT ticket carries the Azure-required
`x-ms-blob-type: BlockBlob` header alongside `Content-Type`, so the frontend's
single PUT path (which sends every `upload_headers` entry) works against Blob
exactly as it does against S3.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.providers.base import UploadTicket


class BlobStorageProvider:
    """StorageProvider backed by Azure Blob Storage."""

    def __init__(self, container: str) -> None:
        self._container = container
        self._conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
        self._account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "")
        self._service: Any = None

    def _service_client(self) -> Any:
        if self._service is None:
            from azure.storage.blob import BlobServiceClient

            if self._conn:
                self._service = BlobServiceClient.from_connection_string(self._conn)
            else:
                from azure.identity import DefaultAzureCredential

                self._service = BlobServiceClient(self._account_url, credential=DefaultAzureCredential())
        return self._service

    def _container_client(self) -> Any:
        return self._service_client().get_container_client(self._container)

    def _shared_key(self) -> tuple[str, str]:
        """Return (account_name, account_key) parsed from the connection string.

        SAS generation needs the shared key. Without a connection string (managed
        identity), a user-delegation SAS is required instead — raised clearly so
        the prod path is implemented deliberately rather than silently broken.
        """
        if not self._conn:
            raise NotImplementedError(
                "Presigned URLs without a connection string require a user-delegation SAS "
                "(get_user_delegation_key); implement when the managed-identity path is wired."
            )
        parts = dict(p.split("=", 1) for p in self._conn.split(";") if "=" in p)
        return parts.get("AccountName", ""), parts.get("AccountKey", "")

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int,
        response_content_disposition: str | None = None,
    ) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        account_name, account_key = self._shared_key()
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=self._container,
            blob_name=key,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(UTC) + timedelta(seconds=expires_in),
            content_disposition=response_content_disposition,
        )
        blob_url: str = self._container_client().get_blob_client(key).url
        return f"{blob_url}?{sas}"

    def presigned_upload(
        self, key: str, *, content_type: str, expires_in: int, content_length: int | None = None
    ) -> UploadTicket:
        # A SAS cannot bind the upload's length; `content_length` is checked where the file is used
        # (shared.uploads.check_stored_size).
        del content_length
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        account_name, account_key = self._shared_key()
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=self._container,
            blob_name=key,
            account_key=account_key,
            permission=BlobSasPermissions(create=True, write=True),
            expiry=datetime.now(UTC) + timedelta(seconds=expires_in),
        )
        blob_url: str = self._container_client().get_blob_client(key).url
        # Azure Blob PUT requires the blob-type header; it rides in upload_headers
        # so the frontend's generic PUT (which sends every header) satisfies it.
        return UploadTicket(
            url=f"{blob_url}?{sas}",
            method="PUT",
            headers={"Content-Type": content_type, "x-ms-blob-type": "BlockBlob"},
        )

    def put_object(self, key: str, body: bytes, *, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self._container_client().upload_blob(
            name=key,
            data=body,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def get_object(self, key: str) -> bytes:
        return bytes(self._container_client().download_blob(key).readall())

    def object_size(self, key: str) -> int | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            props = self._container_client().get_blob_client(key).get_blob_properties()
        except ResourceNotFoundError:
            return None
        return int(props.size)

    def delete_prefix(self, prefix: str) -> int:
        """Delete every blob under `prefix` (plus snapshots) and return the count.

        For GDPR parity with the S3 version-purge: when blob versioning is enabled
        in production, also enumerate `include=['versions']` and delete by
        `version_id`. Azurite does not support versioning, so snapshots cover the
        local case; the versioning sweep is a prod follow-up.
        """
        cc = self._container_client()
        count = 0
        for blob in cc.list_blobs(name_starts_with=prefix):
            cc.delete_blob(blob.name, delete_snapshots="include")
            count += 1
        return count
