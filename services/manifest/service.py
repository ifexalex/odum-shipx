"""Business logic for the Manifest service.

Manifests are auto-created by the packing list approval flow (Task 08).
This service provides read access and the verification workflow.
"""

import logging
import os
from typing import Any

import boto3

from shared.audit import log_audit
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError
from shared.validation import safe_filename

from . import repository as repo
from .models import ResolveDiscrepancyRequest, VerificationStatus, VerifyManifestRequest

logger = logging.getLogger(__name__)

# Items where actual weight diverges from dispatch weight by more than this
# fraction (5 %) OR by more than 0.1 kg are flagged as discrepancies.
_WEIGHT_DISCREPANCY_THRESHOLD_PCT = 0.05
_WEIGHT_DISCREPANCY_MIN_KG = 0.1

# S3-backed verification evidence (mirrors services/claims/service.py limits).
_s3_client = boto3.client("s3")
_BUCKET = os.environ.get("S3_BUCKET_NAME", "logistics-assets")
_ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_URL_EXPIRY = 3600  # 1 hour


def _serialize_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Evidence row → wire shape with a short-lived presigned GET download URL."""
    download_url = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": row["file_key"]},
        ExpiresIn=_URL_EXPIRY,
    )
    return {
        "id": str(row["id"]),
        "file_name": row["file_name"],
        "file_type": row["file_type"],
        "label": row.get("label"),
        "created_at": row.get("created_at"),
        "download_url": download_url,
    }


def _compute_weight_discrepancies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return items where weight_actual_kg diverges meaningfully from weight_dispatch_kg."""
    discrepancies = []
    for item in items:
        dispatch = item.get("weight_dispatch_kg")
        actual = item.get("weight_actual_kg")
        if dispatch is None or actual is None:
            continue
        try:
            dispatch_f = float(dispatch)
            actual_f = float(actual)
        except (TypeError, ValueError):
            continue
        diff = abs(actual_f - dispatch_f)
        threshold = max(_WEIGHT_DISCREPANCY_MIN_KG, dispatch_f * _WEIGHT_DISCREPANCY_THRESHOLD_PCT)
        if diff > threshold:
            discrepancies.append(
                {
                    "item_id": item.get("id"),
                    "carton_tag": item.get("carton_tag"),
                    "tracking_code": item.get("tracking_code"),
                    "customer_id": item.get("customer_id"),
                    "weight_dispatch_kg": dispatch_f,
                    "weight_actual_kg": actual_f,
                    "difference_kg": round(actual_f - dispatch_f, 3),
                }
            )
    return discrepancies


def get_manifest(tenant_id: str, manifest_id: str) -> dict[str, Any]:
    """Fetch a manifest with per-customer summaries, weight discrepancies, and missing items."""
    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)
    customers = repo.get_customer_summaries(tenant_id, manifest_id)
    items = repo.get_items_with_weights_for_manifest(tenant_id, manifest_id)
    missing_items = repo.get_missing_items_for_manifest(tenant_id, manifest_id)
    evidence = repo.list_manifest_evidence(tenant_id, manifest_id)
    return {
        **manifest,
        "customers": customers,
        "weight_discrepancies": _compute_weight_discrepancies(items),
        "missing_items": [
            {
                "id": str(mi["id"]),
                "customer_id": str(mi["customer_id"]),
                "carton_tags": list(mi.get("carton_tags") or []),
                "description": mi.get("description"),
                "status": mi.get("status"),
            }
            for mi in missing_items
        ],
        "evidence": [_serialize_evidence(e) for e in evidence],
    }


def list_manifests(
    tenant_id: str,
    filters: dict[str, Any],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return a paginated list of manifests for the tenant."""
    return repo.list_manifests(tenant_id, filters, limit, cursor)


def get_manifest_stats(tenant_id: str) -> dict[str, int]:
    """Per-verification-status counts + overdue for the list stats row (§6.2, P2-4)."""
    return repo.get_manifest_stats(tenant_id)


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
    items = repo.get_items_with_weights_for_manifest(tenant_id, manifest_id)
    return {**updated, "customers": customers, "weight_discrepancies": _compute_weight_discrepancies(items)}


def generate_evidence_upload(
    tenant_id: str,
    manifest_id: str,
    filename: str,
    content_type: str,
    actor_id: str,
    label: str | None = None,
) -> dict[str, Any]:
    """Presign an S3 POST for a manifest-verification photo/doc (§6.3).

    Mirrors the claims evidence flow: validates the content type, confirms the
    manifest belongs to the tenant, records a `manifest_evidence` row, and
    returns the presigned POST plus the resulting file_key. The browser uploads
    directly to S3; tenant isolation comes from the `{tenant_id}/manifests/...`
    key prefix and the tenant-scoped manifest lookup.
    """
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise BusinessRuleViolationError(
            f"content_type '{content_type}' is not allowed. " f"Allowed: {', '.join(sorted(_ALLOWED_CONTENT_TYPES))}",
            rule_id="INVALID_CONTENT_TYPE",
        )

    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    filename = safe_filename(filename)
    file_key = f"{tenant_id}/manifests/{manifest_id}/{filename}"

    presigned = _s3_client.generate_presigned_post(
        Bucket=_BUCKET,
        Key=file_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, _MAX_FILE_SIZE],
        ],
        ExpiresIn=_URL_EXPIRY,
    )

    evidence = repo.create_manifest_evidence(
        tenant_id,
        {
            "manifest_id": manifest_id,
            "file_key": file_key,
            "file_name": filename,
            "file_type": content_type,
            "file_size_bytes": None,
            "label": label,
            "uploaded_by": actor_id,
        },
    )

    return {
        "upload_url": presigned["url"],
        "fields": presigned["fields"],
        "evidence_id": str(evidence["id"]) if evidence else None,
        "file_key": file_key,
    }


def revoke_verification(
    tenant_id: str,
    manifest_id: str,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Revert a verified manifest back to pending.

    Transition: verified → pending.
    Clears verified_by and verified_at so the manifest can be re-verified.
    Only allowed while the manifest is still in 'verified' status — once
    downstream processes (release notes, customs) have consumed it, revocation
    should be blocked at the business process level, not here.
    """
    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    current_status = manifest["verification_status"]
    if current_status != "verified":
        raise BusinessRuleViolationError(
            f"Manifest is '{current_status}' — only 'verified' manifests can have their verification revoked",
            rule_id="MANIFEST_NOT_VERIFIED",
        )

    container_status = manifest.get("container_status")
    if container_status and container_status != "loading":
        raise BusinessRuleViolationError(
            f"Cannot revoke verification — the container is already '{container_status}'. "
            "Verification can only be revoked while the container is still in 'loading' status.",
            rule_id="CONTAINER_ALREADY_ADVANCED",
        )

    updated = repo.revoke_manifest_verification(tenant_id, manifest_id)
    if updated is None:
        raise RuntimeError("revoke_manifest_verification returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="manifest",
        entity_id=manifest_id,
        action="STATUS_CHANGE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"verification_status": "verified"},
        after_state={"verification_status": "pending"},
        ip_address=ip_address,
    )

    customers = repo.get_customer_summaries(tenant_id, manifest_id)
    items = repo.get_items_with_weights_for_manifest(tenant_id, manifest_id)
    return {**updated, "customers": customers, "weight_discrepancies": _compute_weight_discrepancies(items)}


def resolve_discrepancy(
    tenant_id: str,
    manifest_id: str,
    req: ResolveDiscrepancyRequest,
    actor_id: str,
    ctx: Any,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Close out a discrepancies_found manifest after staff resolution.

    Transitions: discrepancies_found → resolved.
    Guards: manifest must be in discrepancies_found state.
    """
    manifest = repo.get_manifest_by_id(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    current_status = manifest["verification_status"]
    if current_status != "discrepancies_found":
        raise BusinessRuleViolationError(
            f"Manifest is '{current_status}' — only 'discrepancies_found' manifests can be resolved",
            rule_id="MANIFEST_NOT_DISCREPANCIES_FOUND",
        )

    updated = repo.resolve_manifest_discrepancy(
        tenant_id,
        manifest_id,
        resolved_by=actor_id,
        resolution_notes=req.resolution_notes,
        final_counts=req.final_counts,
    )
    if updated is None:
        raise RuntimeError("resolve_manifest_discrepancy returned None unexpectedly")

    log_audit(
        tenant_id=tenant_id,
        entity_type="manifest",
        entity_id=manifest_id,
        action="DISCREPANCY_RESOLVED",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        before_state={"verification_status": current_status},
        after_state={"verification_status": "resolved", "resolution_notes": req.resolution_notes},
        ip_address=ip_address,
    )

    customers = repo.get_customer_summaries(tenant_id, manifest_id)
    return {**updated, "customers": customers}
