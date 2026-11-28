"""Tenant Data Cleanup — runs daily at 02:00 UTC.

For each tenant offboarded more than 90 days ago:
  0. Refuse (and log) if no offboarding export has completed since it was offboarded (audit BE-10): its data must
     be handed over before it is destroyed. A platform admin sees the export's state on the tenant page.
  1. Purge the tenant's object-storage prefix ({tenant_id}/), the export archive included. A failure here stops the
     tenant's deletion until tomorrow, so files are never orphaned behind a deleted tenant.
  2. In one transaction: delete every table in ``shared.tenant_data.TENANT_TABLES`` in reverse (children first),
     delete the tenant's impersonation sessions, anonymise the platform audit rows about it, delete the tenant.
  3. Delete its Cognito users (best effort).
  4. Log in audit_log (platform scope).

The table list used to be kept here by hand and had fallen about twenty tables behind the schema, so the final
``DELETE FROM tenant`` (or a parent table's delete) failed on a foreign key for any tenant that had used payment
claims, warehouses, staff notifications and more. The shared inventory is checked against the migrations by
``tests/unit/test_tenant_data.py``.
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

from shared import tenant_export
from shared.audit import log_audit
from shared.db import execute_with_tenant, execute_write_with_tenant, execute_write_with_tenant_many, tenant_transaction
from shared.job_runs import tracked_job
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing, record_failure
from shared.providers import get_storage_provider
from shared.tenant_context import PLATFORM_TENANT_ID
from shared.tenant_data import TENANT_TABLES

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 90
_SYSTEM_ACTOR = "system"
_SYSTEM_ROLE = "scheduler"

# Module-level boto3 clients (object storage is accessed via get_storage_provider)
_cognito_client = None


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


@tracked_job("data_cleanup")
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_RETENTION_DAYS)

    tenants = _get_offboarded_tenants(cutoff)
    deleted = errors = refused = 0

    for tenant in tenants:
        tenant_id = str(tenant["id"])
        bind_log_context(tenant_id=tenant_id)
        try:
            if not tenant_export.has_completed_export(tenant_id, since=tenant["offboarded_at"]):
                logger.warning("Refusing to delete tenant %s: no offboarding export has completed", tenant_id)
                record_failure("tenant_deletion_refused")  # counted, not alarmed: it repeats daily until handled
                refused += 1
                continue
            _delete_tenant(tenant_id, tenant)
            deleted += 1
            logger.info("Tenant data deleted: %s", tenant_id)
        except Exception:
            logger.exception("Data cleanup failed for tenant %s", tenant_id)
            record_failure("scheduled_job_step")
            errors += 1

    logger.info("Data cleanup job done: deleted=%d errors=%d refused=%d", deleted, errors, refused)
    return {"deleted": deleted, "errors": errors, "refused": refused}


# ---------------------------------------------------------------------------
# Tenant deletion
# ---------------------------------------------------------------------------


def _delete_tenant(tenant_id: str, tenant: dict[str, Any]) -> None:
    params = {"tenant_id": tenant_id}

    # 1. Files first: if this fails, nothing else is deleted and tomorrow's run tries again.
    _delete_s3_prefix(tenant_id)

    # 2. Every row, or none.
    with tenant_transaction(PLATFORM_TENANT_ID):
        for entry in reversed(TENANT_TABLES):
            execute_write_with_tenant(PLATFORM_TENANT_ID, entry.delete_sql(), params)
        # The platform's records about the tenant: support sessions point at it with a NOT NULL key; the audit rows
        # keep that an action happened (action, actor, time) and lose which tenant it was about (GDPR Art. 17).
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            "DELETE FROM impersonation_session WHERE target_tenant_id = %(tenant_id)s RETURNING 1",
            params,
        )
        # Through the SECURITY DEFINER function from migration 075: the app role may neither update nor delete
        # platform audit rows, so a plain UPDATE here is refused.
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            "SELECT anonymise_platform_audit_for_tenant(%(tenant_id)s) AS anonymised",
            params,
        )
        # Two-person approvals about the tenant (migration 076) keep who asked, who decided and when, and lose what
        # they were about. ``execute_write_with_tenant_many``: a tenant may have none.
        execute_write_with_tenant_many(
            PLATFORM_TENANT_ID,
            """
            UPDATE platform_approval
            SET payload = '{}'::jsonb, secret_payload = NULL, reason = NULL, target_tenant_id = NULL,
                target_label = 'deleted tenant ' || id::text,
                status = CASE WHEN status IN ('pending', 'scheduled') THEN 'cancelled' ELSE status END
            WHERE target_tenant_id = %(tenant_id)s
            RETURNING id
            """,
            params,
        )
        if (
            execute_write_with_tenant(PLATFORM_TENANT_ID, "DELETE FROM tenant WHERE id = %(tenant_id)s RETURNING id", params)
            is None
        ):
            raise RuntimeError("the tenant row was already gone")

    # 3. Cognito users
    _delete_cognito_users(tenant_id)

    # 4. Log in audit_log (platform scope)
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
    # Tenant files live in the assets bucket (`get_storage_provider()`'s default). TENANT_DATA_BUCKET was required here
    # but set by no deployment, so the purge was always skipped and a deleted tenant's files stayed. It is now only an
    # override for a deployment that keeps tenant data in a separate bucket.
    bucket = os.environ.get("TENANT_DATA_BUCKET") or None

    # delete_prefix purges current objects plus non-current versions and
    # delete-markers (GDPR Art. 17 immediate erasure, not lifecycle-deferred).
    # A failure propagates: the caller deletes nothing else for this tenant today.
    total_deleted = get_storage_provider(bucket).delete_prefix(f"{tenant_id}/")  # bucket None = the assets bucket
    if total_deleted:
        logger.info("Deleted %d storage objects/versions for tenant %s", total_deleted, tenant_id)


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
