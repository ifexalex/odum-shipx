"""Tenant Data Cleanup — runs daily at 02:00 UTC.

For each tenant with status = 'offboarded':
  If (NOW() - offboarded_at) > 90 days:
    1. Delete tables that have no tenant_id column (via subquery).
    2. Delete all tenant data in FK-safe order (tables with tenant_id).
    3. Delete tenant S3 prefix (TENANT_DATA_BUCKET / tenant_id/).
    4. Delete Cognito users for this tenant (COGNITO_USER_POOL_ID).
    5. Anonymise platform_audit_log rows referencing this tenant (GDPR Art. 17).
    6. Delete the tenant record itself.
    7. Log in audit_log (platform scope).
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from aws_xray_sdk.core import patch_all

from shared.audit import log_audit
from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.tenant_context import PLATFORM_TENANT_ID

setup_logging()
patch_all()

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 90
_SYSTEM_ACTOR = "system"
_SYSTEM_ROLE = "scheduler"

# Tables deleted in FK-safe leaf-first order (all have a tenant_id column).
# claim_evidence is intentionally absent: it has no tenant_id and is
# cascade-deleted automatically when damage_claim rows are removed.
_DELETE_ORDER = [
    "storage_fee_log",  # → billing, container, customer
    "pickup_record",  # → release_note, customer
    "release_note",  # → billing, customer, container
    "payment_record",  # → billing
    "carryover_ledger",  # → billing, customer
    "claim_resolution",  # → damage_claim (RESTRICT FK — must precede damage_claim)
    "refund_request",  # → damage_claim, customer, billing
    "damage_claim",  # cascade-deletes claim_evidence automatically
    "cbm_dispute",  # → billing, customer, packing_list
    "missing_item",  # → manifest, customer, packing_list
    "seized_item",  # → container, customer, packing_list_item
    "audit_log",
    "usage_record",
    "shipment_tracking",  # → container
    "manifest",  # → container, packing_list
    "packing_list",  # → customer, container (cascade-deletes packing_list_item)
    "billing",  # → customer, container, packing_list
    "container",
    "customer",
    "tenant_user",
    "tenant_config",
]

# Tables that have no tenant_id column and must be deleted via a subquery
# before the main _DELETE_ORDER loop runs.
_SPECIAL_DELETES: list[tuple[str, str]] = [
    (
        "packing_list_item",
        "DELETE FROM packing_list_item "
        "WHERE packing_list_id IN "
        "(SELECT id FROM packing_list WHERE tenant_id = %(tenant_id)s) "
        "RETURNING id",
    ),
]

# Module-level boto3 clients
_s3_client = None
_cognito_client = None


def _get_s3() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return _s3_client


def _get_cognito() -> Any:
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client(
            "cognito-idp",
            region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        )
    return _cognito_client


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_RETENTION_DAYS)

    tenants = _get_offboarded_tenants(cutoff)
    deleted = errors = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            _delete_tenant(tenant_id, tenant)
            deleted += 1
            logger.info("Tenant data deleted: %s", tenant_id)
        except Exception:
            logger.exception("Data cleanup failed for tenant %s", tenant_id)
            errors += 1

    logger.info(
        "Data cleanup job done: deleted=%d errors=%d",
        deleted,
        errors,
    )
    return {"deleted": deleted, "errors": errors}


# ---------------------------------------------------------------------------
# Tenant deletion
# ---------------------------------------------------------------------------


def _delete_tenant(tenant_id: str, tenant: dict[str, Any]) -> None:
    params = {"tenant_id": tenant_id}

    # 1. Delete tables that have no tenant_id column (subquery-based)
    for table, query in _SPECIAL_DELETES:
        try:
            execute_write_with_tenant(PLATFORM_TENANT_ID, query, params)  # noqa: S608
        except Exception:
            logger.exception("Failed special delete of %s for tenant %s", table, tenant_id)
            raise

    # 2. Delete all relational data in FK-safe order
    for table in _DELETE_ORDER:
        try:
            execute_write_with_tenant(
                PLATFORM_TENANT_ID,
                f"DELETE FROM {table} WHERE tenant_id = %(tenant_id)s RETURNING id",  # noqa: S608
                params,
            )
        except Exception:
            logger.exception("Failed to delete %s rows for tenant %s", table, tenant_id)
            raise

    # 3. Delete S3 prefix
    _delete_s3_prefix(tenant_id)

    # 4. Delete Cognito users
    _delete_cognito_users(tenant_id)

    # 5. Anonymise platform_audit_log rows that reference this tenant.
    #    Nulling target_tenant_id and details satisfies the FK constraint
    #    on tenant(id) while honouring GDPR Art. 17 (right to erasure).
    #    The existence of each admin action (action, actor_id, created_at)
    #    is preserved for internal governance purposes.
    try:
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            UPDATE platform_audit_log
            SET target_tenant_id = NULL,
                details          = NULL
            WHERE target_tenant_id = %(tenant_id)s
            RETURNING id
            """,
            params,
        )
    except Exception:
        logger.exception("Failed to anonymise platform_audit_log for tenant %s", tenant_id)
        raise

    # 6. Delete tenant record
    execute_write_with_tenant(
        PLATFORM_TENANT_ID,
        "DELETE FROM tenant WHERE id = %(tenant_id)s RETURNING id",
        params,
    )

    # 7. Log in audit_log (platform scope)
    log_audit(
        tenant_id=PLATFORM_TENANT_ID,
        entity_type="tenant",
        entity_id=tenant_id,
        action="DELETE",
        actor_id=_SYSTEM_ACTOR,
        actor_role=_SYSTEM_ROLE,
        before_state={
            "tenant_id": tenant_id,
            "offboarded_at": str(tenant.get("offboarded_at")),
        },
    )


def _delete_s3_prefix(tenant_id: str) -> None:
    bucket = os.environ.get("TENANT_DATA_BUCKET", "")
    if not bucket:
        logger.warning("TENANT_DATA_BUCKET not set — S3 cleanup skipped for %s", tenant_id)
        return

    prefix = f"{tenant_id}/"
    s3 = _get_s3()

    try:
        # Delete current object versions
        paginator = s3.get_paginator("list_objects_v2")
        total_deleted = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
                total_deleted += len(objects)

        # Also delete all non-current versions and delete markers (GDPR Art. 17).
        # S3 versioning means deleted objects remain in version history; this ensures
        # they are fully purged immediately rather than waiting for lifecycle rules.
        version_paginator = s3.get_paginator("list_object_versions")
        for page in version_paginator.paginate(Bucket=bucket, Prefix=prefix):
            to_delete = [
                {"Key": v["Key"], "VersionId": v["VersionId"]} for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            if to_delete:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
                total_deleted += len(to_delete)

        if total_deleted:
            logger.info("Deleted %d S3 objects/versions for tenant %s", total_deleted, tenant_id)
    except Exception:
        logger.exception("S3 cleanup failed for tenant %s", tenant_id)
        # Non-fatal — continue with Cognito + DB deletion


def _delete_cognito_users(tenant_id: str) -> None:
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    if not pool_id:
        logger.warning(
            "COGNITO_USER_POOL_ID not set — Cognito cleanup skipped for %s",
            tenant_id,
        )
        return

    cognito = _get_cognito()
    paginator = cognito.get_paginator("list_users")

    try:
        deleted_count = 0
        for page in paginator.paginate(
            UserPoolId=pool_id,
            Filter=f'custom:tenant_id = "{tenant_id}"',
        ):
            for user in page.get("Users", []):
                username = user["Username"]
                try:
                    cognito.admin_delete_user(UserPoolId=pool_id, Username=username)
                    deleted_count += 1
                except Exception:
                    logger.exception("Failed to delete a Cognito user for tenant %s", tenant_id)
        logger.info("Deleted %d Cognito users for tenant %s", deleted_count, tenant_id)
    except Exception:
        logger.exception("Cognito cleanup failed for tenant %s", tenant_id)
        # Non-fatal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_offboarded_tenants(cutoff: datetime) -> list[dict[str, Any]]:
    return execute_with_tenant(
        PLATFORM_TENANT_ID,
        """
        SELECT id, offboarded_at
        FROM tenant
        WHERE status = 'offboarded'
          AND offboarded_at IS NOT NULL
          AND offboarded_at < %s
        ORDER BY offboarded_at ASC
        """,
        (cutoff,),
    )
