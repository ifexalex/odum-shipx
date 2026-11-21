"""Direct-to-storage uploads: which files are accepted, where they go, and the presigned URL (audit BE-12).

Every browser upload follows the same three steps, and this module is the one place that does them:

  1. ``policy.check_content_type(content_type)``: refuse a type the policy does not list, before any database work.
  2. The caller confirms the record the file belongs to exists in this tenant (a claim, a manifest, an invoice).
  3. ``presign_upload(policy, tenant_id, segments, filename, content_type)``: build the key under the tenant's prefix
     and return the presigned upload.

Keys are always ``{tenant_id}/{segment}/.../{random hex}-{safe filename}``: the tenant prefix is what the download
paths and the import guard check, so it is built here and nowhere else. Segments come from the server (a resource name
and an ID), never from the client, and are refused if they could change the key's structure. The random part keeps two
uploads of ``photo.jpg`` to one claim from overwriting each other, so deleting one never deletes the other.

The type is declared by the client; nothing inspects the bytes. On AWS it is signed into the URL (SigV4), so S3
refuses a PUT whose ``Content-Type`` differs. An Azure SAS does not bind the type, and the local Moto S3 does not
enforce it either (checked 2026-11-17): there the declared type is a check on the request, not on the upload.
``application/octet-stream`` ("unknown") is never accepted: allowing it let any file through the type check.

Every upload is limited to ``MAX_UPLOAD_BYTES`` (5 MB). The client declares the file's size with the presign request
and a larger or missing size is refused there. On AWS the declared size is signed into the URL (``ContentLength``), so
S3 refuses a body of any other length. An Azure SAS cannot bind a length, so where a stored file is used later (a
payment claim, a spreadsheet import) ``check_stored_size`` reads its real size and refuses it if it is over.

A file that is listed once uploaded (claim evidence, manifest evidence, container documents) has a row written at
presign time that stays hidden until the client confirms the upload. ``confirm_stored_upload`` is that confirmation:
it reads the stored size, deletes a file over the limit, and the caller then stamps the row ``confirmed_at``. An upload
the client never confirms is never listed.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from shared.exceptions import BusinessRuleViolationError, ValidationError
from shared.providers import get_storage_provider
from shared.validation import safe_filename

_IMAGES_AND_PDF = frozenset({"image/jpeg", "image/png", "application/pdf"})

#: The largest file any upload accepts.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class UploadPolicy:
    """What one kind of upload accepts.

    Attributes:
        name: Short label for the kind of upload, used in error messages.
        content_types: MIME types the client may declare.
        expires_in: Lifetime of the presigned URL, in seconds.
        max_bytes: The largest file this kind of upload accepts.
    """

    name: str
    content_types: frozenset[str]
    expires_in: int
    max_bytes: int = MAX_UPLOAD_BYTES

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

    def check_size(self, size_bytes: object) -> int:
        """The declared file size, if it is a whole number of bytes from 1 to ``max_bytes``.

        Raises:
            ValidationError: The size is missing or not a positive whole number.
            BusinessRuleViolationError: ``FILE_TOO_LARGE``, over ``max_bytes``.
        """
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
            raise ValidationError(
                "size_bytes is required: the file's size in bytes",
                field_errors={"size_bytes": "Send the file's size in bytes."},
            )
        if size_bytes > self.max_bytes:
            raise BusinessRuleViolationError(
                f"The file is larger than {self.max_bytes // (1024 * 1024)} MB.", rule_id="FILE_TOO_LARGE"
            )
        return size_bytes

    def check(self, content_type: str, size_bytes: object) -> int:
        """Both checks, before any database work. Returns the size."""
        self.check_content_type(content_type)
        return self.check_size(size_bytes)


#: Photos and documents attached as evidence: damage claims, manifest verification, payment claims.
EVIDENCE = UploadPolicy(name="evidence", content_types=_IMAGES_AND_PDF, expires_in=3600)

#: Container documents (bill of lading, customs certificate, ...). WebP for phone photos of paperwork.
CONTAINER_DOCUMENT = UploadPolicy(name="container document", content_types=_IMAGES_AND_PDF | {"image/webp"}, expires_in=900)

#: A tenant's logo (FD-29): raster images only. SVG is refused, since an SVG can carry script and the logo is shown to
#: every user of the tenant and on its public pages. 1 MB is ample for a logo and keeps documents light.
TENANT_LOGO = UploadPolicy(
    name="logo",
    content_types=frozenset({"image/png", "image/jpeg", "image/webp"}),
    expires_in=900,
    max_bytes=1024 * 1024,
)
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
        filename: The client's file name made safe, without the key's random part: the name to show and download as.
        expires_in: Seconds until the URL stops working.
        ticket: The provider's upload ticket (URL, method, headers the browser must send).
    """

    key: str
    filename: str
    expires_in: int
    ticket: Any

    def as_response(self) -> dict[str, Any]:
        """The ticket's wire fields (``upload_url``, ``upload_method``, ``upload_headers``, ...)."""
        response: dict[str, Any] = self.ticket.as_response()
        return response


def upload_key(tenant_id: str, segments: tuple[str, ...], filename: str) -> str:
    """The storage key for an upload: ``{tenant_id}/{segments...}/{random hex}-{safe filename}``.

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
    return "/".join((tenant_id, *segments, f"{uuid4().hex}-{safe_filename(filename)}"))


def presign_upload(
    policy: UploadPolicy,
    tenant_id: str,
    segments: tuple[str, ...],
    filename: str,
    content_type: str,
    size_bytes: object,
) -> PresignedUpload:
    """Check the type, build the tenant-prefixed key and presign the upload.

    Args:
        policy: What this kind of upload accepts.
        tenant_id: The tenant the file belongs to.
        segments: Server-chosen path parts under the tenant prefix.
        filename: The client's file name.
        content_type: The type the client declared; signed into the URL.
        size_bytes: The size the client declared; signed into the URL where the provider can bind it (AWS).

    Raises:
        BusinessRuleViolationError: ``INVALID_CONTENT_TYPE`` or ``FILE_TOO_LARGE``.
        ValidationError: No usable ``size_bytes``.
        ValueError: An unsafe tenant ID or segment (a server bug, not a client error).
    """
    size = policy.check(content_type, size_bytes)
    key = upload_key(tenant_id, segments, filename)
    ticket = get_storage_provider().presigned_upload(
        key, content_type=content_type, expires_in=policy.expires_in, content_length=size
    )
    return PresignedUpload(key=key, filename=safe_filename(filename), expires_in=policy.expires_in, ticket=ticket)


def check_stored_size(policy: UploadPolicy, key: str) -> int:
    """The stored file's real size, refusing a missing file or one over the policy's limit.

    For where a stored upload is used (a payment claim, a spreadsheet import): an Azure SAS cannot bind the size, and
    this is the check that holds there.

    Raises:
        BusinessRuleViolationError: ``UPLOAD_NOT_FOUND`` (nothing at ``key``) or ``FILE_TOO_LARGE``.
    """
    size = get_storage_provider().object_size(key)
    if size is None:
        raise BusinessRuleViolationError("The uploaded file was not found. Upload it again.", rule_id="UPLOAD_NOT_FOUND")
    if size > policy.max_bytes:
        raise BusinessRuleViolationError(
            f"The file is larger than {policy.max_bytes // (1024 * 1024)} MB.", rule_id="FILE_TOO_LARGE"
        )
    return size


def confirm_stored_upload(policy: UploadPolicy, key: str) -> int:
    """Confirm a browser upload landed: return its size, or delete it and refuse it if it is over the limit.

    The check that holds on Azure, where a SAS cannot bind the upload's length. On AWS the signed length already
    refused a larger body, so this only confirms the file is there.

    Raises:
        BusinessRuleViolationError: ``UPLOAD_NOT_FOUND`` (nothing at ``key``: the upload did not finish) or
            ``FILE_TOO_LARGE`` (the stored file was over the limit and has been deleted).
    """
    size = get_storage_provider().object_size(key)
    if size is None:
        raise BusinessRuleViolationError("The uploaded file was not found. Upload it again.", rule_id="UPLOAD_NOT_FOUND")
    if size > policy.max_bytes:
        get_storage_provider().delete_object(key)
        raise BusinessRuleViolationError(
            f"The file is larger than {policy.max_bytes // (1024 * 1024)} MB.", rule_id="FILE_TOO_LARGE"
        )
    return size
