import type { UserRole } from '../auth/types'
import type { Claim } from './claims'

const _INSPECT_ROLES: UserRole[] = ['nigeria_office_staff']
const _RESOLVE_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _FILE_CLAIM_ROLES: UserRole[] = ['nigeria_office_staff', 'customer']
const _ITEM_WRITE_ROLES: UserRole[] = ['nigeria_office_staff']

export function canStartInspection(claim: Claim, role: UserRole): boolean {
  return _INSPECT_ROLES.includes(role) && claim.status === 'filed'
}

export function canResolveClaim(claim: Claim, role: UserRole): boolean {
  const resolvable: Claim['status'][] = ['under_inspection', 'inspection_complete', 'pending_resolution']
  return _RESOLVE_ROLES.includes(role) && resolvable.includes(claim.status)
}

export function canFileClaim(role: UserRole): boolean {
  return _FILE_CLAIM_ROLES.includes(role)
}

export function canUpdateItem(role: UserRole): boolean {
  return _ITEM_WRITE_ROLES.includes(role)
}

export function isTerminalClaimStatus(status: Claim['status']): boolean {
  return status === 'resolved' || status === 'closed'
}

export const CLAIM_STATUS_ORDER: Claim['status'][] = [
  'filed',
  'under_inspection',
  'inspection_complete',
  'pending_resolution',
  'resolved',
  'closed',
]
