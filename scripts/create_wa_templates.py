"""Create the ShipX WhatsApp message templates in Meta's WhatsApp Business Account.

Templates must exist and be approved by Meta before the matching event can send;
see `docs/project docs/whatsapp_templates.md`.

Each body's placeholder count is validated against `WA_TEMPLATE_PARAMS` in
`services/notification/service.py` before anything is submitted, so a template
can never be created with a shape the sender would violate at runtime
(Meta error `132000 number of parameters does not match`).

Usage:
    export META_WABA_ID=...            # WhatsApp Business Account ID
    export META_WHATSAPP_ACCESS_TOKEN=...   # needs whatsapp_business_management

    python3 scripts/create_wa_templates.py                 # dry run (default)
    python3 scripts/create_wa_templates.py --priority      # show the 6 live ones
    python3 scripts/create_wa_templates.py --priority --apply
    python3 scripts/create_wa_templates.py --apply         # all 11
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notification.service import WA_TEMPLATE_MAP, WA_TEMPLATE_PARAMS  # noqa: E402

GRAPH_VERSION = "v21.0"

# Templates whose events fire in the current product. The rest are defined so the
# set stays complete, but need not be submitted for review yet.
PRIORITY = frozenset(
    {
        "customer_invite",
        "customer_welcome",
        "container_arrived_warehouse",
        "payment_due_notification",
        "release_note_ready",
        "shipment_status_update",
    }
)

# Meta rejects templates whose samples look like placeholders, so these are
# realistic values rather than "test"/"xxx".
BODIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "customer_invite": (
        "Hello {{2}}, {{1}} has created an account for you to track your shipments.\n\n"
        "Tap here to create your account: {{3}}\n\n"
        "This link expires in 48 hours. If it expires, contact {{1}} for a new one.",
        ("Acme Shipping Ltd", "Ifesinachi Ugwuoke", "https://app.shipx.com/invite/3f9a2b7c1d"),
    ),
    "customer_welcome": (
        "Your {{1}} account has been created, {{2}}. " "Check your email to set your password and start tracking your shipments.",
        ("Acme Shipping Ltd", "Ifesinachi Ugwuoke"),
    ),
    "container_arrived_warehouse": (
        "Your container {{2}} has arrived at the {{1}} warehouse. "
        "We will contact you when your goods are ready for collection.",
        ("Acme Shipping Ltd", "STL409"),
    ),
    "shipment_status_update": (
        "Shipment update from {{1}}: your shipment {{2}} is now {{3}}. " "Reply to this message if you have any questions.",
        ("Acme Shipping Ltd", "SHX-2026-004821", "cleared at destination"),
    ),
    "release_note_ready": (
        "Your release note from {{1}} is ready. Reference {{2}} — " "please collect {{3}} carton(s) from our warehouse.",
        ("Acme Shipping Ltd", "RN-2026-01184", "12"),
    ),
    "payment_due_notification": (
        "Payment is due on your shipment with {{1}}. Container {{2}} has arrived. "
        "Amount due: {{3}} {{4}}. Collect your goods from {{5}} once payment is confirmed.",
        ("Acme Shipping Ltd", "STL409", "NGN", "485,000", "14 Balogun Street, Lagos Island, Lagos"),
    ),
    "damage_claim_update": (
        "Update from {{1}} on your damage claim {{2}}: the status is now {{3}}. " "Reply here if you have questions.",
        ("Acme Shipping Ltd", "CLM-2026-00317", "approved"),
    ),
    "cbm_dispute_update": (
        "Your CBM dispute {{2}} with {{1}} has been updated. Status: {{3}}. " "Reply here if you have questions.",
        ("Acme Shipping Ltd", "DSP-2026-00092", "resolved in your favour"),
    ),
    "packing_list_approved": (
        "Your packing list {{2}} has been approved by {{1}} and added to a container.",
        ("Acme Shipping Ltd", "PL-2026-02273"),
    ),
    "tenant_welcome": (
        "Welcome to {{1}}. Your account for {{2}} is active and ready to use.",
        ("ShipX", "Acme Shipping Ltd"),
    ),
    "tenant_suspended": (
        "Your {{1}} account has been suspended. Reason: {{2}}. " "Contact support to restore access.",
        ("ShipX", "unpaid subscription invoice"),
    ),
}


def expected_param_count(template_name: str) -> int:
    """Return the placeholder count the sender will produce for this template."""
    events = [e for e, t in WA_TEMPLATE_MAP.items() if t == template_name]
    if not events:
        raise KeyError(f"{template_name} is not in WA_TEMPLATE_MAP")
    # {{1}} is always company name; the rest come from WA_TEMPLATE_PARAMS.
    return 1 + len(WA_TEMPLATE_PARAMS.get(events[0], ()))


def validate() -> list[str]:
    """Check every body against the code's parameter contract. Returns problems."""
    problems = []
    for name, (body, samples) in BODIES.items():
        placeholders = {int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)}
        expected = expected_param_count(name)
        if placeholders != set(range(1, expected + 1)):
            problems.append(f"{name}: body uses {sorted(placeholders)} but WA_TEMPLATE_PARAMS " f"implies {{1}}..{{{expected}}}")
        if len(samples) != expected:
            problems.append(f"{name}: {len(samples)} sample values, expected {expected}")
        # Meta rejects "leading or trailing params" (subcode 2388299). Trailing
        # punctuation is not reliably counted as text, so require a real word.
        if body.lstrip().startswith("{{"):
            problems.append(f"{name}: body starts with a variable — Meta rejects this")
        if body.rstrip().rstrip(".!?:;,-— ").endswith("}}"):
            problems.append(f"{name}: body ends with a variable — Meta rejects this")
    missing = set(WA_TEMPLATE_MAP.values()) - set(BODIES)
    if missing:
        problems.append(f"no body defined for: {', '.join(sorted(missing))}")
    return problems


def _graph(path: str, token: str, payload: dict | None = None) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path}"
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if payload else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read() or b"{}").get("error", {})
        # error_user_title/msg carry Meta's actual reason; `message` is often
        # just "Invalid parameter" and says nothing useful on its own.
        parts = [f"Meta API error {exc.code}: {detail.get('message', 'unknown')}"]
        for key in ("error_user_title", "error_user_msg", "error_subcode"):
            if detail.get(key):
                parts.append(f"  {key}: {detail[key]}")
        parts.append(f"  code: {detail.get('code')}  path: {path}")
        raise SystemExit("\n".join(parts)) from exc


def _print_status(lang: str) -> int:
    """Print each ShipX template's Meta review status. Submits nothing."""
    token = os.environ.get("META_WHATSAPP_ACCESS_TOKEN", "")
    waba_id = os.environ.get("META_WABA_ID", "")
    if not token or not waba_id:
        print("Set META_WHATSAPP_ACCESS_TOKEN and META_WABA_ID.", file=sys.stderr)
        return 1
    query = urllib.parse.urlencode({"fields": "name,status,language,category,rejected_reason", "limit": "200"})
    remote = _graph(f"{waba_id}/message_templates?{query}", token).get("data", [])
    ours = sorted((t for t in remote if t["name"] in BODIES), key=lambda t: t["name"])
    if not ours:
        print("No ShipX templates found on this WhatsApp Business Account.")
        return 0
    for t in ours:
        reason = t.get("rejected_reason")
        note = f"  ← {reason}" if t["status"] == "REJECTED" and reason != "NONE" else ""
        mark = "✓" if t["status"] == "APPROVED" else "·"
        print(f"  {mark} {t['name']:<30} {t['language']:<6} {t.get('category', '?'):<9} " f"{t['status']}{note}")
    unsubmitted = sorted(set(BODIES) - {t["name"] for t in ours if t["language"] == lang})
    if unsubmitted:
        print(f"\nNot yet submitted in {lang}: {', '.join(unsubmitted)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually submit to Meta")
    parser.add_argument("--priority", action="store_true", help="only the 6 live templates")
    parser.add_argument("--status", action="store_true", help="show review status, submit nothing")
    parser.add_argument("--lang", default=os.environ.get("META_WHATSAPP_TEMPLATE_LANG", "en_US"))
    args = parser.parse_args()

    if args.status:
        return _print_status(args.lang)

    problems = validate()
    if problems:
        print("Parameter contract violations — fix before submitting:\n")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"✓ all {len(BODIES)} bodies match WA_TEMPLATE_PARAMS\n")

    wanted = sorted(PRIORITY if args.priority else BODIES.keys())

    if not args.apply:
        for name in wanted:
            body, samples = BODIES[name]
            print(f"── {name}  ({expected_param_count(name)} params)")
            print("   " + body.replace("\n", "\n   "))
            print(f"   samples: {list(samples)}\n")
        print(f"Dry run. {len(wanted)} template(s) would be submitted as UTILITY/{args.lang}.")
        print("Re-run with --apply to create them.")
        return 0

    token = os.environ.get("META_WHATSAPP_ACCESS_TOKEN", "")
    waba_id = os.environ.get("META_WABA_ID", "")
    if not token or not waba_id:
        print("Set META_WHATSAPP_ACCESS_TOKEN and META_WABA_ID.", file=sys.stderr)
        return 1

    query = urllib.parse.urlencode({"fields": "name,status,language", "limit": "200"})
    remote = _graph(f"{waba_id}/message_templates?{query}", token).get("data", [])
    # Keyed by (name, language): Meta versions templates per translation, so a
    # name approved under `en` is not reachable by a sender requesting `en_US`.
    existing = {(t["name"], t.get("language")): (t.get("status", "?"), t["id"]) for t in remote}
    other_langs = {t["name"] for t in remote if t["name"] in BODIES and t.get("language") != args.lang}
    for name in sorted(other_langs - {n for (n, lang) in existing if lang == args.lang}):
        langs = sorted({t["language"] for t in remote if t["name"] == name})
        print(f"  ! {name:<30} exists only as {', '.join(langs)} — adding {args.lang}")

    created = edited = skipped = 0
    for name in wanted:
        body, samples = BODIES[name]
        components = [{"type": "BODY", "text": body, "example": {"body_text": [list(samples)]}}]
        status, template_id = existing.get((name, args.lang), (None, None))

        if status is not None and status != "REJECTED":
            print(f"  · {name:<30} already exists ({status}) — skipped")
            skipped += 1
            continue

        if status == "REJECTED":
            # A (name, language) pair cannot be created twice, so a rejected
            # template must be edited in place to resubmit it for review.
            _graph(template_id, token, {"category": "UTILITY", "components": components})
            print(f"  ✎ {name:<30} edited and resubmitted  id={template_id}")
            edited += 1
            continue

        result = _graph(
            f"{waba_id}/message_templates",
            token,
            {
                "name": name,
                "language": args.lang,
                "category": "UTILITY",
                "components": components,
            },
        )
        print(f"  ✓ {name:<30} {result.get('status', 'submitted')}  id={result.get('id')}")
        created += 1

    print(f"\n{created} created, {edited} resubmitted, {skipped} already present.")
    print("Meta review is usually minutes. Check status with --apply again, or the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
