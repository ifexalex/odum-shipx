import type { UserRole } from '../auth/types'
import type { Billing, CBMDispute } from './billing'

const _PAYMENT_RECORD_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _CANCEL_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _CARRYOVER_APPLY_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _ACKNOWLEDGE_ROLES: UserRole[] = ['nigeria_office_staff']
const _DISPUTE_RESOLVE_ROLES: UserRole[] = ['nigeria_office_staff', 'china_office_staff', 'tenant_admin']

export function canRecordPayment(billing: Billing, role: UserRole): boolean {
  return (
    _PAYMENT_RECORD_ROLES.includes(role) &&
    (billing.payment_status === 'unpaid' || billing.payment_status === 'partially_paid')
  )
}

export function canCancelBilling(billing: Billing, role: UserRole): boolean {
  return (
    _CANCEL_ROLES.includes(role) &&
    (billing.payment_status === 'unpaid' || billing.payment_status === 'partially_paid')
  )
}

export function canApplyCarryover(billing: Billing, role: UserRole): boolean {
  return (
    _CARRYOVER_APPLY_ROLES.includes(role) &&
    billing.payment_status !== 'cancelled' &&
    billing.payment_status !== 'waived'
  )
}

export function canAcknowledgeDispute(dispute: CBMDispute, role: UserRole): boolean {
  return _ACKNOWLEDGE_ROLES.includes(role) && dispute.status === 'submitted'
}

export function canResolveDispute(dispute: CBMDispute, role: UserRole): boolean {
  const resolvableStatuses = ['submitted', 'acknowledged', 'investigating', 'escalated_china']
  return _DISPUTE_RESOLVE_ROLES.includes(role) && resolvableStatuses.includes(dispute.status)
}

export function canRejectDispute(dispute: CBMDispute, role: UserRole): boolean {
  return canResolveDispute(dispute, role)
}

export function isTerminalDisputeStatus(status: CBMDispute['status']): boolean {
  return status === 'resolved_adjusted' || status === 'resolved_no_change' || status === 'closed'
}
