"""Mint a customer-creation invite and print its raw token, for e2e test setup.

The real API never returns a raw invite token (`shared/invites.py`) — it's
stored only as a SHA-256 hash, and staff-facing responses report just the
masked delivery contact. That's correct security behavior, but it means the
one thing an e2e test of InviteClaimScreen (frontend/src/pages/auth/
InviteClaimScreen.tsx) needs — a real, unconsumed token to visit /invite/:token
with — has nowhere else to come from. This script talks to the DB directly to
produce one, exactly the way issue_customer_invite() does internally, minus
the masking.

Test-only. Never expose this as an HTTP endpoint.

Usage:
    python3 scripts/mint_test_invite.py [--tenant-id UUID] [--name NAME] [--phone PHONE]

Prints one line: "<token> <customer_id>"
"""

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.tenant_management.repository import create_customer  # noqa: E402
from shared.invites import create_invite, delete_unconsumed_invites, hash_token, mint_token  # noqa: E402

DEFAULT_TENANT_ID = "10000000-0000-0000-0000-000000000001"  # Acme Shipping Ltd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--name", default="E2E Test Customer")
    # A fresh phone per run avoids colliding with a real customer's invite —
    # this is throwaway test data, never a real contact.
    parser.add_argument("--phone", default=f"+234800{uuid.uuid4().int % 10_000_000:07d}")
    args = parser.parse_args()

    customer = create_customer(
        args.tenant_id,
        {"name": args.name, "phone": args.phone, "notification_consent": []},
    )
    if not customer:
        print("Failed to create customer", file=sys.stderr)
        return 1
    customer_id = str(customer["id"])

    delete_unconsumed_invites(args.tenant_id, customer_id)
    token = mint_token()
    invite = create_invite(
        args.tenant_id,
        customer_id,
        hash_token(token),
        sent_channel=None,
        sent_to_masked=None,
        created_by=None,
    )
    if not invite:
        print("Failed to create invite", file=sys.stderr)
        return 1

    print(f"{token} {customer_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
