# ShipX — Backend Gap-Closure Prompts

> **How to use this file.** Each task below is a self-contained prompt for a
> coding agent (e.g. Claude Code) running **inside the ShipX repo**. Work them in
> priority order (P0 → P1). Paste one task at a time, let the agent implement and
> verify it, run the tests, then move on. Do **not** paste all tasks at once.
>
> Names in `backticks` are **hints to confirm in the code, not facts to trust** —
> the agent should discover the real signatures, columns, and route patterns.

---

## Status — Round 1 is CLOSED ✅

A re-check of the codebase (June 2026) confirmed the four original gaps are now
implemented. **Do not rebuild these** — confirm with a quick grep and move on:

| Round 1 task | Where it landed |
|---|---|
| PDF export (packing list + release note + QR) | `services/excel/export_packing_list_pdf.py`, `export_release_note_pdf.py` |
| Notification delivery log (persist + list + retry) | migration `027_notification_log.py`, `services/notification/{repository,service,handler}.py` (`http_handler`) |
| Container document download URL | `services/tracking/{service,handler}.py` — `GET /v1/containers/{id}/documents/{doc-id}/download` |
| Platform Admin impersonation (token + session + authorizer) | migration `028_impersonation_session.py`, `services/tenant_management/impersonation.py`, `services/authorizer/handler.py` |

Also already present (never rebuild): `GET /v1/tenant/reports`,
`GET/PUT /v1/platform/settings`.

**This round (Round 2) fixes the seams the re-check found:** features that were
built but not wired end-to-end. The first one is a live security gap.

---

## Global context (paste once at the start of the session)

```
You are working in the ShipX logistics platform — a multi-tenant, serverless
(AWS Lambda + API Gateway + Postgres with row-level security) backend.

Before writing any code, read and obey these:
  - docs/project docs/00_CROSS_CUTTING_STANDARDS.md   (the binding conventions)
  - shared/  (auth.py, responses.py, exceptions.py, audit.py, db.py, and any
    pagination / idempotency / metering / tenant_context modules)
  - One existing service end-to-end as a reference, e.g. services/tracking/
    (handler.py → service.py → repository.py → models.py) and services/billing/.

Match the existing code exactly:
  - Layered structure: handler (routing + authz) → service (business logic +
    audit) → repository (parameterised SQL only) → models (Pydantic).
  - Role checks via the existing auth/context helper (confirm its name and the
    UserRole enum values before using them).
  - Every state change writes an audit record via the existing audit helper —
    confirm its exact signature first.
  - All POST/PATCH routes honour the Idempotency-Key header using the existing
    idempotency helper.
  - All errors raise the existing typed exceptions → RFC 7807 responses. Never
    invent a new error shape.
  - All SQL is parameterised. Tenant-scoped tables use the existing tenant-scoped
    DB helper so RLS is applied — confirm its name and signature.
  - New migrations follow the numbering and structure of the latest file in
    migrations/versions/ (read the highest-numbered one first).

After each task: add/extend unit tests in the matching tests/ location following
the existing style, run the suite, and confirm any new routes are registered
(API Gateway / Terraform / OpenAPI).
```

---

## P0 · Task 1 — Enforce read-only impersonation (SECURITY — do this first)

```
CONTEXT — this is a live security gap, not a feature request.

Impersonation was built (migration 028, services/tenant_management/impersonation.py,
the custom authorizer at services/authorizer/handler.py). The authorizer injects
read_only=true + impersonated_by + session_id into the request context, and
shared/auth.py populates TenantContext.read_only / .impersonated_by / .session_id.
A guard function `assert_not_read_only(ctx, method)` is defined in shared/auth.py
and RAISES IMPERSONATION_READ_ONLY on any non-GET/HEAD/OPTIONS.

THE PROBLEM: that guard has ZERO call sites. Grep the whole repo — it is never
imported or called by any write handler. So a "read-only" impersonation session
can currently POST/PATCH/DELETE freely: alter billing, approve refunds, change
config, update statuses. PRD Q12's core safety property is unenforced. (The docs
in 07_api_tenant_management.md even mark this [x] complete — that checkbox is
wrong; fix it too.)

GOAL: make impersonation actually read-only at runtime, in a way no future
handler can forget.

Do this:
  1. Confirm the exact guard signature in shared/auth.py (assert_not_read_only)
     and how each service handler determines the HTTP method and builds its
     TenantContext.
  2. Enforce it in ONE central place rather than sprinkling calls. Strongly prefer
     a single chokepoint:
       - If handlers share a common dispatch/router or a get_tenant_context() call
         path, invoke the guard there so every mutating request is covered
         automatically; OR
       - add a tiny decorator/wrapper that every service handler's entry point
         already uses, and put the guard inside it.
     Whichever you choose, the requirement is: ANY non-GET/HEAD/OPTIONS request
     carrying read_only=true is rejected with the existing IMPERSONATION_READ_ONLY
     error (403) BEFORE it reaches business logic — across tracking, billing,
     claims, refunds, packing_list, manifest, payment_release, and the
     tenant_management write routes.
  3. Make sure genuinely public/no-JWT routes (payment + whatsapp webhooks,
     public tracking, customer self-registration) are unaffected.
  4. Fix the stale [x] in docs/project docs/07_api_tenant_management.md.

Tests (required):
  - An impersonation-context request to a representative write route in EACH
    service returns 403 IMPERSONATION_READ_ONLY.
  - The same route works normally for a non-impersonated user.
  - GET routes still work under impersonation (read-only browsing is the point).
  - A regression test that FAILS if a new write route bypasses the chokepoint
    (e.g. assert the guard is invoked on a sampled mutating path).

Deliver as its own PR titled "fix(security): enforce read-only impersonation".
```

---

## P1 · Task 2 — Webhook config save endpoint

```
GOAL: let a Tenant Admin save outbound-webhook settings. The outbound webhook
already FIRES (shared webhook helper, called from tracking) and webhook_config is
seeded in DEFAULT_CONFIGS — but there is no way to configure it. UpdateTenant-
ConfigRequest accepts only `branding` and `notification_preferences`, and
update_tenant_config() persists only those, so the Webhook config screen (design
Section 16.6) has no endpoint to call.

Confirm first:
  - The webhook_config shape in DEFAULT_CONFIGS (services/tenant_management/
    service.py) — URL, secret, enabled flag, events list, header name.
  - How update_tenant_config() + repo.upsert_config() persist a config key.
  - The events the outbound webhook can fire (grep the webhook helper for the
    event names it emits, e.g. container.status_updated) so the events list is
    validated against a real enum, not free text.

Implement:
  1. Extend UpdateTenantConfigRequest (models.py) with an optional `webhook_config`
     object: endpoint_url (validated https URL), enabled (bool), events (list,
     validated against the known event enum). Do NOT accept the secret as plain
     client input on every update — generate/rotate it server-side (see below).
  2. Persist webhook_config in update_tenant_config() via upsert_config(), and
     audit the change (entity_type tenant_config).
  3. Secret handling: add a rotate action (POST /v1/tenant/config/webhook/rotate-
     secret or similar, tenant_admin) that generates a new signing secret, stores
     it, and returns it ONCE. Reads of the config must return the secret masked.
  4. Test-fire: add POST /v1/tenant/config/webhook/test (tenant_admin) that sends a
     signed sample payload to the configured URL using the SAME signing path as
     real events, and returns the delivery result (status code / error). This backs
     the screen's "Send test event" button.

Roles: tenant_admin only. Honour Idempotency-Key on POSTs. Add tests for
validation (bad URL / unknown event rejected), persistence, secret masking on read,
and rotate returning a fresh secret.
```

---

## P1 · Task 3 — Staff locale (EN/ZH) write path

```
GOAL: make tenant_user.locale settable so the EN/ZH notification feature actually
works. Migration 026 added tenant_user.locale and the notification stack fully
honours it (enqueue_notifications passes locale through SQS; SMS/WhatsApp/email
handlers select ZH templates when locale == 'zh'). But update_user() whitelists
only ("full_name", "role"), so locale can never be written — every user is stuck
at the 'en' default and the Locale Preference screen (Section 16.11) has nothing
to PATCH.

Confirm first:
  - update_user() in services/tenant_management/{handler,service,repository}.py and
    the field-whitelist in the handler (currently {k: v ... if k in
    ("full_name","role")}).
  - locale is settable for STAFF only (tenant_user). Customer locale is determined
    by LOCATION, not chosen — do NOT add a customer language setter (see Task 4).
  - CRITICAL downstream check: trace the notification CALLERS (e.g. tracking's
    container_arrived enqueue, scheduled jobs, tenant_management welcome). Confirm
    they look up the recipient's locale from the DB and pass it into
    enqueue_notifications. If they don't, locale stays 'en' even once settable —
    fix the callers to read and forward the recipient's locale.

Implement:
  1. Add `locale` to the permitted update_user fields, validated against an enum
     of supported locales (currently 'en','zh' — confirm the exact set the
     notification service supports; reject anything else with VALIDATION_ERROR).
  2. Persist via repo.update_user(); audit the change. locale is NOT a Cognito
     attribute — do not push it to Cognito (only full_name/role sync there).
  3. Do NOT add a customer-facing language setter — customer locale is
     location-derived (see Task 4).
  4. Fix any notification callers that don't currently forward recipient locale.

Roles: a user may set their own locale; tenant_admin may set any user's in their
tenant (match existing update_user authz). Add tests: locale persists, invalid
locale rejected, and a notification enqueued for a zh user carries locale='zh'.
```

---

## P1 · Task 4 — Forward recipient locale from scheduled-job notifications

```
GOAL: make EN/ZH localization actually reach recipients of SCHEDULED notifications.
Task 3 added the locale write path, and the tracking service forwards it correctly
(services/tracking/service.py passes locale=customer.get("locale","en") into
enqueue_notifications). But the scheduled jobs do NOT — they call
enqueue_notification(...) WITHOUT a locale arg, and their recipient-lookup queries
don't even SELECT the locale column. So every scheduled notification goes out in
English regardless of the recipient's setting.

Confirmed facts (verify, then fix):
  - Migration 026 added locale to BOTH tenant_user AND customer.
  - shared notifications helper: enqueue_notification(...) accepts a locale param
    (enqueue_notifications — plural — already takes locale=; confirm the singular
    signature and add the param if missing). The SQS consumers already read
    body["locale"] and pick the ZH template when locale == "zh".
  - These callers are missing it:
      services/scheduled/storage_reminders.py  (customer-facing — _get_customer_contact
          selects only c.id, u.email, u.phone_number; no c.locale; enqueue has no locale)
      services/scheduled/release_expiry.py      (customer-facing — same pattern)
      services/scheduled/dispute_escalation.py  (staff-facing — selects tu.email,
          tu.phone_number from tenant_user; no tu.locale)
      services/scheduled/sla_check.py           (staff-facing — same pattern)

Implement, in each of the four jobs:
  1. Add the locale column to the recipient-lookup SELECT (c.locale for customers,
     tu.locale for staff).
  2. Pass locale=<looked-up value, default 'en'> into every enqueue_notification call.
  3. Where a job notifies both a customer and staff, use the RIGHT locale for each
     recipient (don't reuse the customer's locale for the staff alert).

Tests: a scheduled notification for a zh recipient enqueues an SQS message with
locale='zh'; an en recipient still gets 'en'. Add a regression check that the
recipient-lookup queries include the locale column.
```

```
WHILE YOU'RE HERE — customer locale is DETERMINED BY LOCATION, not user-settable.
Do NOT add a customer self-service language setting. Customers never choose their
language in the UI; it is derived from their location/region. Confirm where the
customer's locale is populated (e.g. at registration from country/region, or a
mapping in the customer service) and ensure customer.locale is set there. The four
scheduled jobs below must READ that pre-determined customer.locale and forward it —
they must not expose any setter. (Staff locale, by contrast, IS self-service via
Task 3 / PATCH /v1/tenant/me.)
```

---

## Frontend dependency (handled in the design files, not here)

```
Task 1 (read-only enforcement) needs a matching UI so platform admins can SEE and
EXIT an impersonated session. That screen is built in the design set
(Section 16.13 — Impersonation read-only banner): sticky banner, 30-min session
countdown, "Exit impersonation" calling DELETE /v1/platform/impersonation/{id},
and disabled mutating controls. No backend work beyond Task 1 — but the app needs
to read the current impersonation state. Easiest: decode the impersonation token
claims client-side (impersonated_by / read_only / exp). If you prefer a server
echo, add a tiny GET /v1/session that returns the current context (sub, role,
impersonated_by, read_only, expires_at) — implement it as a trivial read in
tenant_management if the frontend team requests it.
```

---

## Notes for the agent

```
- Order: Task 1 (P0, security) FIRST and on its own PR. Then Task 2 and Task 3.
- Round 1 is done — confirm-by-grep, never rebuild (see the Status table above).
- If any assumption here conflicts with the code, the CODE wins — adapt and note
  the deviation in your PR description.
- Keep each task on its own branch/PR for reviewability.
```
