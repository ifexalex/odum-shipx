/**
 * Platform security API (platform audit Phase 1): the caller's directory row, step-up re-authentication, the platform
 * admin directory and two-person approvals. Backend: services/tenant_management/{platform_admins,step_up,approvals}.py.
 */
import { apiRequest } from './client'

export type PlatformRole = 'owner' | 'admin' | 'support' | 'finance'
export type PlatformPermission = 'read' | 'tenant_lifecycle' | 'support' | 'plans' | 'settings' | 'admins' | 'approve'
export type PlatformAdminStatus = 'invited' | 'active' | 'disabled'

export interface PlatformAdmin {
  id: string
  email: string
  name: string
  role: PlatformRole
  status: PlatformAdminStatus
  last_seen_at: string | null
  disabled_at: string | null
  created_at: string
  updated_at: string
  invited_by_name: string | null
}

export interface PlatformMe extends PlatformAdmin {
  permissions: PlatformPermission[]
}

export type ApprovalAction =
  | 'offboard_tenant'
  | 'gateway_secret_change'
  | 'maintenance_on'
  | 'plan_price_change'
  | 'data_cleanup_rerun'
  | 'admin_transfer'

export type ApprovalStatus =
  | 'pending'
  | 'scheduled'
  | 'approved'
  | 'executed'
  | 'failed'
  | 'rejected'
  | 'cancelled'
  | 'expired'

export interface PlatformApproval {
  id: string
  action: ApprovalAction
  target_tenant_id: string | null
  target_tenant_name: string | null
  target_label: string
  /** What the action will do, secrets masked; `summary` is one line for people. */
  payload: { summary?: string } & Record<string, unknown>
  reason: string | null
  status: ApprovalStatus
  requested_by: string
  requested_by_name: string
  requested_at: string
  decided_by: string | null
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string | null
  expires_at: string
  /** Set when a sole admin's offboarding is waiting out its 24 hours. */
  execute_after: string | null
  executed_at: string | null
  error: string | null
}

/**
 * What a protected action (offboard, a new gateway key, maintenance on) answers with: it waits for a second admin
 * (`pending_approval`, HTTP 202), waits 24 hours (`scheduled`, 202, sole admin offboarding), or ran now (`executed`,
 * 200, sole admin) with the action's own response in `result`.
 */
export interface ProtectedOutcome<R = unknown> {
  outcome: 'pending_approval' | 'scheduled' | 'executed'
  approval: PlatformApproval
  result?: R
}

export function isProtectedOutcome(value: unknown): value is ProtectedOutcome {
  return typeof value === 'object' && value !== null && 'outcome' in value && 'approval' in value
}

/** One sentence for a toast or banner after a protected action. */
export function describeOutcome(outcome: ProtectedOutcome): string {
  if (outcome.outcome === 'pending_approval') {
    return 'Sent for approval. Another platform admin must approve it within 24 hours.'
  }
  if (outcome.outcome === 'scheduled') {
    return 'No other admin can approve this, so it runs in 24 hours. Cancel it from Approvals until then.'
  }
  return 'Done. The platform owners have been emailed, as no second admin was available.'
}

export interface StepUpInput {
  password?: string
  mfa_code?: string
  id_token?: string
}

export interface StepUpGrantResponse {
  step_up_token: string
  expires_at: number
}

export const platformSecurityApi = {
  me: () => apiRequest<PlatformMe>({ method: 'GET', path: '/v1/platform/me' }),

  stepUp: (body: StepUpInput) =>
    apiRequest<StepUpGrantResponse>({ method: 'POST', path: '/v1/platform/auth/step-up', body }),

  listAdmins: () => apiRequest<PlatformAdmin[]>({ method: 'GET', path: '/v1/platform/admins' }),

  inviteAdmin: (body: { email: string; name: string; role: PlatformRole }) =>
    apiRequest<PlatformAdmin>({ method: 'POST', path: '/v1/platform/admins', body }),

  updateAdmin: (id: string, body: { role?: PlatformRole; disabled?: boolean }) =>
    apiRequest<PlatformAdmin>({ method: 'PATCH', path: `/v1/platform/admins/${id}`, body }),

  listApprovals: (status?: 'open' | ApprovalStatus) =>
    apiRequest<PlatformApproval[]>({
      method: 'GET',
      path: '/v1/platform/approvals',
      query: status ? { status } : undefined,
    }),

  approve: (id: string, note?: string) =>
    apiRequest<{ approval: PlatformApproval; result?: unknown }>({
      method: 'POST',
      path: `/v1/platform/approvals/${id}/approve`,
      body: note ? { note } : {},
    }),

  reject: (id: string, note?: string) =>
    apiRequest<{ approval: PlatformApproval }>({
      method: 'POST',
      path: `/v1/platform/approvals/${id}/reject`,
      body: note ? { note } : {},
    }),

  cancel: (id: string, note?: string) =>
    apiRequest<{ approval: PlatformApproval }>({
      method: 'POST',
      path: `/v1/platform/approvals/${id}/cancel`,
      body: note ? { note } : {},
    }),
}
