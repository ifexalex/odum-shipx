"""Business logic for the Manifest service.

Manifests are auto-created by the packing list approval flow (Task 08).
This service provides read access and the verification workflow.
"""

import logging
from typing import Any

from shared.audit import log_audit
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError

from . import repository as repo
from .models import VerificationStatus, VerifyManifestRequest

logger = logging.getLogger(__name__)


def get_manifest(tenant_id: str, manifest_id: str) -> dict[str, Any]:
    """Fetch a manifest with per-customer aggregated summaries."""
    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)
    customers = repo.get_customer_summaries(tenant_id, manifest_id)
    return {**manifest, "customers": customers}


def list_manifests(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return a paginated list of manifests for the tenant."""
    return repo.list_manifests(tenant_id, filters, limit, cursor)


def verify_manifest(
    tenant_id: str,
    manifest_id: str,
    req: VerifyManifestRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Verify a manifest or log discrepancies.

    Transitions:
      pending → verified            (all items accounted for)
      pending → discrepancies_found (missing/damaged items noted)

    For each discrepancy with type='missing', a missing_item record is created
    per carton_tag. Damaged items are noted in the discrepancy list but no
    record is created — damage claims are filed via a separate workflow.
    """
    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    current_status = manifest["verification_status"]
    if current_status != "pending":
        raise BusinessRuleViolationError(
            f"Manifest verification_status is already '{current_status}' — only 'pending' manifests can be verified",
            rule_id="MANIFEST_ALREADY_VERIFIED",
        )

    if req.verification_status == VerificationStatus.verified:
        updated = repo.set_manifest_verified(
            tenant_id,
            manifest_id,
            actor_id,
            notes=None,
        )

    else:  # discrepancies_found
        updated = repo.set_manifest_discrepancies_found(tenant_id, manifest_id, actor_id)

        for discrepancy in req.discrepancies or []:
            if discrepancy.type != "missing":
                # 'damaged' discrepancies are recorded in the request payload but
                # do not create missing_item rows — damage claims filed separately.
                continue
            for carton_tag in discrepancy.carton_tags:
                item = repo.get_item_by_carton_tag(tenant_id, carton_tag)
                repo.create_missing_item(
                    tenant_id,
                    {
                        "tenant_id": tenant_id,
                        "manifest_id": manifest_id,
                        "customer_id": discrepancy.customer_id,
                        "packing_list_id": item["packing_list_id"] if item else None,
                        "carton_tag": carton_tag,
                        "tracking_code": item["tracking_code"] if item else None,
                        "description": discrepancy.notes or f"Missing item \u2014 carton tag {carton_tag}",
                        "notes": discrepancy.notes,
                        "reported_by": actor_id,
                    },
                )

    log_audit(
        tenant_id=tenant_id,
        entity_type="manifest",
        entity_id=manifest_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"verification_status": current_status},
        after_state={"verification_status": req.verification_status},
        ip_address=ip_address,
    )

    if updated is None:
        raise RuntimeError("manifest verification returned None unexpectedly")
    customers = repo.get_customer_summaries(tenant_id, manifest_id)
    return {**updated, "customers": customers}
