#!/usr/bin/env python3
"""Bulk-migrate existing ShipX users from Cognito into Microsoft Entra (ADR-004).

Cognito cannot export password hashes, so users are re-provisioned in Entra with
a forced password reset on first sign-in (the invite drives the password-set
email, per the tenant's invitation/SSPR config). Each user's full role set is
reconciled into Entra security groups named `{tenant_id}:{role}`, matching the
token the authorizer expects.

This reads the source of truth — the `tenant_user` table — and writes via the
cloud-neutral IdentityProvider port, so it goes through `EntraIdentityProvider`
only when CLOUD_PROVIDER=azure (guarded below). It is idempotent: a user who
already exists in Entra is skipped for creation but still has their groups
reconciled, so re-running converges.

Usage:
    CLOUD_PROVIDER=azure \\
    ENTRA_USER_DOMAIN=yourtenant.onmicrosoft.com \\
    python scripts/migrate_users_to_entra.py [--dry-run] [--tenant <tenant_id>]

Auth to Microsoft Graph uses DefaultAzureCredential (az login / a service
principal / managed identity). The deploy identity needs the Graph application
permissions User.ReadWrite.All + Group.ReadWrite.All (documented in the Phase-4
setup checklist).
"""

import argparse
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db import execute_with_tenant  # noqa: E402
from shared.exceptions import DuplicateResourceError  # noqa: E402
from shared.providers import get_identity_provider  # noqa: E402
from shared.tenant_context import PLATFORM_TENANT_ID  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("migrate_users_to_entra")


def _fetch_users(tenant_filter: str | None) -> list[dict]:
    """Return active tenant_user rows (+ full role set) across all tenants.

    Uses PLATFORM scope to read across tenants (bypasses RLS, as the auth
    tenant-status check does). Platform admins (tenant_id='PLATFORM') are
    included so their `platform_admin` group is provisioned too.
    """
    query = """
        SELECT
            tu.tenant_id,
            tu.email,
            tu.full_name,
            tu.role,
            COALESCE(
                (SELECT array_agg(tur.role ORDER BY tur.role)
                 FROM tenant_user_role tur
                 WHERE tur.tenant_user_id = tu.id AND tur.tenant_id = tu.tenant_id),
                ARRAY[tu.role]
            ) AS roles
        FROM tenant_user tu
        WHERE tu.status = 'active'
    """
    params: tuple = ()
    if tenant_filter:
        query += " AND tu.tenant_id = %s"
        params = (tenant_filter,)
    return execute_with_tenant(PLATFORM_TENANT_ID, query, params)


def _desired_groups(tenant_id: str, roles: list[str]) -> set[str]:
    """Platform admins belong to the prefixless `platform_admin` group; everyone
    else to `{tenant_id}:{role}` for each role held."""
    if tenant_id == PLATFORM_TENANT_ID:
        return {"platform_admin"}
    return set(roles)


def migrate(dry_run: bool, tenant_filter: str | None) -> int:
    users = _fetch_users(tenant_filter)
    logger.info("Found %d active user(s) to migrate%s", len(users), f" for tenant {tenant_filter}" if tenant_filter else "")

    idp = get_identity_provider()
    created = skipped = failed = 0

    for row in users:
        email = row["email"]
        tenant_id = row["tenant_id"]
        full_name = row["full_name"] or email
        primary_role = row["role"]
        roles = list(row["roles"] or [primary_role])

        if dry_run:
            logger.info("[dry-run] would provision %s (tenant=%s, roles=%s)", email, tenant_id, roles)
            continue

        try:
            idp.create_user(email=email, full_name=full_name, tenant_id=tenant_id, role=primary_role)
            created += 1
            logger.info("Provisioned %s (tenant=%s)", email, tenant_id)
        except DuplicateResourceError:
            skipped += 1
            logger.info("Already in Entra, reconciling groups only: %s", email)
        except Exception:
            failed += 1
            logger.exception("Failed to provision %s", email)
            continue

        # Reconcile the full role set regardless (handles multi-role + re-runs).
        if tenant_id == PLATFORM_TENANT_ID:
            idp.create_group_if_not_exists("platform_admin")
            idp.add_user_to_group(email, "platform_admin")
        else:
            try:
                idp.sync_user_groups(email, tenant_id, set(roles))
            except Exception:
                failed += 1
                logger.exception("Provisioned but failed to sync groups for %s", email)

    logger.info("Done. created=%d skipped=%d failed=%d (dry_run=%s)", created, skipped, failed, dry_run)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate ShipX users from Cognito to Entra")
    parser.add_argument("--dry-run", action="store_true", help="List what would be provisioned; make no changes")
    parser.add_argument("--tenant", help="Only migrate users of this tenant id")
    args = parser.parse_args(argv)

    if os.environ.get("CLOUD_PROVIDER", "aws").lower() != "azure":
        logger.error("Refusing to run: set CLOUD_PROVIDER=azure (this migrates INTO Entra).")
        return 2

    return migrate(dry_run=args.dry_run, tenant_filter=args.tenant)


if __name__ == "__main__":
    sys.exit(main())
