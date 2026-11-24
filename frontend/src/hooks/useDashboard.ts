import { useQuery } from '@tanstack/react-query'
import { billingApi, disputeApi } from '../api/billing'
import { billingKeys, disputeKeys, manifestKeys, packingListKeys, releaseNoteKeys } from '../api/keys'
import { manifestApi } from '../api/manifest'
import { packingListApi } from '../api/packingList'
import { releaseNotesApi } from '../api/releaseNotes'
import { useContainerLookup } from './useContainers'

// The tenant dashboard's work queues. Each is a small, flat read under its domain's `lookup` key, so a write anywhere
// in that domain (approving a packing list, recording a payment or a pickup) refreshes the queue through the central
// invalidation rules, where the old `useEffect` fetches showed whatever was true when the dashboard first opened.
// All are non-fatal: a queue that fails to load is simply not shown.

// `pending_approval`, the status a submitted list has. This read `submitted`, which no packing list ever has, so the
// queue was always empty (found 2026-11-17).
const PENDING_PACKING_LISTS = { status: 'pending_approval', limit: 10 } as const
const PENDING_MANIFESTS = { verification_status: 'pending', limit: 20 } as const
const OPEN_DISPUTES = { status: 'submitted', limit: 10 } as const
// Oldest billed first, so the most overdue (and highest storage-fee risk) is at the top.
const OUTSTANDING_BILLING = { status: 'unpaid,partially_paid', sort: 'billed_at', direction: 'asc', limit: 6 } as const
const ACTIVE_RELEASE_NOTES = { status: 'active', limit: 50 } as const

/** A bounded sample for the admin's "Recent containers" table. */
export function useRecentContainers(enabled: boolean) {
  return useContainerLookup({}, enabled)
}

/** Packing lists waiting for approval. */
export function usePendingPackingLists(enabled: boolean) {
  return useQuery({
    queryKey: packingListKeys.lookup(PENDING_PACKING_LISTS),
    queryFn: () => packingListApi.list(PENDING_PACKING_LISTS),
    enabled,
  })
}

/** Manifests not yet verified. */
export function usePendingManifests(enabled: boolean) {
  return useQuery({
    queryKey: manifestKeys.lookup(PENDING_MANIFESTS),
    queryFn: () => manifestApi.list(PENDING_MANIFESTS),
    enabled,
  })
}

/** CBM disputes waiting to be acknowledged. */
export function useOpenDisputes(enabled: boolean) {
  return useQuery({ queryKey: disputeKeys.lookup(OPEN_DISPUTES), queryFn: () => disputeApi.list(OPEN_DISPUTES), enabled })
}

/** Unpaid and part-paid invoices: money to collect. */
export function useOutstandingBilling(enabled: boolean) {
  return useQuery({
    queryKey: billingKeys.lookup(OUTSTANDING_BILLING),
    queryFn: () => billingApi.list(OUTSTANDING_BILLING),
    enabled,
  })
}

/** Release notes issued and not yet collected: goods to release. */
export function useActiveReleaseNotes(enabled: boolean) {
  return useQuery({
    queryKey: releaseNoteKeys.lookup(ACTIVE_RELEASE_NOTES),
    queryFn: () => releaseNotesApi.list(ACTIVE_RELEASE_NOTES),
    enabled,
  })
}

// The China office's work queue (audit UX-10). Small first pages: the page shows a count (`total_count`) and the
// first few rows of each, and links to the filtered list for the rest.
const CHINA_QUEUE_SIZE = 5
export const CHINA_QUEUES = {
  pendingApprovalPackingLists: { status: 'pending_approval', limit: CHINA_QUEUE_SIZE },
  rejectedPackingLists: { status: 'rejected', limit: CHINA_QUEUE_SIZE },
  draftPackingLists: { status: 'draft', limit: CHINA_QUEUE_SIZE },
  pendingManifests: { verification_status: 'pending', limit: CHINA_QUEUE_SIZE },
  escalatedDisputes: { status: 'escalated_china', limit: CHINA_QUEUE_SIZE },
} as const

/** Packing lists in one status, for a China work queue. */
export function usePackingListQueue(
  params:
    | typeof CHINA_QUEUES.pendingApprovalPackingLists
    | typeof CHINA_QUEUES.rejectedPackingLists
    | typeof CHINA_QUEUES.draftPackingLists,
) {
  return useQuery({ queryKey: packingListKeys.lookup(params), queryFn: () => packingListApi.list(params) })
}

/** Manifests Nigeria has not verified yet. */
export function useChinaManifestQueue() {
  const params = CHINA_QUEUES.pendingManifests
  return useQuery({ queryKey: manifestKeys.lookup(params), queryFn: () => manifestApi.list(params) })
}

/** CBM disputes escalated to the China office. */
export function useEscalatedDisputes() {
  const params = CHINA_QUEUES.escalatedDisputes
  return useQuery({ queryKey: disputeKeys.lookup(params), queryFn: () => disputeApi.list(params) })
}

