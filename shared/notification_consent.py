"""Which customer messages a customer's notification preferences govern (audit SEC-01).

`customer.notification_consent` is a list of the channels a customer has agreed to be messaged on (`sms`,
`whatsapp`, `email`). It is collected at sign-up and editable on the Account page. Before this nothing on
the send path read it.

The policy has three parts, and the owner decided each (2026-11-15):

1. **Recorded choices bind; no recorded choice means no restriction.** A customer who has set preferences
   (`consent_given_at` is set: self-registered, or saved on the Account page, or recorded by staff) is held to
   them strictly, an empty list meaning "none". A customer with no recorded choice (created by staff or by a
   manifest import, never asked) is messaged on every channel the tenant has enabled, as before. Treating an
   empty list as "no" would silence every imported customer, who never had a chance to say yes.
2. **Operational messages bypass an opt-out.** Anything about the customer's own shipments, invoices, claims or
   account is sent regardless; only announcements and marketing honour an opt-out.
3. **Account links are always sent**: activation, invite, "you already have an account". The person asked for
   them, they carry a single-use link, and withholding them locks someone out of their own account.

Today every event type is operational or account, so in practice no message is held back by an opt-out:
announcements are in-app only (staff_notification rows, no SMS, WhatsApp or email) and there is no marketing
send. The machinery exists so that this stays true by *default* rather than by accident:

**An event type that is not listed here is consent-bound.** Adding a new kind of message and forgetting to
classify it therefore errs on the side of the customer's choice, and `tests/unit/test_notification_consent.py`
fails until the author decides which set it belongs in. To bind an existing event type to opt-outs instead,
move it to CONSENT_BOUND_EVENTS: nothing else changes.
"""

from collections.abc import Iterable
from typing import Any

# Single-use links the person asked for. Sent whatever their preferences.
ACCOUNT_EVENTS: frozenset[str] = frozenset(
    {
        "account_activation",
        "customer_invite",
        "registration_existing_account",
        # The code that lets the customer's own collector take their goods; without it the pickup cannot happen.
        "pickup_code_issued",
    }
)

# About the customer's own shipments, money, claims or account. Sent whatever their preferences.
OPERATIONAL_EVENTS: frozenset[str] = frozenset(
    {
        "shipment_update",
        "container_arrived",
        "payment_due",
        "payment_claim_confirmed",
        "payment_claim_rejected",
        "release_note_generated",
        "packing_list_approved",
        "damage_claim_update",
        "cbm_dispute_update",
        "customer_registered",
        "storage_first_reminder",
        "storage_final_reminder",
        "release_note_expired",
        # Sent to the tenant's own people, not to a customer: there is no customer preference to honour.
        "tenant_onboarded",
        "tenant_suspended",
    }
)

# Held back for a customer whose recorded preferences exclude the channel. Empty today, by the owner's decision;
# move an event type here to make it honour opt-outs.
CONSENT_BOUND_EVENTS: frozenset[str] = frozenset()


def is_consent_bound(event_type: str) -> bool:
    """True if a customer's recorded preferences decide whether this event is sent.

    Anything not explicitly classified as account or operational is bound, so an unclassified event type
    is protected until someone decides otherwise.
    """
    if event_type in CONSENT_BOUND_EVENTS:
        return True
    return event_type not in ACCOUNT_EVENTS and event_type not in OPERATIONAL_EVENTS


def permits(consent: Iterable[str] | None, preferences_recorded_at: Any, channel: str) -> bool:
    """May a customer with these preferences be messaged on `channel`?

    Args:
        consent: The customer's `notification_consent` list.
        preferences_recorded_at: Their `consent_given_at`. None means they never made a choice.
        channel: `sms`, `whatsapp` or `email`.
    """
    if preferences_recorded_at is None:
        return True
    return channel in (consent or [])
