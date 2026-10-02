"""Tenant onboarding script — creates tenant record, Cognito user pool group, and initial admin user.

Usage:
    DATABASE_HOST=localhost DATABASE_NAME=logistics \\
    DATABASE_USER=postgres DATABASE_PASSWORD=secret \\
    AWS_REGION=eu-west-1 COGNITO_USER_POOL_ID=eu-west-1_XXXXXXXX \\
    python scripts/onboard_tenant.py \\
        --company-name "New Shipping Co" \\
        --email "admin@newshipping.com" \\
        --tier starter

Options:
    --company-name   Display name for the tenant (required)
    --email          Primary contact / initial admin email (required)
    --phone          Primary contact phone (optional)
    --tier           starter | business | enterprise (default: starter)
    --admin-name     Full name for the initial admin user (default: "Tenant Admin")
    --dry-run        Print actions without executing them
"""

import argparse
import contextlib
import json
import os
import re
import secrets
import string
import sys

import boto3
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _connect() -> psycopg2.extensions.connection:
    dsn = (
        f"host={os.environ['DATABASE_HOST']} "
        f"port={os.environ.get('DATABASE_PORT', '5432')} "
        f"dbname={os.environ['DATABASE_NAME']} "
        f"user={os.environ['DATABASE_USER']} "
        f"password={os.environ['DATABASE_PASSWORD']}"
    )
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def _one(cur, sql, params=None) -> dict:
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"Expected one row, got none.\nSQL: {sql}")
    return dict(rows[0])


# ---------------------------------------------------------------------------
# Onboarding steps
# ---------------------------------------------------------------------------


def _generate_temp_password(length: int = 16) -> str:
    """Generate a temporary password meeting Cognito complexity requirements."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Guarantee at least one of each required character class
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    password += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def step_create_tenant(cur, company_name: str, email: str, phone: str | None, tier: str) -> dict:
    print(f"[1/5] Creating tenant record for '{company_name}'...")
    # tenant.slug is NOT NULL + UNIQUE (migration 023) with no DB default —
    # mirror the same backfill logic used in scripts/seed.py.
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", company_name.lower())).strip("-")
    return _one(
        cur,
        """
        INSERT INTO tenant (
            company_name, primary_contact_email, primary_contact_phone,
            subscription_tier, status, slug
        ) VALUES (%s, %s, %s, %s, 'active', %s)
        RETURNING *
        """,
        (company_name, email, phone, tier, slug),
    )


def step_create_cognito_user(
    cognito_client,
    user_pool_id: str,
    tenant_id: str,
    email: str,
    admin_name: str,
    temp_password: str,
    dry_run: bool,
) -> str:
    """Create Cognito user and return the generated sub (username)."""
    print(f"[2/5] Creating Cognito user for {email}...")
    if dry_run:
        print("      [dry-run] skipping Cognito call")
        return "DRY-RUN-SUB"

    resp = cognito_client.admin_create_user(
        UserPoolId=user_pool_id,
        Username=email,
        TemporaryPassword=temp_password,
        MessageAction="SUPPRESS",  # We print it below; don't send Cognito's built-in email
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": admin_name},
            {"Name": "custom:tenant_id", "Value": tenant_id},
            {"Name": "custom:role", "Value": "tenant_admin"},
        ],
    )
    sub = next(attr["Value"] for attr in resp["User"]["Attributes"] if attr["Name"] == "sub")
    print(f"      Cognito sub: {sub}")

    # Roles are determined entirely by cognito:groups (shared/auth.py's
    # _parse_roles()), never by the custom:role attribute set above — without
    # this, the user falls back to UserRole.CUSTOMER on every login.
    group_name = f"{tenant_id}:tenant_admin"
    with contextlib.suppress(cognito_client.exceptions.GroupExistsException):
        cognito_client.create_group(GroupName=group_name, UserPoolId=user_pool_id)
    cognito_client.admin_add_user_to_group(
        UserPoolId=user_pool_id,
        Username=email,
        GroupName=group_name,
    )
    print(f"      Added to group: {group_name}")
    return sub


def step_create_tenant_user(cur, tenant_id: str, cognito_sub: str, email: str, admin_name: str) -> dict:
    print("[3/5] Creating tenant_user record...")
    # id = cognito_sub (not gen_random_uuid()) — every created_by/approved_by
    # FK points at tenant_user(id), and the JWT's `sub` claim becomes
    # ctx.user_id directly with no separate resolution step. See the same
    # note in services/tenant_management/repository.py's create_tenant_user().
    return _one(
        cur,
        """
        INSERT INTO tenant_user (id, tenant_id, cognito_sub, email, full_name, role, status)
        VALUES (%s, %s, %s, %s, %s, 'tenant_admin', 'active')
        RETURNING *
        """,
        (cognito_sub, tenant_id, cognito_sub, email, admin_name),
    )


def step_create_default_configs(cur, tenant_id: str) -> None:
    print("[4/5] Inserting default tenant_config records...")
    defaults = {
        "dollar_rate": {"rate": 1550.00, "currency_pair": "USD_NGN", "effective_from": ""},
        "cbm_rate_per_unit": {"rate_usd": 45.00},
        "storage_fee": {"enabled": True, "grace_period_days": 14, "daily_fee_per_carton_ngn": 500},
        "warehouse_address": {"address": "", "city": "Lagos", "state": "Lagos"},
        "refund_threshold_usd": {"staff_limit": 50, "requires_manager_above": 50},
        "dispute_escalation": {"enabled": True, "auto_escalate_days": 5},
        "reminder_days": {"storage_first_reminder": 7, "storage_final_reminder": 13},
    }
    for key, value in defaults.items():
        cur.execute(
            """
            INSERT INTO tenant_config (tenant_id, config_key, config_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, config_key) DO NOTHING
            """,
            (tenant_id, key, json.dumps(value)),
        )
    print(f"      {len(defaults)} config keys inserted.")


def step_print_summary(tenant: dict, tenant_user: dict, temp_password: str) -> None:
    print("\n[5/5] Onboarding complete.")
    print("=" * 60)
    print(f"  Tenant ID       : {tenant['id']}")
    print(f"  Company         : {tenant['company_name']}")
    print(f"  Tier            : {tenant['subscription_tier']}")
    print(f"  Admin email     : {tenant_user['email']}")
    print(f"  Admin user ID   : {tenant_user['id']}")
    print(f"  Temp password   : {temp_password}")
    print("=" * 60)
    print("  The admin user must change their password on first login.")
    print("  Update 'dollar_rate' and 'warehouse_address' configs before go-live.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Onboard a new tenant into the logistics platform.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--company-name", required=True, help="Tenant company display name")
    parser.add_argument("--email", required=True, help="Primary contact / initial admin email")
    parser.add_argument("--phone", default=None, help="Primary contact phone number")
    parser.add_argument(
        "--tier",
        choices=["starter", "business", "enterprise"],
        default="starter",
        help="Subscription tier (default: starter)",
    )
    parser.add_argument("--admin-name", default="Tenant Admin", help="Full name for the initial admin user")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to DB or Cognito")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
    aws_region = os.environ.get("AWS_REGION", "eu-west-1")

    if not user_pool_id and not args.dry_run:
        print("ERROR: COGNITO_USER_POOL_ID environment variable is required.", file=sys.stderr)
        sys.exit(1)

    temp_password = _generate_temp_password()

    if args.dry_run:
        print("[dry-run mode] No writes will be performed.\n")
        print(f"  Would create tenant: '{args.company_name}' ({args.tier})")
        print(f"  Would create Cognito user: {args.email}")
        print(f"  Would create tenant_user record for: {args.admin_name}")
        print("  Would insert 7 default tenant_config rows")
        print(f"  Generated temp password: {temp_password}")
        return

    cognito = boto3.client("cognito-idp", region_name=aws_region)
    conn = _connect()

    try:
        with conn.cursor() as cur:
            tenant = step_create_tenant(cur, args.company_name, args.email, args.phone, args.tier)
            tenant_id = str(tenant["id"])

            cognito_sub = step_create_cognito_user(
                cognito,
                user_pool_id,
                tenant_id,
                args.email,
                args.admin_name,
                temp_password,
                dry_run=False,
            )

            tenant_user = step_create_tenant_user(cur, tenant_id, cognito_sub, args.email, args.admin_name)

            step_create_default_configs(cur, tenant_id)

        conn.commit()
        step_print_summary(tenant, tenant_user, temp_password)

    except Exception as exc:
        conn.rollback()
        print(f"\nOnboarding FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
