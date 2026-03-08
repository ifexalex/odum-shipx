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
├── handler.py           # 3 handlers: sms_handler, whatsapp_handler, email_handler
├── service.py           # Channel-specific sending logic
├── tenant_branding.py   # Extract tenant branding from event payload
└── models.py
```

## SQS Event Format

Each SQS message body contains:
```json
{
  "tenant_id": "uuid",
  "event_type": "ShipmentStatusUpdated",
  "channel": "sms",
  "recipient": {
    "phone": "+2348012345678",
    "email": "customer@example.com",
    "name": "John Doe"
  },
  "tenant_branding": {
    "company_name": "Acme Shipping",
    "primary_color": "#1A5276"
  },
  "template_data": {
    "tracking_code": "ACME-TRK-20260215-0001",
    "status": "arrived_nigeria",
    "container_number": "MSKU1234567",
    "amount": "166,310.00",
    "currency": "NGN",
    "warehouse_address": "12 Warehouse Road, Apapa, Lagos",
    "reference_number": "ACME-RN-20260301-0012"
  }
}
```

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

- Use `boto3` SES client
- HTML email templates with tenant branding (company name, color)
- Events that trigger email: packing_list_approved, release_note_generated, damage_claim_filed, tenant_onboarded
- From address: `notifications@logistics.example.com` (or tenant-specific in future)
- Cost tracking: publish `UsageRecorded` event (metric_type = 'emails_sent')

## Tenant Notification Preferences

The publishing service checks `tenant.notification_preferences` before enqueueing. If a channel is disabled for that event type, no SQS message is sent. The notification Lambda does NOT need to re-check.

## Error Handling

- Invalid phone/email → log warning, message goes to DLQ after 3 retries
- External API failure (Africa's Talking down) → SQS retry with backoff
- DLQ messages: CloudWatch alarm triggers when DLQ has > 0 messages

## Acceptance Criteria

- [x] 3 separate Lambda handlers consuming from 3 SQS queues
- [x] SMS sends via Africa's Talking API
- [x] WhatsApp sends via Meta Cloud API with template messages
- [x] Email sends via SES with tenant-branded HTML
- [x] Tenant company name injected into all messages
- [x] Usage recorded for each sent message
- [x] Failed messages end up in DLQ after 3 retries
- [x] No VPC attachment (runs outside VPC)
