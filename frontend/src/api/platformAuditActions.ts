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
] as const

export type PlatformAuditAction = (typeof PLATFORM_AUDIT_ACTIONS)[number]
