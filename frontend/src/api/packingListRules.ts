import type { UserRole } from '../auth/types'
import type { PackingList } from './packingList'

// Ground truth: services/packing_list/service.py — draft -> pending_approval
// -> approved, or pending_approval -> rejected -> draft (revision cycle).
// Approval is restricted to china_office_staff/tenant_admin and blocked
// when the actor is also the creator (self-approval prevention).
const APPROVER_ROLES: UserRole[] = ['china_office_staff', 'tenant_admin']

export function canEditPackingList(pl: PackingList): boolean {
  return pl.status === 'draft' || pl.status === 'rejected'
}

export function canSubmitForApproval(pl: PackingList): boolean {
  return pl.status === 'draft' && pl.items.length > 0
}

export function isSelfApproval(pl: PackingList, userId: string): boolean {
  return pl.created_by != null && String(pl.created_by) === String(userId)
}

export function canApproveOrReject(pl: PackingList, role: UserRole, userId: string): boolean {
  if (pl.status !== 'pending_approval') return false
  if (!APPROVER_ROLES.includes(role)) return false
  return !isSelfApproval(pl, userId)
}

export function totalDeclaredValueUsd(pl: PackingList): number {
  return pl.items.reduce((sum, item) => sum + Number(item.declared_value_usd ?? 0), 0)
}

/** L x W x H in cm, computed client-side for live preview before the server assigns the persisted value. */
export function computeCbm(lengthCm: number, widthCm: number, heightCm: number): number {
  return (lengthCm * widthCm * heightCm) / 1_000_000
}

/** Bales at/above this CBM are "big", below are "small" — mirrors the backend. */
export const BIG_BALE_CBM = 0.3

/** Abbreviated bale-size label for a bale line item. */
export function baleSizeAbbr(cbm: number): 'BIG BALE' | 'SM BALE' {
  return cbm >= BIG_BALE_CBM ? 'BIG BALE' : 'SM BALE'
}

/** Floor a line-item CBM at the tenant minimum — mirrors the backend so the
 *  wizard shows the value that will actually be stored/billed. */
export function applyMinCbm(cbm: number, minCbm: number): number {
  return Math.max(cbm, minCbm)
}

/**
 * Plain-language explanation of a bulk-action failure reason.
 *
 * The API returns machine codes (`self_approval_forbidden`, `wrong_status:draft`).
 * Those are precise for a developer and meaningless to the warehouse or office
 * staff actually doing the work, so every code is translated here into what
 * happened and what to do next. Unknown codes fall back to the raw value rather
 * than being hidden — a code on screen is bad, a silently swallowed failure is
 * worse.
 */
export interface BulkFailureExplanation {
  title: string
  help: string
}

export function explainBulkFailure(reason: string): BulkFailureExplanation {
  if (reason === 'self_approval_forbidden') {
    return {
      title: 'You created these, so you cannot approve them',
      help:
        'Packing lists have to be checked by someone other than the person who added them. ' +
        'Ask a colleague or your admin to approve these.',
    }
  }
  if (reason === 'not_found') {
    return {
      title: 'No longer available',
      help: 'These were deleted or moved while the page was open. Refresh and try again.',
    }
  }
  if (reason.startsWith('wrong_status:')) {
    const status = reason.slice('wrong_status:'.length)
    const byStatus: Record<string, BulkFailureExplanation> = {
      draft: {
        title: 'Still drafts',
        help: 'Select them and use "Submit for approval" first, then approve.',
      },
      pending_approval: {
        title: 'Already waiting for approval',
        help: 'These have been submitted already — they just need approving.',
      },
      approved: {
        title: 'Already approved',
        help: 'Nothing to do — these were approved earlier.',
      },
      rejected: {
        title: 'Previously rejected',
        help: 'Open each one to fix the problem and submit it again.',
      },
    }
    return (
      byStatus[status] ?? {
        title: `Not in the right state (${status})`,
        help: 'These are at a stage where this action does not apply.',
      }
    )
  }
  return { title: reason, help: 'This action could not be applied to these packing lists.' }
}

/** Group bulk failures by reason so one cause is reported once, not per row. */
export function groupBulkFailures<T extends { id: string; reason: string }>(
  failures: T[],
): { reason: string; ids: string[] }[] {
  const byReason = new Map<string, string[]>()
  for (const failure of failures) {
    const ids = byReason.get(failure.reason) ?? []
    ids.push(failure.id)
    byReason.set(failure.reason, ids)
  }
  return [...byReason.entries()].map(([reason, ids]) => ({ reason, ids }))
}

/**
 * Package quantities keyed by normalised unit, e.g. `{ bale: 2, bag: 16 }`.
 * Comes from the packing-list list endpoint's `package_mix`.
 */
export type PackageMix = Record<string, number>

const UNIT_LABELS: Record<string, [singular: string, plural: string]> = {
  bale: ['bale', 'bales'],
  carton: ['carton', 'cartons'],
  bag: ['bag', 'bags'],
  pallet: ['pallet', 'pallets'],
  package: ['package', 'packages'],
  mixed: ['mixed parcel', 'mixed parcels'],
  unspecified: ['item', 'items'],
}

export function formatPackageUnit(unit: string | null | undefined, count: number): string {
  const [singular, plural] = UNIT_LABELS[unit ?? 'unspecified'] ?? [
    unit ?? 'item',
    `${unit ?? 'item'}s`,
  ]
  return `${count} ${count === 1 ? singular : plural}`
}

/**
 * Human summary of a package mix, largest group first — "16 bags · 2 bales".
 *
 * Staff need to see at a glance whether a list is bales or cartons: a bare
 * count cannot say, and since a row became a bulk quantity (migration 040) the
 * row count is not the package count either.
 */
export function formatPackageMix(mix: PackageMix | null | undefined): string {
  const entries = Object.entries(mix ?? {}).filter(([, count]) => count > 0)
  if (entries.length === 0) return '—'
  entries.sort((a, b) => b[1] - a[1])
  return entries.map(([unit, count]) => formatPackageUnit(unit, count)).join(' · ')
}

/** The single dominant unit in a mix, or null when it is genuinely mixed. */
export function dominantPackageUnit(mix: PackageMix | null | undefined): string | null {
  const units = Object.entries(mix ?? {}).filter(([, count]) => count > 0)
  return units.length === 1 ? units[0]![0] : null
}
