"""Direct-to-storage uploads: which files are accepted, where they go, and the presigned URL (audit BE-12).

Every browser upload follows the same three steps, and this module is the one place that does them:

  1. ``policy.check_content_type(content_type)``: refuse a type the policy does not list, before any database work.
  2. The caller confirms the record the file belongs to exists in this tenant (a claim, a manifest, an invoice).
  3. ``presign_upload(policy, tenant_id, segments, filename, content_type)``: build the key under the tenant's prefix
     and return the presigned upload.

Keys are always ``{tenant_id}/{segment}/.../{safe filename}``: the tenant prefix is what the download paths and the
import guard check, so it is built here and nowhere else. Segments come from the server (a resource name and an ID),
never from the client, and are refused if they could change the key's structure.

The type is declared by the client; nothing inspects the bytes. On AWS it is signed into the URL (SigV4), so S3
refuses a PUT whose ``Content-Type`` differs. An Azure SAS does not bind the type, and the local Moto S3 does not
enforce it either (checked 2026-11-17): there the declared type is a check on the request, not on the upload.
``application/octet-stream`` ("unknown") is never accepted: allowing it let any file through the type check.

The upload size is not limited yet. A presigned PUT carries no size condition on either cloud unless the client
declares the length up front and it is signed in; see the runbook's open items.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from shared.exceptions import BusinessRuleViolationError
from shared.providers import get_storage_provider
from shared.validation import safe_filename

_IMAGES_AND_PDF = frozenset({"image/jpeg", "image/png", "application/pdf"})


@dataclass(frozen=True)
class UploadPolicy:
    """What one kind of upload accepts.

    Attributes:
        name: Short label for the kind of upload, used in error messages.
        content_types: MIME types the client may declare.
        expires_in: Lifetime of the presigned URL, in seconds.
    """

    name: str
    content_types: frozenset[str]
    expires_in: int

    def __post_init__(self) -> None:
        if "application/octet-stream" in self.content_types:
            raise ValueError("application/octet-stream defeats the type check; list the real types instead")

    def check_content_type(self, content_type: str) -> None:
        """Refuse a type this policy does not accept.

        Raises:
            BusinessRuleViolationError: ``INVALID_CONTENT_TYPE``, naming the accepted types.
        """
        if content_type not in self.content_types:
            raise BusinessRuleViolationError(
                f"content_type '{content_type}' is not allowed. Allowed: {', '.join(sorted(self.content_types))}",
                rule_id="INVALID_CONTENT_TYPE",
            )


#: Photos and documents attached as evidence: damage claims, manifest verification, payment claims.
EVIDENCE = UploadPolicy(name="evidence", content_types=_IMAGES_AND_PDF, expires_in=3600)

#: Container documents (bill of lading, customs certificate, ...). WebP for phone photos of paperwork.
CONTAINER_DOCUMENT = UploadPolicy(name="container document", content_types=_IMAGES_AND_PDF | {"image/webp"}, expires_in=900)

#: A packing-list spreadsheet, read once by the import and never listed.
SPREADSHEET_IMPORT = UploadPolicy(
    name="spreadsheet import",
    content_types=frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    expires_in=900,
)


@dataclass(frozen=True)
class PresignedUpload:
    """A presigned upload and the key the file will land at.

    Attributes:
        key: The storage key, under the tenant's prefix.
        expires_in: Seconds until the URL stops working.
        ticket: The provider's upload ticket (URL, method, headers the browser must send).
    """

    key: str
    expires_in: int
    ticket: Any

    def as_response(self) -> dict[str, Any]:
        """The ticket's wire fields (``upload_url``, ``upload_method``, ``upload_headers``, ...)."""
        response: dict[str, Any] = self.ticket.as_response()
        return response


def upload_key(tenant_id: str, segments: tuple[str, ...], filename: str) -> str:
    """The storage key for an upload: ``{tenant_id}/{segments...}/{safe filename}``.

    Args:
        tenant_id: The tenant's UUID; it must be one, so the prefix cannot be anything else.
        segments: Server-chosen path parts, e.g. ``("claims", claim_id)``.
        filename: The client's file name, reduced by ``safe_filename``.

    Raises:
        ValueError: The tenant ID is not a UUID, or a segment is empty or holds ``/``, ``\\`` or ``..``.
    """
    UUID(tenant_id)
    for segment in segments:
        if not segment or "/" in segment or "\\" in segment or ".." in segment:
            raise ValueError(f"unsafe upload key segment: {segment!r}")
    return "/".join((tenant_id, *segments, safe_filename(filename)))


def presign_upload(
    policy: UploadPolicy, tenant_id: str, segments: tuple[str, ...], filename: str, content_type: str
) -> PresignedUpload:
    """Check the type, build the tenant-prefixed key and presign the upload.

    Args:
        policy: What this kind of upload accepts.
        tenant_id: The tenant the file belongs to.
        segments: Server-chosen path parts under the tenant prefix.
        filename: The client's file name.
        content_type: The type the client declared; signed into the URL.

    Raises:
        BusinessRuleViolationError: ``INVALID_CONTENT_TYPE``.
        ValueError: An unsafe tenant ID or segment (a server bug, not a client error).
    """
    policy.check_content_type(content_type)
    key = upload_key(tenant_id, segments, filename)
    ticket = get_storage_provider().presigned_upload(key, content_type=content_type, expires_in=policy.expires_in)
    return PresignedUpload(key=key, expires_in=policy.expires_in, ticket=ticket)
