"""Cloud-portability ports (interfaces).

The app depends on these abstractions; per-cloud implementations live in
`shared/providers/<cloud>/`. Keeping `services/` and the rest of `shared/` free
of cloud SDKs is what lets ShipX run on AWS or Azure. The active cloud is
selected by the `CLOUD_PROVIDER` env var (default "aws") in
`shared/providers/__init__.py`.

Adapters so far: KeyProvider (crypto), StorageProvider (object storage). Queue /
email / events / identity ports follow the same shape as they are migrated off
boto3.
"""
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class KeyProvider(Protocol):
    """Envelope-encryption key operations.

    Field encryption (`shared/encryption.py`) generates a per-value 32-byte data
    key, encrypts the value with it (Fernet), and stores the *encrypted* data key
    beside the ciphertext. The data-key generate/decrypt step is the only
    cloud-specific part — AWS KMS vs Azure Key Vault — so it lives here.
    """

    def generate_data_key(self) -> tuple[bytes, bytes]:
        """Return `(plaintext_key, encrypted_key)`.

        `plaintext_key` is exactly 32 bytes (AES-256). `encrypted_key` is the
        provider-specific wrapped form stored alongside the ciphertext and later
        passed back to `decrypt_data_key`.
        """
        ...

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        """Return the 32-byte plaintext key for an `encrypted_key` blob."""
        ...


@dataclass(frozen=True)
class UploadTicket:
    """Cloud-neutral browser-upload descriptor.

    A single normalized PUT contract that both clouds satisfy: the browser does
    `PUT url` with `headers` and the file as the raw body. AWS returns a
    presigned-PUT URL; Azure returns a Blob SAS PUT URL. (We deliberately do not
    use the AWS presigned-POST form contract, which has no Azure equivalent.)

    Trade-off vs. the old presigned-POST: the S3 `content-length-range` policy
    enforced the max file size at the edge. A presigned PUT cannot, so size is
    enforced client-side (see `frontend/src/hooks/useFileUpload.ts`) and should
    be re-verified server-side via `StorageProvider.object_size` on any flow that
    gains a post-upload confirm step.
    """

    url: str
    method: str  # "PUT"
    headers: dict[str, str]  # e.g. {"Content-Type": "image/png"}

    def as_response(self) -> dict[str, Any]:
        """Wire shape merged into presigned-upload endpoint responses."""
        return {
            "upload_url": self.url,
            "upload_method": self.method,
            "upload_headers": self.headers,
        }


@runtime_checkable
class StorageProvider(Protocol):
    """Object-storage operations behind a single cloud-neutral port.

    An instance is bound to one bucket/container (see
    `shared.providers.get_storage_provider`). Keys are tenant-prefixed
    (`{tenant_id}/...`); callers validate the prefix before passing a key —
    the provider does no authorization.
    """

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int,
        response_content_disposition: str | None = None,
    ) -> str:
        """Return a short-lived read URL for `key`.

        `response_content_disposition`, when set, overrides the download
        `Content-Disposition` header the storage service returns (e.g.
        `inline; filename="x.pdf"`).
        """
        ...

    def presigned_upload(self, key: str, *, content_type: str, expires_in: int) -> UploadTicket:
        """Return an `UploadTicket` for a direct browser PUT to `key`."""
        ...

    def put_object(self, key: str, body: bytes, *, content_type: str) -> None:
        """Write `body` to `key` server-side."""
        ...

    def get_object(self, key: str) -> bytes:
        """Read and return the full contents of `key`."""
        ...

    def object_size(self, key: str) -> int | None:
        """Return the byte size of `key`, or None if it does not exist."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix` (including versions, for GDPR
        erasure) and return the count removed."""
        ...


@runtime_checkable
class SecretsProvider(Protocol):
    """Secret retrieval behind a cloud-neutral port.

    Returns the raw secret string exactly as stored (callers that store JSON
    parse it themselves), so AWS Secrets Manager `SecretString` and Azure Key
    Vault secret values map identically.
    """

    def get_secret(self, secret_id: str) -> str:
        """Return the secret value for `secret_id` (an ARN/name/URI)."""
        ...


@runtime_checkable
class EventProvider(Protocol):
    """Domain-event publishing behind a cloud-neutral port.

    The envelope (event_id, occurred_at, tenant_id, payload) is built by
    `shared/events.py`; this port only delivers one already-formed event and
    raises on failure. AWS → EventBridge `put_events`; Azure → Event Grid.
    """

    def publish(self, *, source: str, detail_type: str, detail: dict[str, Any], bus_name: str) -> None:
        """Publish one event. Raise `ExternalServiceError` on delivery failure."""
        ...


@runtime_checkable
class QueueProvider(Protocol):
    """Async message queue behind a cloud-neutral port.

    `destination` is an opaque queue reference the caller resolves from config
    (an SQS queue URL on AWS; a Service Bus queue name on Azure). AWS →
    `send_message`; Azure → Service Bus `send_messages`.
    """

    def send(self, *, destination: str, body: str) -> None:
        """Enqueue `body` (a serialized string) to `destination`."""
        ...


@runtime_checkable
class EmailProvider(Protocol):
    """Transactional email behind a cloud-neutral port.

    AWS → SES `send_email`; Azure → Communication Services email. Raises on a
    hard send failure so the caller's retry/log path runs.
    """

    def send(self, *, sender: str, to_email: str, subject: str, html_body: str, text_body: str) -> None:
        """Send one multipart (HTML + text) email. Raise on delivery failure."""
        ...
