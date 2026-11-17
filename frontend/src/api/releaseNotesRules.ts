import type { UserRole } from '../auth/types'
import type { ReleaseNote, ReleaseNoteStatus } from './releaseNotes'

const _CREATE_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _SPLIT_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const _PICKUP_ROLES: UserRole[] = ['warehouse_attendant']

export function isTerminalReleaseStatus(status: ReleaseNoteStatus): boolean {
  return status === 'picked_up' || status === 'expired' || status === 'cancelled'
}

export function canCreateReleaseNote(role: UserRole): boolean {
  return _CREATE_ROLES.includes(role)
}

export function canRecordPickup(note: ReleaseNote, role: UserRole): boolean {
  return _PICKUP_ROLES.includes(role) && note.status === 'active'
}

export function canSplitNote(note: ReleaseNote, role: UserRole): boolean {
  return _SPLIT_ROLES.includes(role) && note.status === 'active'
}

/** Staff who issue release notes can send the customer a new pickup code for an active one. */
export function canSendPickupCode(note: ReleaseNote, role: UserRole): boolean {
  return _CREATE_ROLES.includes(role) && note.status === 'active'
}

/** "SMS and email" from the channel names the API reports a code was sent on. */
export function sentViaLabel(channels: string[]): string {
  const names = channels.map((c) => (c === 'sms' ? 'SMS' : c === 'whatsapp' ? 'WhatsApp' : c))
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : (names[0] ?? '')
}

export function releaseNoteStatusLabel(status: ReleaseNoteStatus): string {
  switch (status) {
    case 'active': return 'Active'
    case 'picked_up': return 'Picked up'
    case 'expired': return 'Expired'
    case 'cancelled': return 'Cancelled'
  }
}

export function releaseTypeLabel(note: ReleaseNote): string {
  return note.is_partial_release ? 'Partial release' : 'Full release'
}
