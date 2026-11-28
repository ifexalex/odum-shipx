#!/usr/bin/env python3
"""List or seed the platform admin directory (``platform_user``, migration 076).

The console invites admins once an owner exists. This script is for the step before that: seeding the first owner
ahead of the Phase 1 deploy, so the directory does not fall back to "the first platform admin to sign in becomes the
owner" (``shared/platform_directory.py``). A seeded row is ``invited`` with no subject; the person's first signed-in
request binds it by email. Their identity-provider account must already exist and be in the ``platform_admin`` group.

It also moves platform admins to the platform Cognito pool, which requires MFA (platform audit Phase 1b): each
active or invited admin gets an account there (Cognito emails a temporary password; the first sign-in sets up an
authenticator app), and their directory row is rebound to the new subject, the old one kept in ``previous_subjects`` so
audit rows keep their name. ``--disable-old`` then disables their tenant-pool account. Run it before turning on
``PLATFORM_MFA_REQUIRED``. Needs ``AWS_REGION`` and ``COGNITO_PLATFORM_USER_POOL_ID`` (and ``COGNITO_USER_POOL_ID``
for ``--disable-old``).

Usage::

    python3 scripts/platform_admins.py list
    python3 scripts/platform_admins.py add --email owner@example.com --name "Ada N" --role owner
    python3 scripts/platform_admins.py move-to-platform-pool --dry-run
    python3 scripts/platform_admins.py move-to-platform-pool --disable-old

Connects with the owner credential (``shared.db_credentials.admin_db_params``): the table is platform-only under RLS.
"""

import argparse
import os
import sys
from typing import Any

import psycopg2
import psycopg2.extras

from shared.db_credentials import admin_db_params

ROLES = ("owner", "admin", "support", "finance")


def _connect() -> Any:
    return psycopg2.connect(
        **admin_db_params(),
        sslmode=os.environ.get("DATABASE_SSLMODE", "prefer"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def list_admins(cur: Any) -> list[dict[str, Any]]:
    """Every directory row, owners first."""
    cur.execute("SELECT email, name, role, status, last_seen_at FROM platform_user ORDER BY role, email")
    return list(cur.fetchall())


def add_admin(cur: Any, email: str, name: str, role: str) -> dict[str, Any]:
    """Insert an ``invited`` row; refuse an email that is already in the directory."""
    if role not in ROLES:
        raise SystemExit(f"role must be one of {', '.join(ROLES)}")
    cur.execute("SELECT 1 FROM platform_user WHERE lower(email) = lower(%s)", (email,))
    if cur.fetchone():
        raise SystemExit(f"{email} is already in the platform directory")
    cur.execute(
        "INSERT INTO platform_user (email, name, role, status) VALUES (%s, %s, %s, 'invited') RETURNING id, status",
        (email.strip().lower(), name.strip(), role),
    )
    row: dict[str, Any] = cur.fetchone()
    return row


def _platform_pool_sub(client: Any, pool_id: str, email: str, name: str) -> tuple[str, bool]:
    """Return ``(sub, created)`` for ``email`` in the platform pool, creating the account when there is none."""
    from botocore.exceptions import ClientError

    try:
        user = client.admin_get_user(UserPoolId=pool_id, Username=email)
        return next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub"), False
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "UserNotFoundException":
            raise
    resp = client.admin_create_user(
        UserPoolId=pool_id,
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": name},
        ],
        DesiredDeliveryMediums=["EMAIL"],
    )
    return next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub"), True


def move_to_platform_pool(cur: Any, *, dry_run: bool, disable_old: bool) -> list[str]:
    """Give each active or invited admin a platform-pool account and rebind their row; return one line per admin."""
    import boto3

    pool_id = os.environ["COGNITO_PLATFORM_USER_POOL_ID"]
    client = boto3.client("cognito-idp", region_name=os.environ["AWS_REGION"])
    cur.execute("SELECT id, email, name, subject FROM platform_user WHERE status IN ('active', 'invited') ORDER BY email")
    report: list[str] = []
    for row in cur.fetchall():
        if dry_run:
            report.append(f"would move {row['email']}")
            continue
        sub, created = _platform_pool_sub(client, pool_id, row["email"], row["name"])
        if sub == row["subject"]:
            report.append(f"already in the platform pool: {row['email']}")
            continue
        cur.execute(
            """
            UPDATE platform_user
            SET previous_subjects = CASE WHEN subject IS NULL THEN previous_subjects
                                         ELSE array_append(previous_subjects, subject) END,
                subject = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (sub, row["id"]),
        )
        if disable_old and row["subject"]:
            try:
                client.admin_disable_user(UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=row["email"])
            except Exception as exc:  # noqa: BLE001 - report and carry on; the directory row is already rebound
                report.append(f"could not disable the tenant-pool account of {row['email']}: {type(exc).__name__}")
        report.append(f"moved {row['email']}{' (account created, temporary password emailed)' if created else ''}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShipX platform admin directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the directory")
    add = sub.add_parser("add", help="Seed an invited platform admin")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True, choices=ROLES)
    move = sub.add_parser("move-to-platform-pool", help="Give admins MFA-required accounts in the platform pool")
    move.add_argument("--dry-run", action="store_true")
    move.add_argument("--disable-old", action="store_true", help="Disable each admin's tenant-pool account")
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            if args.command == "list":
                for row in list_admins(cur):
                    print(f"{row['role']:<8} {row['status']:<9} {row['email']}  ({row['name']})")
                return 0
            if args.command == "move-to-platform-pool":
                for line in move_to_platform_pool(cur, dry_run=args.dry_run, disable_old=args.disable_old):
                    print(line)
                conn.commit()
                return 0
            row = add_admin(cur, args.email, args.name, args.role)
        conn.commit()
        print(f"Added {args.email} as {args.role} ({row['status']}); their first sign-in activates the row.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
