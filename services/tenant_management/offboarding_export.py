"""A leaving tenant's data export (audit BE-10).

Status, queueing a new one, and the five-minute download link.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from shared import tenant_export
from shared.exceptions import (
    BusinessRuleViolationError,
)
from shared.providers import get_storage_provider

from . import repository as repo

if TYPE_CHECKING:
    pass
from .tenants import get_tenant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Offboarding data export (audit BE-10)
# ---------------------------------------------------------------------------

#: How long a download link for an offboarding archive works.
EXPORT_LINK_SECONDS = 300

_FILENAME_UNSAFE = re.compile(r"[^a-z0-9-]+")


def _current_export(tenant: dict[str, Any]) -> dict[str, Any] | None:
    """The latest export for the tenant's latest offboarding; one from an earlier offboarding does not count."""
    if tenant["status"] != "offboarded":
        return None
    export = tenant_export.latest_export(str(tenant["id"]))
    offboarded_at = tenant.get("offboarded_at")
    if export is None or (offboarded_at is not None and export["requested_at"] < offboarded_at):
        return None
    return export


def get_offboarding_export(tenant_id: str) -> dict[str, Any]:
    """Where the tenant's offboarding export stands, for the platform tenant page.

    Returns:
        ``status`` (``none`` when nothing is queued for the current offboarding, else the export's status), the
        export's id, times, size, checksum and row count, how many attempts it has had, whether it is still being
        retried, whether a platform admin may queue one now, and when the tenant's data is due to be deleted.
    """
    tenant = get_tenant(tenant_id)
    export = _current_export(tenant)
    row_counts = (export or {}).get("row_counts") or {}
    status = export["status"] if export else "none"
    attempts = int(export["attempts"]) if export else 0
    return {
        "tenant_status": tenant["status"],
        "status": status,
        "export_id": str(export["id"]) if export else None,
        "requested_at": export["requested_at"] if export else None,
        "completed_at": export.get("completed_at") if export else None,
        "size_bytes": export.get("size_bytes") if export else None,
        "sha256": export.get("sha256") if export else None,
        "row_count": sum(int(n) for n in row_counts.values()) if export else None,
        "attempts": attempts,
        "max_attempts": tenant_export.MAX_ATTEMPTS,
        "retrying": status == "failed" and attempts < tenant_export.MAX_ATTEMPTS,
        "can_queue": tenant["status"] == "offboarded"
        and (status in {"none", "cancelled"} or (status == "failed" and attempts >= tenant_export.MAX_ATTEMPTS)),
        "deletion_scheduled_at": tenant.get("deletion_scheduled_at"),
    }


def queue_offboarding_export(tenant_id: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """Queue an export for an offboarded tenant that has none, or whose export gave up.

    For tenants offboarded before exports existed, and for an export that failed every attempt.

    Raises:
        BusinessRuleViolationError: The tenant is not offboarded, or an export is already queued, running, retrying
            or done.
    """
    tenant = get_tenant(tenant_id)
    if tenant["status"] != "offboarded":
        raise BusinessRuleViolationError(
            "Only an offboarded tenant has an offboarding export.", rule_id="OFFBOARDING_EXPORT_NOT_OFFBOARDED"
        )
    current = get_offboarding_export(tenant_id)
    if not current["can_queue"]:
        raise BusinessRuleViolationError(
            f"This tenant's export is already {current['status']}.", rule_id="OFFBOARDING_EXPORT_IN_PROGRESS"
        )
    if current["status"] == "failed":
        tenant_export.mark_cancelled(current["export_id"])
    queued = tenant_export.queue_export(tenant_id, requested_by=actor_id)
    if queued is None:
        raise BusinessRuleViolationError("An export was queued by another request.", rule_id="OFFBOARDING_EXPORT_IN_PROGRESS")
    try:
        repo.insert_platform_audit(
            action="TENANT_EXPORT_QUEUED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"export_id": str(queued["id"])},
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Platform audit insert failed: %s", exc)
    return get_offboarding_export(tenant_id)


def create_offboarding_export_link(tenant_id: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """A five-minute download link to the tenant's completed offboarding archive. Every link is audited.

    Raises:
        BusinessRuleViolationError: No export of the current offboarding has completed.
    """
    tenant = get_tenant(tenant_id)
    export = _current_export(tenant)
    if export is None or export["status"] != "completed":
        raise BusinessRuleViolationError("The export is not ready yet.", rule_id="OFFBOARDING_EXPORT_NOT_READY")
    key = str(export["object_key"])
    # The key comes from our own record, but it is still checked to sit in this tenant's export folder before a
    # link to it is signed.
    if not key.startswith(tenant_export.export_prefix(tenant_id)) or ".." in key:
        logger.error("Offboarding export %s has a key outside its tenant's export folder", export["id"])
        raise BusinessRuleViolationError("The export is not available.", rule_id="OFFBOARDING_EXPORT_NOT_READY")

    slug = _FILENAME_UNSAFE.sub("-", str(tenant.get("slug") or "tenant").lower()).strip("-") or "tenant"
    completed = export.get("completed_at") or datetime.now(UTC)
    filename = f"shipx-export-{slug}-{completed:%Y%m%d}.zip"
    url = get_storage_provider().presigned_get_url(
        key, expires_in=EXPORT_LINK_SECONDS, response_content_disposition=f'attachment; filename="{filename}"'
    )
    try:
        repo.insert_platform_audit(
            action="TENANT_EXPORT_LINK_ISSUED",
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            details={"export_id": str(export["id"])},
            ip_address=ip_address,
        )
    except Exception as exc:
        # The link is a download of every customer's personal data: no record, no link.
        logger.warning("Platform audit insert failed; refusing the export link: %s", exc)
        raise
    return {
        "download_url": url,
        "expires_at": datetime.now(UTC) + timedelta(seconds=EXPORT_LINK_SECONDS),
        "filename": filename,
        "size_bytes": export.get("size_bytes"),
        "sha256": export.get("sha256"),
    }
