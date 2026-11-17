# Task 15 — API Service: Notification Service (SMS, WhatsApp, Email)

## Objective

Implement the 3 Notification Lambda functions (SMS, WhatsApp, Email) that consume from SQS queues. Each function fetches tenant branding, formats messages using templates, and sends via the appropriate channel.

## Depends On

- Task 06 (shared layer), Task 04d (SQS queues)

## Architecture

```
EventBridge → SQS (sms/whatsapp/email queues) → Lambda consumers
```

These Lambdas run **outside the VPC** (no database access needed — message data comes in the SQS event). If tenant branding is needed, it's included in the event payload by the publishing service.

## Files

```
services/notification/
├── handler.py           # 4 handlers: sms_handler, whatsapp_handler, email_handler, http_handler; webhook_handler
├── repository.py        # notification_log DB queries (insert/mark_sent/mark_failed/update_delivery_status/list)
├── service.py           # Channel-specific sending logic + notification log functions (log_queued/log_sent/log_failed/retry_notification/get_log/list_logs)
├── tenant_branding.py   # Extract tenant branding from event payload
└── models.py
```

## SQS Event Format

Each SQS message body contains:
```json
{
  "tenant_id": "uuid",
  "event_type": "container_arrived",
  "channel": "sms",
  "recipient": {
    "phone": "+2348012345678",
    "email": "customer@example.com",
    "whatsapp": "+2348012345678",
    "name": "John Doe"
  },
  "tenant_branding": {
    "company_name": "Acme Shipping",
    "primary_color": "#1A5276"
  },
  "template_data": {
    "tracking_code": "ACME-TRK-20260215-0001",
    "status": "arrived_nigeria",
    "container_number": "MSKU1234567"
  },
  "template_override": {
    "sms": "Custom SMS template text (optional — only present when tenant has a custom template)",
    "whatsapp": "custom_wa_template_name",
    "email": {
      "subject": "Custom subject",
      "body": "<html>Custom HTML body</html>"
    }
  }
}
```

`template_override` is populated by `shared.notifications.enqueue_notifications` when the tenant has a custom row in `notification_template`. If absent, each channel handler falls back to the hardcoded defaults in `services/notification/service.py`.

## SMS Handler (Africa's Talking)

- Use Africa's Talking API (or Twilio for China numbers)
- Template messages:
  - `shipment_update`: "{company_name}: Your shipment {tracking_code} is now {status}."
  - `payment_due`: "{company_name}: Container {container} arrived. Amount: {currency} {amount}. Pickup: {address}"
  - `release_ready`: "{company_name}: Release note ready. Ref: {ref}. Collect {carton_count} cartons."
- Retry: SQS handles 3 retries, then DLQ
- Cost tracking: publish `UsageRecorded` event (metric_type = 'sms_sent')

## WhatsApp Handler (Meta Cloud API)

- POST to `https://graph.facebook.com/v17.0/{phone-id}/messages`
- Use pre-approved template messages with parameters
- v1: shared platform WABA with `{{company_name}}` variable
- Include tenant company name in template parameters
- Cost tracking: publish `UsageRecorded` event (metric_type = 'whatsapp_sent')

## Email Handler (Amazon SES)

- Sends via the cloud-neutral `EmailProvider` port (`shared/providers/`, AWS adapter = SES `send_email`; 2026-10-05 — was a direct `boto3` SES client). Queue enqueuing likewise goes through `QueueProvider` (AWS = SQS). See `02_shared_utilities.md` → "shared/providers/".
- HTML email templates with tenant branding: company name (`display_name`, else the tenant row's `company_name`), `primary_color`, `tagline`, `support_email`, `support_whatsapp`, `document_footer` — all from the canonical `branding_config` shape, read through `services/notification/tenant_branding.py`
- A **lead paragraph per event** (`_EMAIL_BODIES` / `_EMAIL_BODIES_ZH`), then the CTA button, then the detail rows. See the 2026-11-13 notes below for what this replaced
- Events that trigger email: packing_list_approved, release_note_generated, damage_claim_filed, tenant_onboarded
- Subject is prefixed with the company name (`"{company} — {subject}"`), matching the `{company_name}:` convention of the SMS templates; a tenant subject override is used verbatim
- From address: `SES_FROM_ADDRESS`. The code default `notifications@logistics.example.com` is a placeholder that SES and ACS both reject as unverified — `send_email` **refuses to send** from it in production rather than letting it fail as a provider error
- Cost tracking: publish `UsageRecorded` event (metric_type = 'emails_sent')

## Implementation notes / ground-truth gaps found (2026-11-13 — invite links were broken and no notification was tenant-branded)

Reported as: *"when i send an invite it should be sent via email, i realized that
the link is broken and also the email template does not look well customized to
tenant"*. Investigating found five separate faults, three of which made the
product silently lie about what had been delivered.

### 1. Every invite link was a relative path

`issue_customer_invite` built `f"{os.environ.get('CUSTOMER_PORTAL_BASE_URL', '')}/invite/{token}"`,
and that variable was set in **no** environment — not AWS Terraform, not Azure
Terraform, not `.env.local`; only `.env.example` mentioned it. So every invite
went out as `/invite/<token>`, which no mail or messaging client can open.
`APP_BASE_URL` (activation links) had the mirror-image gap: wired on Azure,
absent on AWS, where its `ENTRA_REDIRECT_URI` fallback is also unset.

Resolution lives in one place now, `shared/app_urls.py`: `CUSTOMER_PORTAL_BASE_URL`
→ `APP_BASE_URL` → the origin of `ENTRA_REDIRECT_URI`. It **raises
`MissingBaseUrlError` rather than returning a relative URL**, and a value that
is set but relative is an error naming the offending variable rather than a
silent fall-through to another host. Callers catch it, log at ERROR, and send
nothing — a dead link is worse than no message, because it consumes the
single-use token and tells staff the customer was contacted. The invite row is
still written (a resend works once the base URL is set) but with
`sent_channel = NULL`.

Staff and customers share one SPA, so one base URL serves both;
`CUSTOMER_PORTAL_BASE_URL` is kept only as an override for the day the customer
portal moves hosts.

### 2. Every notification on every channel was branded "Logistics"

`tenant_branding.get_company_name` read `branding.get("company_name")`. The
canonical `branding_config` shape has **`display_name`** — `company_name` is a
column on the `tenant` row, which `shared/notifications.py` never selected. And
`branding_config` is routinely `{}` (it is for every seeded tenant). So the
hardcoded fallback was reached every time: the literal word "Logistics" in every
email header, every `{company_name}:` SMS prefix and every WhatsApp parameter.

Fixed on both sides: `_tenant_branding` now selects `company_name` alongside
`branding_config` and sets it as a floor beneath the optional `display_name`
(the consumers run outside the VPC with no DB access, so it has to travel in the
message); `get_company_name` reads `display_name` → `company_name` → fallback.

### 3. The email body was a dump of field names

The body was a greeting, a CTA button, and every `template_data` key rendered as
a `Label: value` row — so a customer being invited received a header, a button,
and the single row "Name: Ngozi", with nothing saying what the message was or
why they had it. Each event now has a lead paragraph in EN and ZH, `name` and
`company_name` are no longer shown as rows (they are the greeting and the
header), support contacts and `document_footer` render when the tenant has
published them, and the plain-text part carries the same prose and the same
link instead of a bare field list.

A rendered body whose placeholders did not all resolve falls back to the generic
lead: a half-substituted sentence reads as a bug to the recipient, whereas the
generic lead plus the detail rows is always accurate.

### 4. Values were interpolated into HTML unescaped

`template_data` values come from customer records, staff input and imported
manifests, and went into the email body raw. A name or reference containing `<`
or `"` could break the layout or inject markup into a message sent under the
tenant's name. All values are now `html.escape(..., quote=True)` before
substitution; the templates are plain text so this is lossless.

### 5. A tenant's custom email body was never substituted

`html_body = body_override or render_email_html(...)` used the tenant's template
**verbatim**, so a custom body's `{name}` and `{invite_link}` were emailed
literally — the link arrived as the twelve characters `{invite_link}`. SMS had
always done `format_map`; email never did. Now `render_email_override` substitutes
(keeping the tenant's markup, escaping the values), the text part is derived from
the same override so the two MIME parts cannot disagree, and a malformed template
falls back to the default shell instead of emailing an empty body.

### Also found: an unconfigured WhatsApp send was reported as delivered

`send_whatsapp` returns `""` without raising when the Meta credentials are
missing. The handler fell through to `log_sent` + `record_usage`, so the log said
`sent` when nothing was sent, the tenant was **metered** for it, and — because no
exception was raised — the SMS fallback never fired. The customer got nothing on
either channel while the staff invite screen reported success. It now logs
`failed` and triggers the SMS fallback. (SMS and email already handled their
`False` returns; WhatsApp was the odd one out.)

### Verified live (local stack, Acme Shipping Ltd, `branding_config = {}`)

Invite issued through `POST /v1/customers/{id}/invite`; `notification_log` shows
`email: sent`, and the stored body reads:

```
Acme Shipping Ltd

Hello Invite Link Check,

Acme Shipping Ltd has created an account for you so you can track your
shipments, see what you owe and download your release notes. Use the button
below to choose a password and finish setting it up. The link expires in 48
hours — if it does, ask us to send a new one.

Invite link: http://localhost:5173/invite/wU2ieJgk...

This is an automated message from Acme Shipping Ltd.
```

`GET /v1/invites/{token}` resolves that token, so the link is functional and not
merely well-formed. WhatsApp and SMS correctly logged
`failed — provider unconfigured` (no credentials locally) instead of the former
false `sent`.

## Production readiness: what each channel needs (2026-11-13)

An audit comparing the env vars the notification code **reads** against the ones
Terraform **sets** — the same technique that found the `APP_BASE_URL` gap in task
7.128 — found that **neither cloud wired SMS or WhatsApp at all**. (An earlier
pass appeared to show AWS as wired; those matches came from
`infrastructure/aws/modules/lambda/.builds/package/`, an untracked local build
artifact that is a copy of the source, not Terraform.)

Every one of these failures is silent by construction: the send path logs
"not configured" and returns, so the deploy is healthy, the API returns 200, and
customers are simply never told anything.

| Variable | Channel | Purpose |
|---|---|---|
| `APP_BASE_URL` | all | Absolute base for `/activate/{token}` and `/invite/{token}` links |
| `CUSTOMER_PORTAL_BASE_URL` | all | Optional override, if the customer portal moves to its own host |
| `SES_FROM_ADDRESS` | email | Verified sender (SES identity, or the ACS managed-domain sender on Azure) |
| `AFRICASTALKING_API_KEY` | SMS | Africa's Talking API key |
| `AFRICASTALKING_USERNAME` | SMS | **Must be the live username.** The code default is `sandbox`, which accepts messages and delivers none, with a success-shaped response |
| `AFRICASTALKING_SENDER_ID` | SMS | Registered sender ID / short code, if any |
| `META_WHATSAPP_ACCESS_TOKEN` | WhatsApp | Meta Cloud API token |
| `META_WHATSAPP_PHONE_ID` | WhatsApp | Meta Cloud API phone number ID |
| `META_WHATSAPP_TEMPLATE_LANG` | WhatsApp | Language the templates were approved under — must match Meta exactly or every send 404s |
| `WHATSAPP_VERIFY_TOKEN` | WhatsApp | Shared secret Meta echoes when verifying the webhook |
| `NOTIFICATION_ALLOWLIST` | all | Contacts messageable **outside** production. Fails closed: empty means nothing is sent |

Now wired on **both** clouds — AWS through `modules/lambda` `common_env_vars`
(all Lambdas), Azure through `modules/container_app`, where the three credentials
are Container App **secrets** gated on their non-sensitive companion value
(`africastalking_username`, `meta_whatsapp_phone_id`) rather than on the secret
itself, since a predicate over a sensitive value marks the whole map sensitive
and breaks `for_each`.

### Plan-time guards

`terraform_data.notification_config_guard` (in both `infrastructure/aws/main.tf`
and `infrastructure/azure/main.tf`, modelled on the existing
`auth_config_guard`) fails the **plan** rather than letting a production deploy
succeed with channels that cannot send:

- a base URL is required in **every** environment, because a relative link is
  worse than no message;
- in **prod** only: the SES sender, the Africa's Talking key + username, and all
  three WhatsApp values. Non-prod is left free to run with channels off.

### Fail-loud behaviour in the send paths

- `SES_FROM_ADDRESS` unset in production → refuse to send from the placeholder,
  which SES/ACS would reject anyway, but as a provider error buried in
  `notification_log` that reads as a transient fault.
- `AFRICASTALKING_USERNAME == "sandbox"` in production → refuse. Sandbox traffic
  is accepted and silently undelivered, which is indistinguishable from working.
- Missing SMS key or WhatsApp credentials → logged at **ERROR**, not WARNING
  (WhatsApp is the primary customer channel, SMS only its fallback).
- Empty-string env vars count as unconfigured. Terraform sets `""` for an
  unconfigured variable, and `""` is "set" as far as `os.environ.get` is
  concerned, so a `get()` default would have been bypassed.
- Africa's Talking error payloads **echo the recipient MSISDN**, so the body is
  redacted (`_redact_provider_error`) and truncated before logging — a phone
  number must never reach CloudWatch.

### Still required from the operator — these cannot be done from code

1. **Verify the sending domain.** SES: verify the domain/address and move the
   account out of the sandbox. Azure: `module.acs` yields
   `DoNotReply@<azure-managed-domain>`, which works but is unreplyable and has
   low deliverability — a custom verified domain is advisable before launch.
2. **Africa's Talking live account**, plus a registered sender ID (Nigerian
   networks commonly require pre-registration for alphanumeric senders).
3. **Meta WhatsApp Business**: a verified business, a phone number, and **each
   template in `WA_TEMPLATE_MAP` / `WA_TEMPLATE_MAP_ZH` approved by Meta under
   that exact name and language**. An unapproved name 404s, which the handler
   now reports and falls back from, but no message goes out.
4. Subscribe the WhatsApp webhook to the deployed
   `POST /v1/webhooks/whatsapp`, using `WHATSAPP_VERIFY_TOKEN`.
5. Populate `NOTIFICATION_ALLOWLIST` in dev/staging before testing — it fails
   closed, so nothing is sent until it is set.

### Local development

`make bootstrap` now verifies an SES identity in Moto, because Moto enforces
SES's verified-identity rule exactly as AWS does: local email was being sent
from the placeholder address and rejected with
`MessageRejected: Email address not verified`, so local email delivery failed
outright while SMS and WhatsApp appeared to work. `.env.local` sets
`APP_BASE_URL=http://localhost:5173` and `SES_FROM_ADDRESS=notifications@shipx.local`.

## Tenant Notification Preferences

The publishing service checks `tenant.notification_preferences` before enqueueing. If a channel is disabled for that event type, no SQS message is sent. The notification Lambda does NOT need to re-check.

## Error Handling

- Invalid phone/email → log warning, message goes to DLQ after 3 retries
- External API failure (Africa's Talking down) → SQS retry with backoff
- DLQ messages: CloudWatch alarm triggers when DLQ has > 0 messages

## Notification Template Management API

Tenant admins can override the hardcoded templates per event type and channel.

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/v1/tenant/notification-templates` | List all custom templates for the tenant |
| GET | `/v1/tenant/notification-templates/{event_type}/{channel}` | Get a specific template |
| PUT | `/v1/tenant/notification-templates/{event_type}/{channel}` | Create or update a template |

**Roles**: `tenant_admin` only.

**Request body** (PUT):
```json
{
  "template_body": "{{company_name}}: Your container {{container_number}} has arrived!",
  "subject": "Your goods have arrived"
}
```

`subject` is used only for email channel; ignored for SMS and WhatsApp.

For WhatsApp, `template_body` must be a pre-approved Meta template name.

**How it works**: `enqueue_notifications` in `shared/notifications.py` queries `notification_template` at enqueue time and embeds the custom copy as `template_override` in the SQS payload. The notification Lambda reads `template_override` before falling back to hardcoded defaults.

## Container Arrival Notification

When a container transitions to `at_warehouse`, `services/tracking/service.py` calls `enqueue_notifications` with `event_type="container_arrived"` for every customer with approved packing lists in that container. All three channels (SMS, WhatsApp, email) are attempted subject to tenant notification preferences.

## Customer Registration Notification

When a customer self-registers via `POST /v1/register/{slug}`, a welcome notification is enqueued with `event_type="customer_registered"`.

When someone registers with an email that **already has an account**, nothing is created and `registration_existing_account` is emailed to that address instead (audit SEC-04): the page answers `202` either way, so this email is how the owner finds out. It is **email only** (no SMS or WhatsApp), carries a sign-in link (`login_link`, labelled "Sign in"), is an account event that is always sent (below), and greets the account's own name, never what the registrant typed.

## Customer Account-Creation Invite Notification

When a customer is issued an account-creation invite (`POST /v1/customers/{id}/invite`, or auto-issued on manifest import for newly created customers — `07_api_tenant_management.md` §"Customer Account-Creation Invites"), a notification is enqueued with `event_type="customer_invite"` and `template_data={"name", "invite_link"}`. SMS is the primary channel since imported customers typically have only a phone. Added to all five template dicts in `services/notification/service.py` (`_SMS_TEMPLATES`/`_SMS_TEMPLATES_ZH`, `EMAIL_SUBJECTS`/`EMAIL_SUBJECTS_ZH`, both `WA_TEMPLATE_MAP`s), following the `customer_registered` entries.

## Ground-truth audit: every notification event, wired or dead (2026-09-09)

User report: "a staff rejected a payment marked as paid, but no notification was showing when I logged into the staff account. Check all notifications within the app and ensure all are working." Investigation found two separate problems:

1. **No in-app staff notification system exists at all.** `TopBar.tsx` renders a bell icon with an unread-count badge and an `onNotificationsClick` handler — its own doc-comment says "wired to GET /v1/notifications/log in Task 07" — but `StaffLayout.tsx` (the only place that mounts `TopBar` for staff/admin) never passes it `notifications` or `onNotificationsClick`. The bell always shows 0 and does nothing when clicked, in every real screen. **Scoped out of this fix** — the user confirmed customer-facing notifications were the priority; a real staff "new work for you" feed (unread state, a table/db-backed model, UI) is a separate feature, not a bug fix.
2. **6 of 8 `NotificationEvent` values were defined with full SMS/WhatsApp/email templates but never triggered anywhere** — `reject_payment_claim`/`confirm_payment_claim` (the exact action the user performed) only published an EventBridge event that was never wired into any routing rule (`infrastructure/aws/modules/eventbridge/main.tf` only routes `ShipmentStatusUpdated`/`PaymentDue`/`ReleaseNoteGenerated`/`CBMDisputeResolved`/`PackingListApproved`/`DamageClaimFiled`/`TenantOnboarded`/`TenantSuspended` — and even those routed ones don't reach `shared/notifications.py`, since EventBridge and the SQS-based notification pipeline are two disconnected systems). The customer was never actually told either way.

Fixed by calling `shared/notifications.py::enqueue_notifications` directly from the business-logic function itself (same pattern `container_arrived`/`release_note_generated` already used), not by trying to route EventBridge into the notification queues. Every new call site is **best-effort and wrapped in try/except** — a notification-send failure must never fail the underlying action (confirm/reject a claim, approve a packing list, etc.), matching the established pattern for the two events that already worked.

| Event | Where it's fired | Recipient | Status before this fix |
|---|---|---|---|
| `payment_claim_confirmed` (new) | `payment_release/service.py::confirm_payment_claim` | customer | did not exist |
| `payment_claim_rejected` (new) | `payment_release/service.py::reject_payment_claim` | customer | did not exist — **the exact bug reported** |
| `payment_due` | `billing/service.py::handle_payment_due` (invoice created) | customer | dead — templates existed, never called |
| `shipment_update` | `tracking/service.py::update_container_status`, for `in_transit`/`arrived`/`customs_clearance`/`fully_released` (not `at_warehouse` — that's `container_arrived`; not `cleared` — that's `payment_due`, which is richer than a bare status ping) | customer | dead |
| `damage_claim_update` | `claims/service.py::start_inspection` and both `resolve_claim` paths (old-style + `_resolve_claim_new_style`) | customer | dead |
| `packing_list_approved` | `packing_list/service.py::_apply_approval_side_effects` (shared by single-item and bulk approve) | customer | dead |
| `tenant_onboarded` | `tenant_management/service.py::create_tenant` | the new tenant's primary contact | dead |
| `tenant_suspended` | `tenant_management/service.py::suspend_tenant` | the tenant's primary contact | dead |
| `release_note_generated` | `scheduled/release_expiry.py` | customer | already worked |
| `cbm_dispute_update` | `scheduled/sla_check.py`, `scheduled/dispute_escalation.py` | **staff** (email only) — the only staff notification anywhere in the app | already worked |

`payment_claim_confirmed`/`payment_claim_rejected` are new event types, added to `_SMS_TEMPLATES`/`_SMS_TEMPLATES_ZH`/`WA_TEMPLATE_MAP`/`WA_TEMPLATE_MAP_ZH`/`WA_TEMPLATE_PARAMS`/`EMAIL_SUBJECTS`/`EMAIL_SUBJECTS_ZH` in `services/notification/service.py` (not added to the `NotificationEvent` enum — following the existing precedent of `container_arrived`/`customer_registered`/`customer_invite`, which are also ad-hoc string event types outside the enum). `damage_claim_update` and `packing_list_approved` gained the SMS-template entries they were previously missing (WhatsApp/email templates already existed for all six).

Each new business-logic function needed a customer-contact lookup; `get_customer_contact(tenant_id, customer_id)` was added identically to `billing`, `claims`, `packing_list`, and `payment_release`'s own `repository.py` (not centralized into `shared/` — matches this codebase's existing per-service `get_customer_by_user_id` duplication, a deliberate microservice-isolation choice, not an oversight).

**Verified live end-to-end against the real local stack** — the actual scenario the user described: submitted a fresh payment claim as a real customer, rejected it as staff via `PATCH /v1/payments/claims/{id}/reject`, confirmed both a WhatsApp and an email `payment_claim_rejected` message were enqueued to the real (Moto) SQS queues, then drained them through `scripts/drain_notifications.py` — WhatsApp correctly triggered its SMS fallback when Meta rejected the (not-yet-registered) template, and all three attempts landed in `notification_log` with the correct amount/reason/recipient, visible on `GET /v1/notifications/log` (the staff-facing Notification Log page). The two send failures (Meta template not registered, SES/Africa's Talking not configured) are expected local-dev limitations, not code bugs — the pipeline itself now runs end-to-end where before nothing was ever enqueued at all.

Tests: `TestConfirmPaymentClaim`/`TestRejectPaymentClaim` (`test_payment_release.py`), `TestHandlePaymentDueNotification` (`test_billing.py`), `TestShipmentUpdateNotification` (`test_tracking.py`), `TestClaimStatusChangeNotifications` (`test_claims.py`), `TestApprovalNotifiesCustomer` (`test_packing_list.py`), `TestCreateTenantNotifiesOnboarding` + notification tests in `TestSuspendTenant` (`test_tenant_management.py`) — each event covers the happy path, a missing-contact no-op, and a notification failure not breaking the primary action. 714 backend tests pass.

## Staff notification bell (2026-09-12)

Direct user follow-up to the audit above: "let's go through the whole notification including the frontend notification to resolve all." Confirmed as the user's chosen scope: build the real thing (a per-user read/unread feed, new table, new API, real frontend wiring), not a cheaper live-actionable-count alternative.

**Backend.** `shared/staff_notifications.py::notify_staff()` is modeled directly on `shared/audit.py::log_audit` — it never raises, so every call site below is safe to call unmocked. Writes to `staff_notification` (migration 046, full schema in `05b_database_schema_extended.md`), broadcast to a role (`target_role`) or targeted at one person (`target_user_id`); read state lives in the separate `staff_notification_read` table so a role-broadcast notification is independently readable per recipient.

API (all in `services/notification/handler.py`, same Lambda as the notification log):

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/v1/notifications/staff` | tenant_admin, nigeria_office_staff, china_office_staff, warehouse_attendant | `?unread_only=true` filters; cursor-paginated, `is_read` resolved per-viewer via a `LEFT JOIN` against `staff_notification_read` |
| GET | `/v1/notifications/staff/unread-count` | same | TopBar bell badge |
| PATCH | `/v1/notifications/staff/{id}/read` | same | idempotent — `ON CONFLICT (notification_id, user_id) DO UPDATE`, re-marking an already-read row is a no-op, not an error |
| PATCH | `/v1/notifications/staff/mark-all-read` | same | bulk-inserts read rows for every currently-unread-and-visible notification; returns `{"marked_read": N}` |

Note this is deliberately a **broader** role set than `GET /v1/notifications/log` (`tenant_admin`/`nigeria_office_staff` only, a compliance/audit view) — the bell is for anyone who works inside a tenant.

`ctx.user_id` (the Cognito sub) is used directly as `staff_notification.target_user_id`/`staff_notification_read.user_id` with no separate lookup — `tenant_user.id` is deliberately set equal to `cognito_sub` at creation (`tenant_management/repository.py::create_tenant_user`) specifically so every FK to `tenant_user(id)` can use `ctx.user_id` straight off the JWT.

**Trigger sites** — every one is a "staff needs to act" or "staff should know" moment, broadcasting to every relevant role (called once per role, since `notify_staff` targets one role per call):

| Event | Where | Broadcast to |
|---|---|---|
| `payment_claim_submitted` | `payment_release/service.py::submit_payment_claim` | nigeria_office_staff, tenant_admin |
| `damage_claim_filed` | `claims/service.py::file_claim` — only when a **customer** files it; a staff-filed claim doesn't self-notify | nigeria_office_staff, tenant_admin |
| `packing_list_submitted` | `packing_list/service.py::submit_packing_list` and `bulk_submit_packing_lists` | china_office_staff, tenant_admin |
| `cbm_dispute_filed` | `billing/service.py::file_cbm_dispute` | nigeria_office_staff, tenant_admin |
| `cbm_dispute_sla_breach` | `scheduled/sla_check.py::_notify_nigeria_staff` — alongside the pre-existing email | nigeria_office_staff |
| `cbm_dispute_escalated` | `scheduled/dispute_escalation.py::_notify_escalation` — alongside the pre-existing email | china_office_staff, tenant_admin |

**Bulk actions and `entity_id`:** `entity_id` is a single-row UUID column. `bulk_submit_packing_lists` passes `entity_id=None` rather than a comma-joined id list — the same silent-failure shape `log_audit`'s own `BULK_APPROVE` call already has for its `entity_id` (a UUID column fed a comma-joined string fails the cast; both `log_audit` and `notify_staff` swallow the exception, so it would otherwise fail with no visible error at all).

**Frontend.** `TopBar.tsx` gained a `notificationsPanel` prop rendered inside the bell's own `position: relative` wrapper (`.bellWrap`), so a dropdown anchors under the bell regardless of what else sits in the TopBar's right side — no change to the bell button itself beyond that wrapper. `StaffLayout.tsx` (the only place that mounts `TopBar` for staff/admin) now polls `useStaffNotifUnreadCount` (30s, pauses when the tab is backgrounded — same pattern as `useNotifLogPolling`) and renders `StaffNotificationPanel` (new, `frontend/src/shell/`) as that panel: header with a "Mark all read" button (shown only when something is unread), a scrollable list of rows (title/body/relative time, an unread dot, click-to-mark-read), and an empty state. Gated with the same `!isPlatformShell` check `useBranding` already uses — a bare platform admin has no tenant context and `GET /v1/notifications/staff` would 403 for that role anyway.

Verified live against the real local stack: submitted a payment claim as a real customer → `nigeria_office_staff`'s unread count went 0 → 1, the row appeared with the correct title/amount; marking it read as that user dropped their count to 0 while a separate `tenant_admin` session's count stayed at 1 (independent per-viewer read state, confirmed); `mark-all-read` cleared it; a `customer`-role request to any staff-notification route correctly 403s. Filed a damage claim as a customer and confirmed the second event type lands correctly too, newest-first.

Tests: `tests/unit/test_staff_notifications.py` (repository SQL correctness, service, handler routing/roles, and `notify_staff`'s never-raises contract), plus a notification test added to each trigger site's existing test file (`test_payment_release.py`, `test_claims.py`, `test_packing_list.py`, `test_billing.py`, `test_scheduled_jobs.py`). Frontend: `TopBar.test.tsx` (+1), `StaffLayout.test.tsx` (+4: unread count shown, panel opens on click, platform_admin gets neither), new `StaffNotificationPanel.test.tsx` (7 cases). 737 backend + 686 frontend tests pass.

## Customer notification bell + local-dev delivery plumbing (2026-09-12)

Direct user follow-up, reported live right after using the just-shipped staff bell: "i rejected ifexalex2@gmail[.com]'s submitted payment with a comment that we did not receive the payment, and i did not see the notification when i logged in as ifexalex2@gmail.com." Investigating this one report turned up three separate, real problems — confirmed one at a time against the actual local stack, not assumed:

1. **The notification code was correct** — rejecting the claim did enqueue a WhatsApp message and an email to the customer, confirmed from the request log at the exact timestamp of the real rejection.
2. **Nothing in local dev ever processes that queue.** In AWS, an SQS→Lambda event-source mapping does this instantly; nothing plays that role against Moto locally, so a queued message just sits there until someone manually runs `scripts/drain_notifications.py`. This is the same class of issue as the two channel-specific failures below, but the one that actually explains "I saw *nothing at all*" — even a fully-configured provider wouldn't have helped, since the message was never even attempted until drained by hand.
3. **The customer portal had no in-app "you have news" signal at all** — `CustomerTopNav.tsx` already had a bell icon with an unread badge (same as the staff `TopBar.tsx` had before its own fix), but `CustomerLayout.tsx` never fed it any data. The rejection reason only ever surfaced if the customer happened to open that one billing record's detail page.

The user chose to fix all three.

### 1. Auto-draining notifications in local dev

`scripts/local_server.py` now spawns `scripts/drain_notifications.py --watch` as a background **process** on startup (`subprocess.Popen`, terminated via `atexit` when the server stops) — not a background *thread*. This distinction is load-bearing: `app.run(..., threaded=False)` a few lines below is itself there because `shared/db.py`'s module-level connection singleton isn't thread-safe (a prior real incident — see that call's own comment), and a poller thread sharing this process's connection would reintroduce exactly the concurrent-access corruption that `threaded=False` exists to prevent. A separate OS process gets its own interpreter and its own connection singleton, so it can poll continuously with zero risk to the server's own DB state. Opt out with `DISABLE_NOTIFICATION_DRAIN=true` if ever needed; on by default since the entire point is that a developer testing the product shouldn't have to know this script exists.

### 2. Recipient allowlist

`ifexalex2@gmail.com` (the phone `+2348169760253`/`08169760253` was already there) added to `.env.local`'s `NOTIFICATION_ALLOWLIST` — the email channel was being silently blocked by `is_recipient_allowed()`'s fail-closed non-production guard (`shared/notifications.py`), which only ever checks recipient values already present in that list. Verified live: before the fix, an email attempt logged `"Blocked email send to a non-allowlisted recipient outside production"`; after, it logged `"send_email raised an exception"` — progress, not a full fix, since local dev still has no real SES credentials to actually deliver with (same category of limitation as WhatsApp's unregistered template and SMS's missing Africa's Talking key). In production, with real provider credentials, this would deliver.

### 3. Customer notification bell

Reuses the **exact same `staff_notification`/`staff_notification_read` tables and service/repository functions** as the staff bell — they were already fully generic (tenant_id + user_id + role, no staff-specific logic) — targeted via `target_user_id` instead of `target_role`, since a customer notification is always 1:1, never a role-wide broadcast. `customer.user_id` (== `tenant_user.id` when the customer has a portal account, set by `link_customer_user` — `NULL` for a customer with no login) was added to the `get_customer_contact()` helper's SELECT in all four repos that have one (billing, claims, packing_list, payment_release) and to `tracking/repository.py::get_customers_for_container`, so every existing customer-notification call site could resolve it for free.

Each of the 6 customer-facing trigger sites now calls `notify_staff(target_user_id=..., ...)` immediately after its existing `enqueue_notifications` call, guarded on `customer.get("user_id")` being set (a customer with no portal account can't receive an in-app notification, only SMS/email/WhatsApp): `payment_claim_confirmed`/`payment_claim_rejected` (`payment_release/service.py` — **the exact reported case**), `payment_due` (`billing/service.py`), `shipment_update` + `container_arrived` (`tracking/service.py`), `damage_claim_update` (`claims/service.py`), `packing_list_approved` (`packing_list/service.py`).

**API:** new `_dispatch_customer_notifications` in `services/notification/handler.py`, mounted at `/v1/notifications/customer/...` (list, `/unread-count`, `PATCH .../{id}/read`, `PATCH .../mark-all-read`) — identical shape to the staff routes, role-gated to `UserRole.CUSTOMER` only, calling the very same `service.list_staff_notifications`/etc. functions with the customer's own `ctx.user_id`/role. No renaming of the underlying `staff_notification` table or its repository/service functions — a rename now that two audiences share it would be more accurate, but was judged not worth the mechanical churn across every already-shipped, already-tested call site; the API-contract layer is what actually needs an audience-appropriate name, and that's what the new `/customer` route prefix gives it.

**Frontend:** `frontend/src/api/customerNotifications.ts` + `frontend/src/hooks/useCustomerNotifications.ts` mirror the staff versions exactly (the `CustomerNotification` type is a re-export of `StaffNotification` — same row shape). `CustomerTopNav.tsx` gained the same `notificationsPanel`/`onNotificationsClick` props and `.bellWrap` positioning wrapper `TopBar.tsx` has; `CustomerLayout.tsx` wires them to a new `CustomerNotificationPanel.tsx` (kept as its own small component reusing `StaffNotificationPanel.module.css`, rather than one shared component with a role switch — the staff and customer shells never share a render tree, and CLAUDE.md's guidance is that three similar lines beat a premature abstraction).

**Verified live end-to-end, reproducing the user's exact report**: submitted a fresh payment claim as `ifexalex2@gmail.com`, rejected it as staff with reason "we did not receive your payment" — without running any script by hand, the background drain process picked up the queued messages within seconds and `notification_log` showed all three channel attempts; separately, `GET /v1/notifications/customer/unread-count` for that same customer went from 0 to 1, and the row's title/body matched exactly ("Payment claim rejected" / "Your payment claim of NGN 15000.00 was not confirmed. Reason: we did not receive your payment").

Tests: `TestNotifyStaffNeverRaises`/`TestStaffNotificationRepository` unaffected (fully generic already); new `TestCustomerNotificationHandler` in `test_staff_notifications.py` (list/unread-count/mark-read/mark-all-read routes, staff-role-forbidden); a second notification test added per trigger-site file for the in-app case (`test_confirming_also_notifies_the_customer_in_app_...`, `test_rejecting_also_notifies_...`, `test_no_in_app_notification_for_a_customer_with_no_portal_account`, one set per file: `test_payment_release.py`, `test_billing.py`, `test_claims.py`, `test_packing_list.py`, `test_tracking.py` ×2 for both tracking events). Frontend: `CustomerTopNav.test.tsx` (+1), `CustomerLayout.test.tsx` (+2, plus the existing 2 fixed to wrap in `QueryClientProvider` — a pre-existing gap in that test file, unrelated to this feature, that only surfaced once the layout started using `useQuery`), new `CustomerNotificationPanel.test.tsx` (7 cases). 755 backend + 696 frontend tests pass.

## Clearing notifications + manual announcements (2026-09-12)

Direct user follow-up to the two bells above: "The notification should allow clearing. Secondly tenant admin and nigeria staff should be able to send a announcements, for example during celebration sessions, or import announcements." Clarified with the user that an announcement's audience is one broad choice per send — every staff member in the tenant, or every customer — not a role/person picker.

### Clearing

`migrations/versions/047_staff_notification_dismissed.py` adds `staff_notification_read.dismissed_at TIMESTAMPTZ`. Clearing is **per-viewer**, living on the same read-state row as `read_at` — a role-broadcast notification cleared by one recipient stays visible, unread state and all, to every other recipient. Clearing always implies read (both timestamps set together); dismissed rows are excluded from `list_staff_notifications`'s query entirely (`AND r.dismissed_at IS NULL`), not just hidden client-side, so a cleared notification never counts toward `unread-count` either.

| Method | Path | Roles | Notes |
|---|---|---|---|
| DELETE | `/v1/notifications/staff/{id}` | same as GET /staff | clears one, for the caller only — `ON CONFLICT (notification_id, user_id) DO UPDATE`, safe to call on a row with no prior read-state |
| DELETE | `/v1/notifications/staff/clear-all` | same | clears every currently-visible, undismissed notification for the caller; returns `{"cleared": N}` |
| DELETE | `/v1/notifications/customer/{id}` | customer | identical semantics, customer-scoped |
| DELETE | `/v1/notifications/customer/clear-all` | customer | identical semantics, customer-scoped |

### Manual announcements

New `POST /v1/notifications/announce` (`tenant_admin`, `nigeria_office_staff` only — `ctx.assert_role`), body `{title, body?, audience: "all_staff" | "all_customers"}` (`SendAnnouncementRequest` in `services/notification/models.py`). Backed by a new `repository.create_staff_notification()` — a direct, **error-propagating** insert, deliberately not the existing `notify_staff()` fire-and-forget helper: an announcement is the entire user-initiated action, so a failed send must surface as a real error to the composer rather than silently no-op the way a side-effect notification piggybacking on an unrelated write is allowed to.

Audience fan-out, in `service.py::send_announcement`:
- `all_staff` → one `staff_notification` row **per staff role** (`tenant_admin`, `nigeria_office_staff`, `china_office_staff`, `warehouse_attendant` — mirrors `handler.py`'s `_STAFF_NOTIF_ROLES`), never a bare `target_role=NULL`/`target_user_id=NULL` row. The existing visibility filter treats NULL/NULL as "visible to literally everyone," which a customer's identical visibility check would also match — fanning out by role is what keeps a staff announcement out of the customer bell.
- `all_customers` → one row with `target_role="customer"`, the one `target_role` value a customer's own `ctx.role` actually equals, so it naturally reaches every customer and no staff member.

Audit: `log_audit(entity_type="announcement", action="CREATE", ...)`, called once per send with `entity_id` set to the first created notification's id — only when at least one row was actually created, since `audit_log.entity_id` is `UUID NOT NULL` and a wholly-failed send has no id to log against (that failure already propagated as an exception before reaching the audit call).

**Frontend:** `frontend/src/api/announcements.ts` (new), `useDismissStaffNotif`/`useClearAllStaffNotif` (+ customer equivalents) in the existing hook files, new `frontend/src/shell/ComposeAnnouncementModal.tsx` (Title/Message/audience-Chip form). `StaffNotificationPanel.tsx`'s row is now a wrapper `<div>` around a `rowMain` click-to-mark-read button and a separate `clearBtn` ×, plus a `.headerActions` row with "Mark all read" and "Clear all", plus a `useSession()`-gated "New announcement" trigger (`ANNOUNCE_ROLES = {tenant_admin, nigeria_office_staff}`, mirroring the backend's `_ANNOUNCE_ROLES`) opening the compose modal. `CustomerNotificationPanel.tsx` got the same row/clear restructuring but no announcement trigger — customers can only receive, never send.

**Verified live against the real local stack**: sent an `all_staff` announcement as `nigeria_office_staff` → 4 rows created (one per role); confirmed `tenant_admin`/`nigeria_office_staff`/`china_office_staff`/`warehouse_attendant` all see it and a `customer` session does not; `china_office_staff` correctly 403s on the announce route itself. Sent an `all_customers` announcement as `tenant_admin` → 1 row created, reached two different customer sessions (role-broadcast, not per-user), invisible to staff. Dismissed one notification as one recipient of a broadcast row and confirmed a different recipient's copy was unaffected; `clear-all` for one user returned the correct count and left every other recipient's list untouched; repeated the same dismiss/clear-all check on the customer route.

Tests: `TestStaffNotificationRepositoryDismiss` (3), `TestStaffNotificationHandlerDismiss` (3), `TestSendAnnouncement` (5) added to `test_staff_notifications.py`. Frontend: `StaffNotificationPanel.test.tsx` grew from 7 to 13 cases (clear-one, clear-all visibility/call, announcement-trigger role-gating for tenant_admin/other-role/no-session — and its `renderPanel` helper now wraps in `SessionContext.Provider`, required once the component started calling `useSession()`), `CustomerNotificationPanel.test.tsx` grew from 7 to 11 (clear-one, clear-all, confirms no announcement trigger ever renders), new `ComposeAnnouncementModal.test.tsx` (8 cases: default audience/disabled-until-title, submit with title+body, audience switch, blank-body-sends-undefined, success closes+resets, error banner on failure, Cancel doesn't submit). 766 backend + 714 frontend tests pass.

### Follow-up: staff customer-announcements now require tenant_admin approval (2026-09-12)

Direct user follow-up, sent immediately after the above shipped: "Tenant admin can send announcement to all staffs and all customers. But the staff can only send to customers, which should be approved by the tenant admins, this is to ensure that a compromised staff does not misinformation the customers." Two trust-model changes, both enforced in `services/notification/handler.py::_handle_send_announcement`:

1. `nigeria_office_staff` can no longer target `all_staff` at all — that audience is now `tenant_admin`-only. Picking `all_staff` as `nigeria_office_staff` raises `InsufficientPermissionsError` (403), not just a stricter version of the send.
2. A `nigeria_office_staff` → `all_customers` request no longer creates any `staff_notification` row immediately. It's held in a new `announcement_request` table (migration `048_announcement_request.py`, RLS on, standard tenant-isolation policy) with `status` (`pending`/`approved`/`rejected`), `requested_by`, `reviewed_by`, `reviewed_at`, `rejection_reason`. `tenant_admin`-composed announcements (either audience) are unaffected — they still send immediately via the existing path.

`POST /v1/notifications/announce`'s response now branches by role: `tenant_admin` gets back `{"status": "sent", "audience": ..., "notifications_created": N}` (an additive field on the existing shape — `status` didn't exist in the previous response); `nigeria_office_staff` gets `{"status": "pending", "request_id": ..., "audience": "all_customers"}`.

New review-queue API, all `tenant_admin`-only, originally on `services/notification/handler.py::_dispatch_announcement_requests` (routes shown here as first shipped — see the "Announcements page + full CRUD" follow-up below for the route restructuring this went through immediately after):

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/notifications/announcements/pending` | cursor-paginated, oldest-first (submitted-earliest reviewed first) |
| PATCH | `/v1/notifications/announcements/{id}/approve` | creates the real `staff_notification` row(s) via the same `_create_announcement_notifications()` fan-out `send_announcement` uses, marks the request `approved`, notifies the original requester |
| PATCH | `/v1/notifications/announcements/{id}/reject` | body `{reason?}` (`RejectAnnouncementRequestBody`), marks `rejected`, notifies the requester with the reason if given |

Both approve/reject use `repository.mark_announcement_request_reviewed()`'s `WHERE status = 'pending'` guard to make double-review impossible — a second call on an already-reviewed row matches zero rows, returned as `None`, which the service layer raises as `IllegalTransitionError` (409). Submitting a request also fires `notify_staff(target_role="tenant_admin", event_type="announcement_request_submitted", ...)` so the queue doesn't rely on someone remembering to check it; approval/rejection each fire a matching notification back to `requested_by`.

**Frontend (superseded by the page-move follow-up below):** this iteration first shipped the review queue inside a `ManageAnnouncementsModal.tsx` opened from the notification bell popup — deleted in the very next follow-up once the user asked for a dedicated page instead.

**Verified live**: `nigeria_office_staff` → `all_staff` correctly 403s before any row is created; `nigeria_office_staff` → `all_customers` creates a pending request only (customer bell shows nothing yet, requesting staff's own bell shows nothing, `tenant_admin`'s bell shows "Announcement awaiting approval"); `tenant_admin` GET `/pending` lists it; approving creates the real notification (customer bell now shows it, requester's bell shows "Your announcement was approved").

Tests: `TestAnnouncementRequestService` (5), `TestAnnouncementRequestHandler` (6) added to `test_staff_notifications.py`, plus 2 rewritten `TestSendAnnouncement` cases reflecting the new role split. 778 backend tests pass. Docs/Postman updated in the same pass as the banner follow-up immediately below.

### Follow-up: announcement banner (2026-09-12)

Direct user follow-up, sent while reviewing the approval feature above: "annoucement should be a banner on the target user's web page, with this they won't miss it. It can be enabled or disabled, more can be created but only one can be visible per time. with this. we can add amination to it, so that it is obvious to the target user."

Migration `049_announcement_banner.py` adds two columns to `staff_notification`, meaningful only for `entity_type = 'announcement'` rows:
- `announcement_group_id` — one send's fan-out (4 rows for `all_staff`, 1 for `all_customers`) shares one group id, so enabling/disabling or listing treats them as a single announcement rather than up to 4 near-duplicates.
- `banner_active` — whether this row's audience currently sees it as a page banner (not just a bell entry).

**"Only one visible at a time" is enforced per audience, not globally** — a staff banner and a customer banner are independent, so sending one never retires the other (a "your bell shows a staff notice" fact has nothing to do with what a customer sees). Every call that creates a banner-eligible announcement (`_create_announcement_notifications`, shared by an immediate `tenant_admin` send and an approved staff request) first calls `repository.deactivate_active_banners_for_roles(tenant_id, target_roles)` — `target_roles` is the 4 staff roles for `all_staff` or `["customer"]` for `all_customers` — before inserting the new group with `banner_active=True`.

New endpoints:

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/v1/notifications/staff/banner` | any staff role | the single active announcement for this viewer's audience, or `null` |
| GET | `/v1/notifications/customer/banner` | customer | same, customer-scoped |
| GET | `/v1/notifications/announcements` | tenant_admin | banner management history — one entry per send (`DISTINCT ON (announcement_group_id)`, grouped in `repository.list_announcement_groups`), newest first |
| PATCH | `/v1/notifications/announcements/{group_id}/deactivate` | tenant_admin | turns off every row in the group at once |
| PATCH | `/v1/notifications/announcements/{group_id}/activate` | tenant_admin | re-shows a past announcement — first deactivates whatever else is active for that same audience (same dedup a fresh send does), then re-activates the group |

**Frontend:** new `AnnouncementBanner.tsx`, a presentational component (banner data in, `onDismiss` out) mounted once each in `StaffLayout.tsx` and `CustomerLayout.tsx` in the same slot as `ImpersonationBanner`/`QuotaWarningBanner`, backed by new `useStaffBanner`/`useCustomerBanner` hooks (60s poll, paused when the tab is hidden — same pattern as the unread-count hooks, gated identically: off for a bare `platform_admin`). Built on the existing `Banner` design component wrapped in a CSS-animated container (`AnnouncementBanner.module.css`: a slide-down entrance plus two pulses of a glowing outline, `prefers-reduced-motion` respected) for the "so it is obvious" requirement. Dismissing is per-tab-session only (component state, not persisted) — closing it doesn't touch the backend, so it reappears on reload or in another tab until a `tenant_admin` actually deactivates it; a genuinely different banner (new id) always shows regardless of what was dismissed before. Management UI for this first iteration lived in `ManageAnnouncementsModal.tsx` (a second section below the pending-approval queue, each row with a `ToggleSwitch`) — deleted in the very next follow-up below.

**Verified live**: two sequential `all_customers` sends — only the second one active, first one auto-deactivated; re-activating the first one retired the second (dedup confirmed both directions); an `all_staff` send's active banner had zero effect on the customer banner and vice versa; manual deactivate correctly zeroed out the customer's banner response.

Tests: `TestAnnouncementBanner` (9 cases) added to `test_staff_notifications.py`. 787 backend tests pass. Frontend: new `AnnouncementBanner.test.tsx` (6), new `ManageAnnouncementsModal.test.tsx` (5), `StaffLayout.test.tsx`/`CustomerLayout.test.tsx` each +3 (shows banner, no banner, platform_admin doesn't fetch — staff only), `StaffNotificationPanel.test.tsx` +2 ("Manage announcements" shown for tenant_admin only), `ComposeAnnouncementModal.test.tsx` rewritten with a `nigeria_office_staff` describe block (3 new cases: no "All staff" chip, "Submit for approval" label + explanation, audience locked to `all_customers`). 735 frontend tests pass.

### Follow-up: Announcements page + full CRUD + Publish/Unpublish (2026-09-13)

Two more direct follow-ups, sent back to back while reviewing the modal-based version above: "no, i wan the annoucement management to be on it's own page, not on the notification popup... Annoucement is managed in that page (CRUD), and they can enable only one announcement to be visible per time. for admin they can toggle staffs and customers. no approval is required for them to publish it. For staff they can only sent to customers, but it must be approved by the admin before it can become visible to the customer. The banner should have a colour that draws attention too. look at the color pallet" — then, seeing the first pass: "Instead of toggle to enable an announcement, let it be "publish". For the admin. For staff, it will be submit announcement (it will show the state) once it is approved, it will show approved on the staff's end."

**Route restructuring — two id spaces, disambiguated by a literal segment.** `announcement_request.id` (a staff submission) and `staff_notification.announcement_group_id` (an already-live announcement) previously shared the same `/v1/notifications/announcements/{id}/...` path with no way to tell which table `{id}` names. Fixed by moving every request-scoped route under a `requests/` prefix; every id directly under `/announcements/{id}` is now unambiguously a group id. `services/notification/handler.py::_dispatch_announcement_requests` was renamed `_dispatch_announcements` and its previous single blanket `ctx.assert_role(TENANT_ADMIN)` replaced with a per-branch check, since `nigeria_office_staff` now owns some of these routes too:

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/v1/notifications/announcements` | tenant_admin | history/management list (unchanged path) |
| GET | `/v1/notifications/announcements/pending` | tenant_admin | review queue (unchanged path) |
| GET | `/v1/notifications/announcements/mine` | nigeria_office_staff | **new** — a staff member's own submissions, every status, not just pending |
| PATCH | `/v1/notifications/announcements/requests/{id}/approve` | tenant_admin | moved from `/{id}/approve` |
| PATCH | `/v1/notifications/announcements/requests/{id}/reject` | tenant_admin | moved from `/{id}/reject` |
| PATCH | `/v1/notifications/announcements/requests/{id}` | nigeria_office_staff, own+pending only | **new** — edit a still-pending request's title/body |
| DELETE | `/v1/notifications/announcements/requests/{id}` | nigeria_office_staff, own+pending only | **new** — withdraw a still-pending request |
| PATCH | `/v1/notifications/announcements/{group_id}/activate` \| `/deactivate` | tenant_admin | unchanged |
| PATCH | `/v1/notifications/announcements/{group_id}` | tenant_admin | **new** — edit a sent announcement's title/body across its whole group |
| DELETE | `/v1/notifications/announcements/{group_id}` | tenant_admin | **new** — permanently delete a sent announcement; cascades to `staff_notification_read` via its existing FK, so it disappears from every recipient's bell history too, not just the banner |

New repository functions all follow the same ownership/status guard pattern as `mark_announcement_request_reviewed`: `update_announcement_request`/`delete_announcement_request` are scoped to `requested_by = %(requested_by)s AND status = 'pending'` in the `WHERE` clause (so editing/withdrawing someone else's request, or one already reviewed, matches zero rows and 404s rather than leaking whether the id exists); `update_announcement_group`/`delete_announcement_group` operate on the whole group at once via `execute_write_with_tenant_many`.

**tenant_admin publishing needs no approval step at all** — direct confirmation of the existing design, restated by the user: `send_announcement`/`activate_announcement` were never gated behind review for that role and still aren't.

**Frontend — moved off the bell popup onto `/announcements`, a real route** (`routeTable.ts`, `navConfig.ts` for both `tenant_admin` and `nigeria_office_staff`, `routes.tsx`'s `STAFF_SCREENS` map). `ManageAnnouncementsModal.tsx` deleted outright; its content became the new `pages/staff/AnnouncementsPage.tsx`, role-branching its entire body rather than showing/hiding a couple of buttons:
- `tenant_admin` sees "Pending approval" (unchanged Approve/Reject-with-reason) and "All announcements" — every sent announcement, each row now showing a **Publish/Unpublish button** instead of a `ToggleSwitch` (a `Badge` reading "Draft"/"Published" makes the state legible at a glance), plus inline **Edit** (title/body form) and **Delete** (click-to-arm, then Confirm) actions.
- `nigeria_office_staff` sees "My announcements" instead — every submission they've ever made, with a status `Badge` ("Pending approval"/"Approved"/"Rejected", the rejection reason shown inline when rejected) so they can see it flip to **Approved** without needing a bell notification. A still-pending one gets **Edit** and **Withdraw** actions; once reviewed, both disappear (matching the backend's `status = 'pending'` guard).
`StaffNotificationPanel.tsx` reverted to notification-only — no announcement compose/manage triggers, no `useSession()` call. `ComposeAnnouncementModal.tsx` is unchanged in role logic but its staff-facing button now reads "Submit announcement" (was "Submit for approval").

**Banner colour** — `AnnouncementBanner.tsx` switched from `variant="info"` (blue) to `variant="warning"` (amber, `--color-warning`/`--color-warning-soft`), matching `QuotaWarningBanner`'s existing "pay attention" language in this palette rather than introducing a new token; the CSS pulse-glow animation's colour was updated to match.

**Verified live**: staff submits → appears in their own "mine" list; edits it (title changes); a different real user id (not just a different header string — see the note below) 404s attempting to edit it; tenant_admin approves via the new `requests/{id}/approve` path → customer banner picks it up, requester's own list flips to "Approved". tenant_admin sends a fresh `all_staff` announcement, edits its title, confirms the edit is visible on a staff member's bell, then deletes it entirely and confirms it's gone from that same bell (not just the banner) and a repeat delete 404s. *Local-dev methodology note:* `scripts/local_server.py` resolves a non-UUID `X-User-ID` header to the tenant's single seeded user for that role, so two different fake header strings for the same role can silently resolve to the same real user — cross-user ownership checks need a fabricated real UUID (`python3 -c "import uuid; print(uuid.uuid4())"`) to actually exercise the negative case, not just any different-looking string.

Tests: `TestAnnouncementCrud` (9), `TestAnnouncementCrudHandler` (10) added to `test_staff_notifications.py`, plus 2 existing approve/reject handler tests updated for the moved paths. 805 backend tests pass. Frontend: `ManageAnnouncementsModal.tsx`/`.test.tsx`/`.module.css` deleted; new `pages/staff/AnnouncementsPage.tsx` (+`.module.css`) with `pages/staff/AnnouncementsPage.test.tsx` (15 cases); `StaffNotificationPanel.tsx` reverted (its test file dropped the `SessionContext.Provider` wrapper it no longer needs, replacing the announcement-trigger tests with one confirming those controls never render); `ComposeAnnouncementModal.test.tsx` updated for the new button label. 741 frontend tests pass. Docs: this section, `frontend/07_domain_modules.md`, `00_MASTER_PLAN.md`, `ShipX_API.postman_collection.json`.

## Notification Delivery Log

Migration 027 creates `notification_log` (RLS-enabled, tenant-scoped). Every outbound notification is persisted so the UI can show status, gateway response, and retry.

### Schema
`id, tenant_id, event_type, channel, recipient_masked, recipient_name, customer_id, status (queued|sent|delivered|read|failed), provider, provider_message_id, gateway_response JSONB, error_detail, retry_of (self-FK), template_data JSONB, created_at, updated_at`

### PII masking
- Phone: last-4 digits visible (`****6789`)
- Email: first-2 chars + `***@domain` (`ng***@gmail.com`)

### HTTP API

| Method | Path | Roles | Notes |
|---|---|---|---|
| GET | `/v1/notifications/log` | tenant_admin, nigeria_office_staff | filters: channel, status, event_type, customer_id, created_after, created_before; cursor-paginated |
| GET | `/v1/notifications/log/{id}` | tenant_admin, nigeria_office_staff | |
| POST | `/v1/notifications/log/{id}/retry` | tenant_admin | only 'failed' rows; creates new 'queued' row via retry_of; honours Idempotency-Key |

Entry point: `http_handler` in `services/notification/handler.py`.

**Deployment (corrected 2026-09-23).** Until this date no Lambda in Terraform served any `/v1/notifications/*`
route — the whole log/bell/banner/announcement surface returned 404 in AWS while working under
`scripts/local_server.py` — and the three SQS consumers were configured with a handler
(`notification.handler.lambda_handler`) that doesn't exist. Now: `http_handler` runs on the VPC-attached
`notif-api` Lambda behind 29 declared routes, `webhook_handler` on `notif-webhook` behind the public
`GET/POST /v1/webhooks/whatsapp`, and the consumers use `sms_handler` / `whatsapp_handler` / `email_handler`.
The producers' queue-URL env vars and `sqs:SendMessage` grants were also missing. Details in
`04c_terraform_api_gateway.md` and `04e_terraform_lambda_monitoring.md`. Provider credentials
(`AFRICASTALKING_*`, `META_WHATSAPP_*`, `WHATSAPP_VERIFY_TOKEN`, `SES_FROM_ADDRESS`) are read from env vars
that no Terraform sets — they must be provisioned out-of-band.

**Ground-truth gap found live (2026-09-07):** `NotificationLog.tsx`'s "Last 30 days" button was a static label with no `onClick`, and `list_logs()` had no date-filter support to back it — found while checking every page with a "calendar" filter after the same dead-UI bug was fixed on `GET /v1/billing` (row 7.63). Added `created_after`/`created_before` (ISO date, inclusive) filtering on `notification_log.created_at`. Frontend now pairs a `DateRangeFilter` preset with an exact custom From/To range via the shared `useDateRangeFilter` hook. Verified live: `created_after=2099-01-01` correctly returns 0 of the tenant's 8 log entries; `created_after=2020-01-01` returns all 8. Tests: `TestListLogsDateRangeRepository` + `TestNotificationLogHandlerDateRangeQueryParams` in `tests/unit/test_notifications.py`; new `NotificationLog.test.tsx`.

### WhatsApp delivery status webhook
`_handle_whatsapp_delivery_status` now updates `notification_log.status` by `provider_message_id` when Meta sends sent/delivered/read/failed callbacks.

## `OnboardingRequested` — shipping-company lead (2026-10-11)

`services/tenant_management/service.py::create_onboarding_request` publishes `OnboardingRequested` (source `logistics.tenant_management`, `tenant_id=PLATFORM`, payload `{request_id, company_name}`) on a public `POST /v1/onboarding-requests`. The publish is **best-effort** (wrapped in try/except; a publish failure never fails lead capture) and carries **no PII** beyond the company name — contact email/phone stay out of the event.

**Delivery status — not yet wired to a channel.** Consistent with the 2026-09-09 ground-truth above, publishing to EventBridge does **not** by itself notify anyone: there is no `OnboardingRequested` rule in `infrastructure/aws/modules/eventbridge/main.tf`, and the SQS notification pipeline is a separate system. There is also no platform-ops recipient model (the `shared/notifications.py` path is tenant/customer-scoped, and there is no tenant yet — a lead precedes any tenant). Platform admins see new leads in the **console queue** (`/platform/onboarding-requests`, GET `/v1/platform/onboarding-requests`) with a live pending-count sidebar badge; that pull-based surface is the current notification mechanism. A push channel for platform ops (email/Slack to a platform distribution list) is a deliberate follow-up, not part of this change.

## Acceptance Criteria

- [x] 3 separate Lambda handlers consuming from 3 SQS queues
- [x] SMS sends via Africa's Talking API
- [x] WhatsApp sends via Meta Cloud API with template messages
- [x] Email sends via SES with tenant-branded HTML
- [x] Tenant company name injected into all messages
- [x] Usage recorded for each sent message
- [x] Failed messages end up in DLQ after 3 retries
- [x] No VPC attachment (runs outside VPC)
- [x] `container_arrived` notification sent per customer when container reaches warehouse
- [x] `customer_registered` welcome notification sent on self-registration
- [x] `customer_invite` notification sent when a customer account-creation invite is issued (manual or auto-issued on import)
- [x] Tenant-custom templates stored in `notification_template` table (migration 024)
- [x] `GET/PUT /v1/tenant/notification-templates/{event_type}/{channel}` for template management
- [x] Custom templates embedded as `template_override` in SQS messages at enqueue time
- [x] EN/ZH locale support (migration 026 adds `tenant_user.locale`): `enqueue_notifications` accepts `locale` param; SQS body includes `locale`; SMS uses `_SMS_TEMPLATES_ZH`, WhatsApp uses `WA_TEMPLATE_MAP_ZH`, email uses `EMAIL_SUBJECTS_ZH` when `locale == 'zh'`
- [x] Notification delivery log: `notification_log` table (migration 027, RLS); every SQS send records queued→sent|failed; WhatsApp webhook updates delivered/read; `GET/POST /v1/notifications/log` HTTP API via `http_handler`; retry creates new row linked via `retry_of`


## WhatsApp-first delivery with SMS fallback (2026-09-03)

Most customers here are reached on WhatsApp, so WhatsApp is now the primary
phone channel and SMS is an exception path rather than a parallel send.

**Producer** (`shared/notifications.py::enqueue_notifications`) queues
`whatsapp` + `email` when WhatsApp can be attempted — the recipient has a
phone, the tenant has the channel enabled, and `SQS_WHATSAPP_QUEUE_URL` is set.
When it cannot be attempted it queues `sms` + `email` instead, because there is
no WhatsApp send that could later fail. **Email is unchanged** — it is a
different medium, not a worse SMS, and still follows each tenant's own
preferences.

**Fallback** (`services/notification/service.py::trigger_sms_fallback`) fires on
the two ways WhatsApp actually fails:

| Failure | Trigger point |
|---|---|
| Meta rejects the send (no WhatsApp account, bad number, template not approved) | the WhatsApp consumer's exception path |
| Meta accepts, then reports `failed` later | the delivery-status webhook |

Both call the same function, so it is **idempotent**: the fallback SMS records
the WhatsApp row it replaces in the existing `retry_of` column, and a second
attempt finds it and stops. Without that a customer with no WhatsApp account
would receive two texts.

The recipient's phone is read back from the linked `customer` record rather
than from `notification_log`, which deliberately stores only a masked contact.
The non-production recipient guard applies to fallbacks too — a dev environment
must not text a real customer just because WhatsApp failed.

### Ground-truth gap found

`send_whatsapp` returned `True` and **discarded Meta's message id**, so
`log_sent` stored an empty `provider_message_id`. The delivery-status webhook
matches rows on exactly that column, so **every `delivered` / `read` / `failed`
callback silently matched nothing** — delivery status was never recorded, and
an SMS fallback on undelivered WhatsApp could not have worked at all. It now
returns the id and the consumer stores it.

### Provider notes

WhatsApp runs on **Meta Cloud API direct** (`META_WHATSAPP_PHONE_ID`,
`META_WHATSAPP_ACCESS_TOKEN`) rather than through a BSP. Meta charges per
template message with no reseller margin, which matters most on the primary
channel; the trade is business verification and per-template approval.
SMS runs on **Africa's Talking** (`AFRICASTALKING_API_KEY`). Now that SMS is
fallback-only its volume collapses, so it is chosen for local deliverability
rather than headline price. Termii is the main Nigeria-specific alternative
(DND handling, sender-ID registration, Naira billing) if fallback delivery
proves unreliable.


## Ground-truth gaps found by draining a real notification (2026-09-06)

Running an actual queued invite through the real consumers (`scripts/drain_notifications.py`)
exposed four defects that 600 passing unit tests did not. WhatsApp-first with SMS
fallback was **entirely non-functional end to end**; every layer looked correct in
isolation.

**1. `notification_log.locale` did not exist.** `get_log_for_fallback` selected it,
so every fallback raised `UndefinedColumn` and no SMS was ever queued. Fixed by
migration 043; `log_queued` now persists the locale it was given.

**2. `customer_id` was never sent.** All three consumers read
`body.get("customer_id")`, but `enqueue_notification(s)` had no such parameter and
never wrote one — so every `notification_log` row had `customer_id = NULL`.
`trigger_sms_fallback` reads the recipient's phone from the customer record (the log
stores only a masked contact), so it could never resolve a number and gave up
silently. Both producers now accept and forward `customer_id`.

**3. Unsent messages were logged as sent and metered.** `send_sms` / `send_email`
return `False` when the provider is unconfigured or the recipient guard suppresses
them, but the handlers discarded the result and called `log_sent` plus
`record_usage` unconditionally. Staff saw a delivered invite nobody received, and
the tenant was billed for it. Both now branch on the result and record `failed`.

**4. Every WhatsApp failure looked identical.** `send_whatsapp` re-raised a bare
`HTTPError`, so `error_detail` read `"send_whatsapp raised an exception"` — an
unapproved template was indistinguishable from a wrong number or an expired token.
It now raises `WhatsAppSendError` carrying Meta's own code, e.g.
`Meta 132001: template name (customer_invite) does not exist in en_US`.

**Why the tests missed all four:** the fallback tests stub `get_log_for_fallback`
to *return* `customer_id` and `locale`, so they asserted the stub rather than the
inputs. `tests/unit/test_whatsapp_first.py` now asserts what the producer actually
enqueues and what `log_queued` actually persists, and both were verified to fail
when their fix is reverted.

### Channel selection is now in one place

`shared/notifications.py::primary_channel(tenant_id, event_type, recipient)` returns
the channel that will actually carry a message (WhatsApp when a phone and queue are
available, else SMS, else email; email always goes out alongside). It exists because
`issue_customer_invite` had its own copy — hardcoded `"sms"` — so after the switch to
WhatsApp-first every invite was reported to staff as SMS while the message went out
over WhatsApp. Anything that needs to *report* a delivery channel must call this
rather than infer one.

---

## Meta WhatsApp setup (2026-09-03)

| Variable | Meaning |
|---|---|
| `META_WHATSAPP_PHONE_ID` | The numeric **Phone number ID** from *WhatsApp → API Setup*, **not** the display number |
| `META_WHATSAPP_ACCESS_TOKEN` | Dashboard tokens expire in ~24h; production needs a System User token |
| `META_WHATSAPP_TEMPLATE_LANG` | Language code templates are approved under (default `en_US`) |
| `META_WABA_ID` | **WhatsApp Business Account ID** — template management only, not sending |

### Template creation

All eleven templates are defined in `scripts/create_wa_templates.py`, which
submits them via the Graph API and validates each body against
`WA_TEMPLATE_PARAMS` before doing so. `--status` reports Meta's review state.
Bodies, sample values, and which six are worth submitting first are in
`whatsapp_templates.md`.

The six live templates were submitted 2026-09-05 (`UTILITY`, `en_US`). Four Meta
constraints surfaced during that run — a body may not begin or end with a
variable; templates are versioned per `(name, language)` so an `en` approval is
invisible to a sender requesting `en_US`; Meta's classifier overrides the
requested category and rejected "Welcome!" phrasing as MARKETING; and a rejected
template must be edited in place rather than re-created. Full detail and the
resulting copy changes are in `whatsapp_templates.md` §"Meta constraints found
while submitting".

Meta **test numbers can only message pre-registered recipients** — add each
tester under *Manage phone number list* and accept the opt-in on the handset,
or Meta rejects the send regardless of anything in this codebase.

### Ground-truth gap found

The template language code was **hardcoded to `"en"`**. Meta approves templates
per language and the request must match exactly, so:

- Meta's own sample templates (`hello_world`, registered `en_US`) returned
  `132001 Template name does not exist in the translation`.
- `WA_TEMPLATE_MAP_ZH` existed but was **unreachable** — Chinese templates were
  always requested in English and could never resolve.

Now derived from the message locale via `wa_language_code()` (`en → en_US`,
`zh → zh_CN`), with the English default overridable per deployment.

### Local development

macOS python.org builds ship without root certificates, so the Graph API call
fails with `CERTIFICATE_VERIFY_FAILED`. `.env.local` sets `SSL_CERT_FILE` to
certifi's bundle — TLS verification in application code is never weakened.

### Recipient safety

Two independent guards, both failing closed outside production:

1. **Producer** — `enqueue_notifications` / `trigger_sms_fallback` drop
   recipients absent from `NOTIFICATION_ALLOWLIST`.
2. **Provider** — `send_whatsapp` / `send_sms` / `send_email` re-check
   immediately before the network call, so a replayed queue message or a direct
   call cannot reach a real customer either.

This matters because dev databases hold genuine customer numbers imported from
client manifests.

## Customer notification preferences — what an opt-out governs (audit SEC-01, 2026-11-15)

`customer.notification_consent` was collected and editable but never read on the send path. The policy (owner decision; ADR-006) lives in `shared/notification_consent.py`:

| Class | Events | Behaviour |
|---|---|---|
| **Account** | `account_activation`, `customer_invite`, `registration_existing_account` | Always sent. |
| **Operational** | `shipment_update`, `container_arrived`, `payment_due`, `payment_claim_confirmed/rejected`, `release_note_generated`, `packing_list_approved`, `damage_claim_update`, `cbm_dispute_update`, `customer_registered`, `storage_first_reminder`, `storage_final_reminder`, `tenant_onboarded`, `tenant_suspended` | Sent **regardless of preferences** (owner decision). |
| **Consent-bound** | none today; **any event type not listed above** | Held back for a customer whose recorded preferences exclude the channel. |

- **"Recorded" means `consent_given_at` is set.** A customer with none recorded (staff-created, manifest-imported: 23 of 23 in the dev database) is not restricted. A recorded empty list means "none". `update_customer` stamps `consent_given_at` whenever `notification_consent` is saved, whoever saves it; self-registration stamps it, and an explicitly empty choice is no longer overridden with `["email"]`.
- **Where it applies:** `enqueue_notifications` and `enqueue_notification` (`shared/notifications.py`, via `consent_verdict`) and the WhatsApp-to-SMS fallback (`trigger_sms_fallback`). A customer who agreed to SMS but not WhatsApp is texted instead of going silent.
- **Fails closed:** a consent-bound message with no `customer_id`, an unknown customer, or a failed lookup is not sent.
- **Suppressed sends are logged:** `notification_log.status = 'suppressed'` (migration 064), reason in `error_detail` (`customer has not agreed to sms`), contact masked.
- **Today this holds nothing back.** Announcements are in-app only (`staff_notification` rows, no SMS/WhatsApp/email) and there is no marketing send, so every existing event is operational or account. Moving an event type into `CONSENT_BOUND_EVENTS` is the one-line change that makes an opt-out govern it. `tests/unit/test_notification_consent.py::TestEveryEventTypeIsClassified` fails until a new event type is classified, so an unclassified type cannot slip through unbound.
- **Customer-facing copy** (Account page, registration form) now says the channel toggles cover *optional* messages, and that shipment, invoice, claim and account messages are always sent. It used to say the SMS toggle controlled "payment due, status changes, claims".

### Bugs fixed on the way

- **Duplicate emails.** `primary_channel` returns `"email"` for a recipient with no phone, so `channels = (primary, "email")` queued the same email **twice** (staff activation links, phone-less customers' invites, every notification to a recipient without a phone). Deduplicated; pinned by `TestEnqueueChannels`.
- **Missing `customer_id`.** `container_arrived` and the four scheduled customer sends (`storage_reminders`, `release_expiry`) did not pass it, which breaks the WhatsApp-to-SMS fallback (it re-reads the phone from the customer) and the log link. All pass it now.
- **New event type** `registration_existing_account`: subject, EN/ZH body and a `login_link` button label added to the notification service tables.

## Staff in-app event: `missing_item_logged` (2026-11-16)

Written by `services/claims/service.py::log_missing_item` to `staff_notification` with `target_role = china_office_staff`, `entity_type = missing_item`. In-app only (the bell); no customer data in the title or body.

## `pickup_code_issued` (2026-11-16, audit UX-09)

Sent by `services/payment_release/service.py::_issue_pickup_code` through `enqueue_notification` on **SMS and email** (no WhatsApp template exists for it). Template data: `reference_number`, `pickup_code`. Classified in `ACCOUNT_EVENTS` (always sent: without it the customer's goods cannot be collected). English and Chinese copy for SMS, email subject and email lead paragraph.

**Secrets never reach `notification_log`.** `log_queued` passes template data and the rendered body through `redact_secrets`, which masks any `_SECRET_TEMPLATE_KEYS` value (`pickup_code`) in both, so a tenant admin reading the log sees "••••••". A failed `pickup_code_issued` row **cannot be retried** (`422 NOTIFICATION_NOT_RETRYABLE`): the code is not kept, so a retry would send a mask. The remedy is to send a new code from the release note. Also new: the staff in-app event `pickup_code_locked` (to `nigeria_office_staff` and `tenant_admin`).
