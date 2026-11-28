#!/usr/bin/env python3
"""List or seed the platform admin directory (``platform_user``, migration 076).

The console invites admins once an owner exists. This script is for the step before that: seeding the first owner
ahead of the Phase 1 deploy, so the directory does not fall back to "the first platform admin to sign in becomes the
owner" (``shared/platform_directory.py``). A seeded row is ``invited`` with no subject; the person's first signed-in
request binds it by email. Their identity-provider account must already exist and be in the ``platform_admin`` group.

Usage::

    python3 scripts/platform_admins.py list
    python3 scripts/platform_admins.py add --email owner@example.com --name "Ada N" --role owner

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ShipX platform admin directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List the directory")
    add = sub.add_parser("add", help="Seed an invited platform admin")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True, choices=ROLES)
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            if args.command == "list":
                for row in list_admins(cur):
                    print(f"{row['role']:<8} {row['status']:<9} {row['email']}  ({row['name']})")
                return 0
            row = add_admin(cur, args.email, args.name, args.role)
        conn.commit()
        print(f"Added {args.email} as {args.role} ({row['status']}); their first sign-in activates the row.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
