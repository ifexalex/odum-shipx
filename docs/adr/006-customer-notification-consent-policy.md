# ADR-006: Customer notification consent — what an opt-out governs

**Status:** Accepted (2026-11-15, owner decision on audit finding SEC-01).
**Related:** `shared/notification_consent.py`, `shared/notifications.py`,
`15_api_notifications.md`, migration 064.

## Context

`customer.notification_consent` (a list of `sms` / `whatsapp` / `email`) is collected at sign-up and
editable on the customer Account page, but nothing on the send path read it. A customer who opted out of SMS
still received SMS.

Enforcing it literally has a consequence the audit had not seen: **every customer in the development
database (23 of 23) has an empty list and no consent timestamp.** They were created by staff or imported from a
forwarder's manifest, never asked. "No consent means no messages" would have silenced all of them, including
payment-due and release-note notices.

## Decision

1. **Recorded choices bind; no recorded choice means no restriction.** "Recorded" is `consent_given_at` being
   set. It is stamped when preferences are saved (`update_customer`, whether by the customer on the Account page
   or by staff) and at self-registration. A recorded empty list means "none". A customer with no recorded
   choice is messaged on every channel the tenant has enabled, as before.
2. **Operational messages bypass an opt-out.** Anything about the customer's own shipments, invoices, claims or
   account is sent regardless of preferences. Only announcements and marketing honour an opt-out. (The
   alternatives offered were honouring opt-outs everywhere, and letting only payment-due and release-note
   bypass.)
3. **Account links are always sent**: activation, invite, "you already have an account".
4. **An event type nobody has classified is consent-bound.** `ACCOUNT_EVENTS`, `OPERATIONAL_EVENTS` and
   `CONSENT_BOUND_EVENTS` are explicit sets; anything in none of them is treated as bound.
   `tests/unit/test_notification_consent.py` fails until a new event type is classified.

Enforcement is at enqueue time, for both `enqueue_notifications` and `enqueue_notification`, and in the
WhatsApp-to-SMS fallback. It **fails closed**: a bound message with no `customer_id`, an unknown customer, or a
failed lookup is not sent. A held-back message is recorded in `notification_log` with status `suppressed` and
the reason in `error_detail`. A customer who agreed to SMS but not WhatsApp is texted instead of going silent.

## Consequences

* **Today, no message that exists is held back by an opt-out.** Every event type is operational or account, and
  announcements are in-app only (`staff_notification` rows: no SMS, WhatsApp or email) and there is no marketing
  send. The policy takes effect the day an optional message type is added, and a test makes that deliberate.
* The customer-facing copy had to change, because it promised more than this delivers: the Account page said
  the SMS toggle controlled "payment due, status changes, claims". It now says the toggles cover optional
  messages and that shipment, invoice, claim and account messages are always sent.
* Binding an existing event type to opt-outs is one line (move it to `CONSENT_BOUND_EVENTS`); nothing else
  changes.
* A customer's own save of an unchanged channel list would record a choice they never made, so the Account page
  sends only the fields that changed.

## Alternatives considered

* **Strict opt-in** (no recorded consent, no messages): correct in principle, but silences every imported
  customer until staff record consent for each, which needs a bulk action that does not exist.
* **Honour opt-outs on every customer message:** the strongest protection, and the audit's default. Declined by
  the owner for operational messages.
