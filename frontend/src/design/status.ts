/**
 * The status registry (FD-08): every status of every record type, with the words staff see, the words a customer
 * sees, and the badge colour. Pages never define their own status map: they render `<StatusBadge kind status />`,
 * or call `statusLabel` where they need the words alone (a filter chip, a select option).
 *
 * Colours follow one rule, so the same kind of state looks the same everywhere:
 *   neutral  — not started, or finished with nothing to do (draft, closed, cancelled, picked up)
 *   info     — moving along; nobody needs to act (sealed, in transit, under inspection)
 *   warning  — waiting on someone (unpaid in part, pending approval, at customs)
 *   success  — done, in the customer's or the tenant's favour (paid, approved, delivered)
 *   error    — refused, failed or lost (rejected, expired, seized)
 *   primary  — a container on Nigerian soil and through customs (cleared, at warehouse): the brand's own stage
 *
 * `customer` is set where a customer should read different words from staff; otherwise both read `label`.
 * `statusRegistry.test.ts` checks every API status union is covered and that no page keeps its own map.
 */
import type { CarryoverStatus, CBMDisputeStatus, PaymentClaimStatus, PaymentStatus } from '../api/billing'
import type { DamageClaimStatus, MissingItemStatus, SeizedItemStatus } from '../api/claims'
import type { VerificationStatus } from '../api/manifest'
import type { NotifStatus } from '../api/notifications'
import type { PackingListStatus } from '../api/packingList'
import type { RefundStatus } from '../api/refunds'
import type { ReleaseNoteStatus } from '../api/releaseNotes'
import type { ApprovalStatus, PlatformAdminStatus } from '../api/platformSecurity'
import type { OffboardingExportStatus, OnboardingRequestStatus, TenantStatus } from '../api/tenantManagement'
import type { ContainerStatus } from '../api/tracking'
import type { BadgeVariant } from './components/Badge'
import { roleColors } from './theme'

export interface StatusEntry {
  /** What staff read. Sentence case. */
  label: string
  /** What a customer reads, where it differs. */
  customer?: string
  variant: BadgeVariant
}

export type Audience = 'staff' | 'customer'

const container = {
  loading: { label: 'Loading', customer: 'Being packed', variant: 'neutral' },
  sealed: { label: 'Sealed', customer: 'Packed', variant: 'info' },
  in_transit: { label: 'In transit', variant: 'info' },
  arrived: { label: 'Arrived in Nigeria', variant: 'warning' },
  customs_clearance: { label: 'Customs clearance', customer: 'In customs', variant: 'warning' },
  cleared: { label: 'Cleared', customer: 'Cleared customs', variant: 'primary' },
  at_warehouse: { label: 'At warehouse', variant: 'primary' },
  fully_released: { label: 'Fully released', customer: 'Completed', variant: 'success' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
} as const satisfies Record<ContainerStatus, StatusEntry>

const invoice = {
  unpaid: { label: 'Unpaid', variant: 'error' },
  partially_paid: { label: 'Partly paid', variant: 'warning' },
  paid: { label: 'Paid', variant: 'success' },
  overpaid: { label: 'Overpaid', variant: 'info' },
  waived: { label: 'Waived', variant: 'neutral' },
  released_with_outstanding: { label: 'Released, balance owed', variant: 'warning' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
} as const satisfies Record<PaymentStatus, StatusEntry>

const packingList = {
  draft: { label: 'Draft', variant: 'neutral' },
  pending_approval: { label: 'Pending approval', variant: 'warning' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
} as const satisfies Record<PackingListStatus, StatusEntry>

const claim = {
  filed: { label: 'Filed', variant: 'warning' },
  under_inspection: { label: 'Under inspection', variant: 'info' },
  inspection_complete: { label: 'Inspection complete', variant: 'info' },
  pending_resolution: { label: 'Pending resolution', variant: 'warning' },
  resolved: { label: 'Resolved', variant: 'success' },
  closed: { label: 'Closed', variant: 'neutral' },
} as const satisfies Record<DamageClaimStatus, StatusEntry>

const dispute = {
  submitted: { label: 'Submitted', variant: 'warning' },
  acknowledged: { label: 'Acknowledged', variant: 'info' },
  investigating: { label: 'Investigating', variant: 'info' },
  escalated_china: { label: 'Escalated to China', variant: 'warning' },
  resolved_adjusted: { label: 'Resolved: adjusted', variant: 'success' },
  resolved_no_change: { label: 'Resolved: no change', variant: 'success' },
  closed: { label: 'Closed', variant: 'neutral' },
} as const satisfies Record<CBMDisputeStatus, StatusEntry>

const manifest = {
  pending: { label: 'Pending', variant: 'warning' },
  verified: { label: 'Verified', variant: 'success' },
  discrepancies_found: { label: 'Discrepancies found', variant: 'error' },
  resolved: { label: 'Resolved', variant: 'success' },
} as const satisfies Record<VerificationStatus, StatusEntry>

const missingItem = {
  reported: { label: 'Reported', variant: 'warning' },
  investigating: { label: 'Investigating', variant: 'info' },
  found_and_shipping: { label: 'Found, shipping', variant: 'info' },
  confirmed_lost: { label: 'Confirmed lost', variant: 'error' },
  resolved: { label: 'Resolved', variant: 'success' },
} as const satisfies Record<MissingItemStatus, StatusEntry>

const seizedItem = {
  seized: { label: 'Seized', variant: 'error' },
  recovery_in_progress: { label: 'Recovery in progress', variant: 'warning' },
  recovered: { label: 'Recovered', variant: 'success' },
  permanently_lost: { label: 'Permanently lost', variant: 'neutral' },
} as const satisfies Record<SeizedItemStatus, StatusEntry>

const refund = {
  pending_review: { label: 'Pending review', customer: 'Being reviewed', variant: 'warning' },
  accounts_reviewed: { label: 'Accounts reviewed', customer: 'Being reviewed', variant: 'warning' },
  pending_approval: { label: 'Pending approval', customer: 'Being reviewed', variant: 'warning' },
  approved: { label: 'Approved', customer: 'Approved', variant: 'info' },
  rejected: { label: 'Rejected', customer: 'Not approved', variant: 'error' },
  processed: { label: 'Paid out', customer: 'Paid', variant: 'success' },
  applied_as_credit: { label: 'Applied as credit', customer: 'Credit on your account', variant: 'success' },
} as const satisfies Record<RefundStatus, StatusEntry>

const releaseNote = {
  active: { label: 'Active', customer: 'Ready to collect', variant: 'success' },
  picked_up: { label: 'Picked up', variant: 'neutral' },
  expired: { label: 'Expired', variant: 'error' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
} as const satisfies Record<ReleaseNoteStatus, StatusEntry>

const carryover = {
  outstanding: { label: 'Outstanding', variant: 'warning' },
  applied: { label: 'Applied', variant: 'info' },
  exempted: { label: 'Exempted', variant: 'neutral' },
  expired: { label: 'Expired', variant: 'neutral' },
} as const satisfies Record<CarryoverStatus, StatusEntry>

const paymentClaim = {
  pending: { label: 'Pending review', customer: 'Being checked', variant: 'warning' },
  confirmed: { label: 'Confirmed', variant: 'success' },
  rejected: { label: 'Rejected', customer: 'Not accepted', variant: 'error' },
} as const satisfies Record<PaymentClaimStatus, StatusEntry>

const notification = {
  pending: { label: 'Pending', variant: 'warning' },
  queued: { label: 'Queued', variant: 'neutral' },
  sent: { label: 'Sent', variant: 'info' },
  delivered: { label: 'Delivered', variant: 'success' },
  failed: { label: 'Failed', variant: 'error' },
} as const satisfies Record<NotifStatus, StatusEntry>

const tenant = {
  active: { label: 'Active', variant: 'success' },
  suspended: { label: 'Suspended', variant: 'error' },
  offboarded: { label: 'Offboarded', variant: 'neutral' },
} as const satisfies Record<TenantStatus, StatusEntry>

const onboardingRequest = {
  new: { label: 'New', variant: 'info' },
  contacted: { label: 'Contacted', variant: 'warning' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
  provisioned: { label: 'Provisioned', variant: 'success' },
} as const satisfies Record<OnboardingRequestStatus, StatusEntry>

const offboardingExport = {
  none: { label: 'Not queued', variant: 'warning' },
  pending: { label: 'Queued', variant: 'info' },
  running: { label: 'Being written', variant: 'info' },
  completed: { label: 'Ready', variant: 'success' },
  failed: { label: 'Failed', variant: 'error' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
} as const satisfies Record<OffboardingExportStatus, StatusEntry>

const staffUser = {
  active: { label: 'Active', variant: 'success' },
  inactive: { label: 'Inactive', variant: 'neutral' },
} as const satisfies Record<'active' | 'inactive', StatusEntry>

const announcement = {
  pending: { label: 'Pending approval', variant: 'warning' },
  approved: { label: 'Approved', variant: 'success' },
  rejected: { label: 'Rejected', variant: 'error' },
} as const satisfies Record<'pending' | 'approved' | 'rejected', StatusEntry>

// Two-person approvals of dangerous platform actions (platform audit Phase 1).
const platformApproval = {
  pending: { label: 'Awaiting approval', variant: 'warning' },
  scheduled: { label: 'Scheduled', variant: 'warning' },
  approved: { label: 'Running', variant: 'info' },
  executed: { label: 'Done', variant: 'success' },
  failed: { label: 'Failed', variant: 'error' },
  rejected: { label: 'Rejected', variant: 'error' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
  expired: { label: 'Expired', variant: 'neutral' },
} as const satisfies Record<ApprovalStatus, StatusEntry>

const platformAdmin = {
  invited: { label: 'Invited', variant: 'warning' },
  active: { label: 'Active', variant: 'success' },
  disabled: { label: 'Disabled', variant: 'neutral' },
} as const satisfies Record<PlatformAdminStatus, StatusEntry>

export const STATUS_REGISTRY = {
  container,
  invoice,
  packingList,
  claim,
  dispute,
  manifest,
  missingItem,
  seizedItem,
  refund,
  releaseNote,
  carryover,
  paymentClaim,
  notification,
  tenant,
  onboardingRequest,
  offboardingExport,
  announcement,
  staffUser,
  platformApproval,
  platformAdmin,
} as const

export type StatusKind = keyof typeof STATUS_REGISTRY
export type StatusOf<K extends StatusKind> = keyof (typeof STATUS_REGISTRY)[K] & string

/** A status no entry knows: shown in words, never as a raw code. */
function humanise(status: string): string {
  const words = status.replace(/_/g, ' ').trim()
  return words ? words[0]!.toUpperCase() + words.slice(1) : '—'
}

function entryFor(kind: StatusKind, status: string): StatusEntry | undefined {
  return (STATUS_REGISTRY[kind] as Record<string, StatusEntry>)[status]
}

/** The words for a status, for staff or for a customer. */
export function statusLabel<K extends StatusKind>(kind: K, status: StatusOf<K> | string, audience: Audience = 'staff'): string {
  const entry = entryFor(kind, status)
  if (!entry) return humanise(status)
  return audience === 'customer' ? (entry.customer ?? entry.label) : entry.label
}

/** The badge colour for a status. An unknown one is neutral. */
export function statusVariant<K extends StatusKind>(kind: K, status: StatusOf<K> | string): BadgeVariant {
  return entryFor(kind, status)?.variant ?? 'neutral'
}

/** Every status of a kind, in registry order: for filter chips and selects. */
export function statusesOf<K extends StatusKind>(kind: K): StatusOf<K>[] {
  return Object.keys(STATUS_REGISTRY[kind]) as StatusOf<K>[]
}

const VARIANT_COLOR: Record<BadgeVariant, string> = {
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
  error: 'var(--color-error)',
  info: 'var(--color-info)',
  primary: 'var(--color-primary)',
  accent: 'var(--color-accent)',
  purple: 'var(--color-role-platform)',
  neutral: 'var(--color-ink-4)',
}

/** A status's colour as a CSS value, for an accent bar or a chart series that stands for that status. */
export function statusColor<K extends StatusKind>(kind: K, status: StatusOf<K> | string): string {
  return VARIANT_COLOR[statusVariant(kind, status)]
}

const VARIANT_STRONG: Record<BadgeVariant, string> = {
  success: 'var(--color-success-strong)',
  warning: 'var(--color-warning-strong)',
  error: 'var(--color-error-strong)',
  info: 'var(--color-info-strong)',
  primary: 'var(--color-primary-strong)',
  accent: 'var(--color-accent)',
  purple: 'var(--color-role-platform)',
  neutral: 'var(--color-ink-3)',
}

/**
 * Colours for a chart whose series are statuses (FD-52): each the colour of that status's badge, so a slice means
 * what its badge means. Where two statuses in one chart share a badge colour ("Partly paid" and "Released, balance
 * owed" are both amber) the later one takes the darker shade of it, so the two stay apart.
 */
export function statusSeriesColors<K extends StatusKind>(kind: K, statuses: readonly (StatusOf<K> | string)[]): string[] {
  const used = new Set<BadgeVariant>()
  return statuses.map((status) => {
    const variant = statusVariant(kind, status)
    const color = used.has(variant) ? VARIANT_STRONG[variant] : VARIANT_COLOR[variant]
    used.add(variant)
    return color
  })
}

/** The one colour of a chart series that is not a status (customers ranked by revenue): neutral, so it means nothing. */
export const NEUTRAL_SERIES_COLOR = 'var(--color-ink-3)'

export type TenantRole = 'tenant_admin' | 'china_office_staff' | 'nigeria_office_staff' | 'warehouse_attendant' | 'customer'

/** Roles are not states: their own words, and their own colour as a dot on a neutral badge (`RoleBadge`). */
const ROLES: Record<TenantRole, { label: string; color: string }> = {
  tenant_admin: { label: 'Admin', color: roleColors.admin },
  china_office_staff: { label: 'China office', color: roleColors.china },
  nigeria_office_staff: { label: 'Nigeria office', color: roleColors.nigeria },
  warehouse_attendant: { label: 'Warehouse', color: roleColors.warehouse },
  customer: { label: 'Customer', color: roleColors.customer },
}

/** A role in words: "Admin", "China office". */
export function roleLabel(role: TenantRole | string): string {
  return ROLES[role as TenantRole]?.label ?? humanise(role)
}

/** A role's colour, for the dot on its badge. */
export function roleColor(role: TenantRole | string): string {
  return ROLES[role as TenantRole]?.color ?? 'var(--color-ink-4)'
}

