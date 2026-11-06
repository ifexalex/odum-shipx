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


@runtime_checkable
class IdentityProvider(Protocol):
    """User/role provisioning behind a cloud-neutral port.

    The *management* side of identity — create/disable/update users and reconcile
    their role grants. AWS → Cognito user-pool admin APIs; Azure → Entra (MS
    Graph). The authN side (JWT verification + claim shape) is a separate concern
    handled at the authorizer; see ADR-004. Email is the stable user identifier
    (`username`), per the "email immutable" constraint.
    """

    def create_user(self, email: str, full_name: str, tenant_id: str, role: str) -> str:
        """Provision a user who receives an invite to set their password. Returns the user id (`sub`)."""
        ...

    def create_user_with_password(self, email: str, full_name: str, tenant_id: str, role: str, password: str) -> str:
        """Provision a user with a caller-chosen permanent password (no invite email). Returns the user id."""
        ...

    def update_user_attributes(self, username: str, full_name: str | None = None, role: str | None = None) -> None:
        """Update a user's mutable attributes (display name, primary role)."""
        ...

    def disable_user(self, username: str) -> None:
        """Deactivate a user account."""
        ...

    def enable_user(self, username: str) -> None:
        """Re-activate a previously disabled user account."""
        ...

    def global_sign_out(self, username: str) -> None:
        """Invalidate all of a user's active sessions. Missing user is a no-op."""
        ...

    def resend_invite(self, username: str) -> None:
        """Re-send the password-setup invite to an existing user."""
        ...

    def reset_password(self, username: str) -> None:
        """Trigger a provider-managed password-reset email."""
        ...

    def set_password(self, username: str, password: str, force_change: bool = False) -> None:
        """Set a user's password directly (admin), for the ShipX account-activation
        flow — the user chooses their own password via a ShipX link. `force_change`
        False means the chosen password is final."""
        ...

    def create_group_if_not_exists(self, group_name: str) -> None:
        """Ensure a role group exists (idempotent)."""
        ...

    def add_user_to_group(self, username: str, group_name: str) -> None:
        """Grant a user membership of a role group."""
        ...

    def remove_user_from_group(self, username: str, group_name: str) -> None:
        """Revoke a user's membership of a role group. Missing user is a no-op."""
        ...

    def list_groups_for_user(self, username: str) -> set[str]:
        """Return the set of role groups a user currently belongs to."""
        ...

    def sync_user_groups(self, username: str, tenant_id: str, roles: set[str]) -> None:
        """Reconcile a user's role groups to exactly `roles`, scoped to this tenant's `{tenant_id}:*`."""
        ...


@runtime_checkable
class ClaimsMapper(Protocol):
    """Translate a verified JWT's raw claims into ShipX's logical identity fields.

    Only the claim *names/shape* are cloud-specific — Cognito's `custom:tenant_id`
    / `cognito:groups` / `custom:role` vs Entra's extension attributes + role
    claims. The downstream *interpretation* (the `{tenant_id}:{role}` group format,
    the `platform_admin` special case, the primary-role fallback) stays in
    `shared/auth.py` and is cloud-agnostic. An Entra mapper therefore normalizes
    its claims into the same canonical shapes these methods return (notably
    `groups()` → `{tenant_id}:{role}` strings), so `auth.py` never changes.
    """

    def user_id(self, claims: dict[str, Any]) -> str:
        """The stable user id (Cognito `sub` / Entra `oid`); empty string if absent."""
        ...

    def tenant_id(self, claims: dict[str, Any]) -> str:
        """The tenant UUID claim; empty string if absent."""
        ...

    def groups(self, claims: dict[str, Any]) -> list[str]:
        """Role-group names in canonical `{tenant_id}:{role}` form (plus `platform_admin`)."""
        ...

    def primary_role(self, claims: dict[str, Any]) -> str | None:
        """The user's primary-role claim value, or None if absent."""
        ...
