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

const PENDING_PACKING_LISTS = { status: 'submitted', limit: 10 } as const
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
