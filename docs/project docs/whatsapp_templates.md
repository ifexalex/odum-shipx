# WhatsApp Message Templates (Meta Cloud API)

Every WhatsApp message ShipX sends is a **template message** — Meta does not
allow free-form text outside a 24-hour customer-service window. Each template
must be created and approved in the Meta dashboard *before* the matching event
can send.

## The parameter contract — read this first

`services/notification/service.py::build_wa_components` builds the body params:

```
{{1}}  = company name   (always, from tenant branding)
{{2}}… = the keys declared for that event in WA_TEMPLATE_PARAMS, in order
```

`WA_TEMPLATE_PARAMS` is the authority — it names exactly which `template_data`
keys fill which placeholder, so the count is a property of the template rather
than of whatever a caller happened to pass. Meta allows 5 body parameters, so
each template may declare at most 4 keys.

**The placeholder count must match exactly.** If a template declares `{{1}} {{2}}`
but the code sends three values, Meta rejects the send with
`132000 number of parameters does not match`. This couples each template to its
call site — see "Fragility" at the bottom.

Create every template with:

- **Category:** `UTILITY` (these are transactional. Do not use MARKETING —
  it costs more and is subject to per-user marketing limits.)
- **Language:** `English (US)` → code `en_US`, matching
  `META_WHATSAPP_TEMPLATE_LANG`.

---

## 1. `customer_invite` — the one currently in use

**Template name:** `customer_invite`
**Params:** 3 — company, customer name, invite link

**Body:**
```
Hello {{2}}, {{1}} has created an account for you to track your shipments.

Tap here to create your account: {{3}}

This link expires in 48 hours. If it expires, contact {{1}} for a new one.
```

**Sample values for Meta's approval form:**

| Placeholder | Sample |
|---|---|
| `{{1}}` | Acme Shipping Ltd |
| `{{2}}` | Ifesinachi Ugwuoke |
| `{{3}}` | https://app.shipx.com/invite/3f9a2b7c1d |

> Meta reviewers reject templates whose samples look like placeholders. Use a
> realistic company name and a real-looking URL.

---

## 2. Remaining templates

Param counts below are derived from each event's SMS template
(`_SMS_TEMPLATES`). Those marked **inferred** have no confirmed call site yet —
verify the actual `template_data` before relying on them.

| Event | Meta template name | Params | `{{2}}`… are |
|---|---|---|---|
| `shipment_update` | `shipment_status_update` | 3 | `tracking_code`, `status` |
| `payment_due` | `payment_due_notification` | 5 | `container_number`, `currency`, `amount`, `warehouse_address` |
| `release_note_generated` | `release_note_ready` | 3 | `reference_number`, `carton_count` |
| `damage_claim_update` | `damage_claim_update` | 3 | `claim_reference`, `status` |
| `cbm_dispute_update` | `cbm_dispute_update` | 3 | `reference_number`, `status` |
| `packing_list_approved` | `packing_list_approved` | 2 | `reference` |
| `tenant_onboarded` | `tenant_welcome` | 2 | `company_name` |
| `tenant_suspended` | `tenant_suspended` | 2 | `reason` |
| `container_arrived` | `container_arrived_warehouse` | 2 | `container_number` |
| `customer_registered` | `customer_welcome` | 2 | `name` |
| `customer_invite` | `customer_invite` | 3 | `name`, `invite_link` |

**`customer_welcome`** (2 params)
```
Your {{1}} account has been created, {{2}}. Check your email to set your password and start tracking your shipments.
```

**`container_arrived_warehouse`** (2 params)
```
Your container {{2}} has arrived at the {{1}} warehouse. We will contact you when your goods are ready for collection.
```

**`shipment_status_update`** (3 params)
```
Shipment update from {{1}}: your shipment {{2}} is now {{3}}. Reply to this message if you have any questions.
```

**`release_note_ready`** (3 params)
```
Your release note from {{1}} is ready. Reference {{2}} — please collect {{3}} carton(s) from our warehouse.
```

**`payment_due_notification`** (5 params)
```
Payment is due on your shipment with {{1}}. Container {{2}} has arrived. Amount due: {{3}} {{4}}. Collect your goods from {{5}} once payment is confirmed.
```

**`damage_claim_update`** (3 params)
```
Update from {{1}} on your damage claim {{2}}: the status is now {{3}}. Reply here if you have questions.
```

**`cbm_dispute_update`** (3 params)
```
Your CBM dispute {{2}} with {{1}} has been updated. Status: {{3}}. Reply here if you have questions.
```

**`packing_list_approved`** (2 params)
```
Your packing list {{2}} has been approved by {{1}} and added to a container.
```

**`tenant_welcome`** (2 params) — sent to the shipping company, not their customers
```
Welcome to {{1}}. Your account for {{2}} is active and ready to use.
```

**`tenant_suspended`** (2 params) — sent to the shipping company, not their customers
```
Your {{1}} account has been suspended. Reason: {{2}}. Contact support to restore access.
```

---

## Which to create first

You do not need all eleven to start.

**Create now — customer-facing, in the live flow:**
`customer_invite`, `customer_welcome`, `container_arrived_warehouse`,
`payment_due_notification`, `release_note_ready`, `shipment_status_update`

**Create later — features not yet fully wired:**
`damage_claim_update`, `cbm_dispute_update`, `packing_list_approved`

**Reconsider before creating:** `tenant_welcome` and `tenant_suspended` go to the
**shipping company**, not to a customer. Reaching a business on WhatsApp with an
account-status notice is a different decision from messaging a consignee about
cargo — email may suit these better. Nothing sends them today.

## Related gap: five events have no SMS text either

`_SMS_TEMPLATES` only covers the six customer-facing events. The other five fall
back to `_DEFAULT_SMS_TEMPLATE` — *"You have a new notification."* — which tells
the recipient nothing. If any of those events starts firing, its SMS needs real
copy as well as a WhatsApp template.

---

## Creating them — `scripts/create_wa_templates.py`

The bodies above are also embedded in `scripts/create_wa_templates.py`, which
submits them to Meta via the Graph API rather than through the dashboard form.
Before submitting anything it checks every body's placeholder count against
`WA_TEMPLATE_PARAMS`, so a template cannot be created in a shape the sender
would violate at runtime. It skips templates that already exist, so it is safe
to re-run.

```bash
export META_WABA_ID=...                  # WhatsApp Business Account ID
export META_WHATSAPP_ACCESS_TOKEN=...    # needs whatsapp_business_management

python3 scripts/create_wa_templates.py --status             # review status, submits nothing
python3 scripts/create_wa_templates.py --priority           # dry run, the 6 live ones
python3 scripts/create_wa_templates.py --priority --apply   # submit them
python3 scripts/create_wa_templates.py --apply              # submit all 11
```

`META_WABA_ID` is **not** the Phone number ID already in `.env.local`. Find it in
Meta Business Suite → WhatsApp Accounts, or at the top of the API Setup page.

A user access token expires in about an hour. For repeat use, create a **System
User** token (Business Settings → System Users) with the
`whatsapp_business_management` and `whatsapp_business_messaging` scopes and no
expiry.

---

## Meta constraints found while submitting (2026-09-05)

Four rules that are not obvious from the docs, each of which cost a round trip:

**1. A body may not start or end with a variable.**
`{{1}}: Container {{2}} has arrived…` is rejected with
`2388299 Leading or trailing params not allowed`. Since `{{1}}` is always the
company name, the natural `{{1}}: …` prefix is unusable — every body now opens
with a real word. The script enforces this locally before submitting, and
conservatively also rejects a body ending in a variable plus punctuation.

**2. Templates are versioned per `(name, language)`, not per name.**
`customer_invite` was already APPROVED under `en`, but `wa_language_code()`
requests `en_US`, so a send would have failed with `132001 Template name does not
exist in the translation` despite the dashboard showing it approved. The script
keys on the pair and reports names that exist only in another language.

**3. Meta's classifier overrides the requested category.**
`customer_invite` and `customer_welcome` were rejected `INCORRECT_CATEGORY` —
"Welcome!" and activation phrasing read as MARKETING. Restating them as plain
account transactions ("Your {{1}} account has been created…") passed. MARKETING
costs more per message and is subject to per-user marketing limits, so the
wording is worth keeping transactional.

**4. A rejected template must be edited, not re-created.**
`(name, language)` is unique, so resubmission is `POST /{template_id}`, which the
script does automatically when it finds a REJECTED template.

> Do **not** delete a template to recreate it — Meta blocks reuse of a deleted
> template's name for 4 weeks.

---

## Adding or changing a template

1. Add or edit the event's entry in `WA_TEMPLATE_MAP` (Meta template name) and
   `WA_TEMPLATE_PARAMS` (its ordered keys) in
   `services/notification/service.py`.
2. Add its body and sample values to `BODIES` in
   `scripts/create_wa_templates.py` with **exactly** `1 + len(keys)`
   placeholders — the script refuses to submit a mismatch, and Meta would
   otherwise reject the send at runtime with `132000`.
3. Run the script to create it, and update the table above.

A test asserts every entry in `WA_TEMPLATE_MAP` has a `WA_TEMPLATE_PARAMS`
declaration and that none exceeds Meta's 5-parameter budget, so a new event
cannot silently fall back to fragile ordering.

> **Previously** the code sent `template_data.values()` in dict insertion order.
> Adding a key to any `template_data` dict silently broke that event's WhatsApp
> send (Meta `132000`) while SMS and email kept working, and reordering keys
> silently swapped values between placeholders — a wrong message to a customer
> with no error at all. Parameters are now declared per template.

## Testing before customers see it

Meta test numbers only deliver to recipients registered under *Manage phone
number list*. Combined with `NOTIFICATION_ALLOWLIST` (see
`15_api_notifications.md`), a template can be exercised end to end without any
real customer being reachable.
