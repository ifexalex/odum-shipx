/**
 * Every `action` the backend writes to `platform_audit_log` — the same list as `PlatformAuditAction` in
 * shared/platform_audit.py. tests/unit/test_platform_audit_actions.py fails when the two differ, so the audit log's
 * action filter never offers a value that matches nothing (audit PA-05).
 */
export const PLATFORM_AUDIT_ACTIONS = [
  'TENANT_CREATED',
  'TENANT_UPDATED',
  'TENANT_SUSPENDED',
  'TENANT_ACTIVATED',
  'TENANT_OFFBOARDED',
  'TENANT_REACTIVATED',
  'TENANT_EXPORT_QUEUED',
  'TENANT_DATA_EXPORTED',
  'TENANT_EXPORT_LINK_ISSUED',
  'IMPERSONATION_START',
  'IMPERSONATION_END',
  'QUOTA_OVERRIDE_SET',
  'QUOTA_OVERRIDE_CLEARED',
  'PLAN_LIMITS_UPDATED',
  'SETTINGS_UPDATED',
  'GATEWAY_SETTINGS_UPDATED',
  'ONBOARDING_REQUEST_UPDATED',
  'PLATFORM_ADMIN_ENROLLED',
  'PLATFORM_ADMIN_INVITED',
  'PLATFORM_ADMIN_ROLE_CHANGED',
  'PLATFORM_ADMIN_DISABLED',
  'PLATFORM_ADMIN_ENABLED',
  'STEP_UP_VERIFIED',
  'APPROVAL_REQUESTED',
  'APPROVAL_APPROVED',
  'APPROVAL_REJECTED',
  'APPROVAL_CANCELLED',
  'APPROVAL_SCHEDULED',
  'APPROVAL_EXECUTED',
  'APPROVAL_FAILED',
  'APPROVAL_EXPIRED',
] as const

export type PlatformAuditAction = (typeof PLATFORM_AUDIT_ACTIONS)[number]
