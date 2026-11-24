/**
 * Automatic cache invalidation for mutating API calls.
 *
 * ## Why this exists
 *
 * `lib/queryClient.ts` sets `refetchOnWindowFocus: false` and a 3-minute
 * `staleTime`, and justifies both with: *"Mutations call invalidateQueries
 * immediately … Mutations + invalidateQueries handle freshness correctly."*
 *
 * That assumption was false in **40 of 45** files that mutate. Only five
 * invalidated anything. With nothing else to correct the cache, a deleted row
 * stayed on screen until a hard reload — the reported symptom was deleting a
 * container and still seeing it in the list. `ContainerDetail` is typical: it
 * held state in `useState`, called `containersApi.delete()` directly, and
 * navigated back to a `ContainerList` reading a cached `useInfiniteQuery`.
 * A `useDeleteContainer` hook that *would* have invalidated existed and was
 * never used.
 *
 * ## The approach
 *
 * Rather than patch 40 call sites — which leaves the 41st free to reintroduce
 * the bug — invalidation happens once, here, keyed off the request path. Any
 * successful non-GET invalidates the query roots its path affects, whether the
 * caller used a hook, a direct `fetch`, or something written next year.
 *
 * `api/cacheInvalidation.test.ts` asserts every mutating path declared in
 * `api/*.ts` matches a rule, so adding an endpoint without a mapping fails CI
 * instead of silently going stale.
 *
 * ## Deliberate choices
 *
 * - **Invalidate roots, not exact keys.** A list's key includes its filters
 *   (`['containers','list',{status:'loading'}]`), and a mutation cannot know
 *   which filter combinations are cached. Invalidating `['containers']` covers
 *   every one. React Query only refetches queries with active observers, so the
 *   cost is bounded by what is actually on screen.
 * - **Cross-domain effects are explicit.** Deleting a container frees its
 *   packing lists; approving a packing list moves container CBM and can create
 *   billing. Those are listed per rule rather than left to the caller.
 * - **Fire-and-forget.** Invalidation never rejects into the caller's `await`,
 *   so a cache hiccup cannot turn a successful write into a UI error.
 */

import {
  announcementKeys,
  billingKeys,
  claimKeys,
  configKeys,
  containerCapacityKeys,
  containerKeys,
  customerKeys,
  customerNotifKeys,
  disputeKeys,
  manifestKeys,
  missingItemKeys,
  notifLogKeys,
  onboardingRequestKeys,
  packingListKeys,
  platformAuditKeys,
  platformDashboardKeys,
  platformSettingsKeys,
  platformTenantKeys,
  refundKeys,
  releaseNoteKeys,
  seizedItemKeys,
  staffKeys,
  staffNotifKeys,
  warehouseKeys,
} from './keys'

type KeyRoot = readonly unknown[]

interface Rule {
  /** Matched against the request path (query string already stripped). */
  test: RegExp
  /** Query roots to invalidate. Empty = nothing is cached for this path. */
  roots: KeyRoot[]
}

/**
 * Ordered: the FIRST match wins, so more specific paths must come first.
 * `/v1/claims/seized-items/{id}` has to precede `/v1/claims/...`.
 */
const RULES: Rule[] = [
  // ── Public / unauthenticated: nothing is cached before sign-in ───────────
  { test: /^\/v1\/(register|activate|invites|onboarding-requests)(\/|$)/, roots: [] },
  // Presigned-URL mints create no domain state of their own.
  { test: /^\/v1\/uploads\/presigned-url$/, roots: [] },

  // ── Claims: sub-resources before the generic claims rule ────────────────
  { test: /^\/v1\/claims\/seized-items\//, roots: [seizedItemKeys.all, claimKeys.all] },
  { test: /^\/v1\/claims\/missing-items\//, roots: [missingItemKeys.all, claimKeys.all] },
  // Resolving a claim can trigger a refund, and a claim is raised against a billing record.
  { test: /^\/v1\/claims(\/|$)/, roots: [claimKeys.all, refundKeys.all, billingKeys.all] },

  // ── Billing: disputes and carryovers before the generic billing rule ────
  { test: /^\/v1\/billing\/disputes\//, roots: [disputeKeys.all, billingKeys.all] },
  { test: /^\/v1\/billing\/carryovers\//, roots: [billingKeys.all] },
  { test: /^\/v1\/billing(\/|$)/, roots: [billingKeys.all, disputeKeys.all] },

  // ── Containers ──────────────────────────────────────────────────────────
  // A container's packing lists move with it: deleting or cancelling one frees
  // them, and a status change is what the tracking view reads.
  // Moving a container to `cleared` invoices its customers, so billing views (and the
  // unbilled queue under billingKeys) must refresh with it.
  { test: /^\/v1\/containers(\/|$)/, roots: [containerKeys.all, packingListKeys.all, billingKeys.all] },

  // ── Packing lists ───────────────────────────────────────────────────────
  // Approving consumes container capacity/CBM and can generate billing, so both
  // move even though the request path mentions neither.
  {
    test: /^\/v1\/packing-lists(\/|$)/,
    roots: [packingListKeys.all, containerKeys.all, billingKeys.all],
  },

  // ── Manifests ───────────────────────────────────────────────────────────
  // Verification advances the container and can surface discrepancies as claims.
  { test: /^\/v1\/manifests(\/|$)/, roots: [manifestKeys.all, containerKeys.all, claimKeys.all] },

  // ── Payments ────────────────────────────────────────────────────────────
  // Every payment path settles money against a billing record; confirming one
  // can also unlock a release note.
  { test: /^\/v1\/payments(\/|$)/, roots: [billingKeys.all, releaseNoteKeys.all] },

  // ── Release notes ───────────────────────────────────────────────────────
  // Recording a pickup updates the shipment the container list reports on.
  {
    test: /^\/v1\/release-notes(\/|$)/,
    roots: [releaseNoteKeys.all, billingKeys.all, containerKeys.all],
  },

  // ── Refunds ─────────────────────────────────────────────────────────────
  { test: /^\/v1\/refunds(\/|$)/, roots: [refundKeys.all, billingKeys.all] },

  // ── Warehouses ──────────────────────────────────────────────────────────
  // The picker on the packing-list form and the release-note letterhead both
  // read this list, so a rename or a new default must reach them.
  {
    test: /^\/v1\/warehouses(\/|$)/,
    roots: [warehouseKeys.all, packingListKeys.all, releaseNoteKeys.all],
  },

  // ── Customers ───────────────────────────────────────────────────────────
  // Anonymising or renaming a customer changes how they read on every list that
  // joins their name.
  {
    test: /^\/v1\/customers(\/|$)/,
    roots: [customerKeys.all, billingKeys.all, packingListKeys.all, claimKeys.all],
  },

  // ── Notifications: specific buckets before the generic rule ─────────────
  { test: /^\/v1\/notifications\/announcements(\/|$)/, roots: [announcementKeys.all] },
  { test: /^\/v1\/notifications\/announce$/, roots: [announcementKeys.all] },
  { test: /^\/v1\/notifications\/customer(\/|$)/, roots: [customerNotifKeys.all] },
  { test: /^\/v1\/notifications\/staff(\/|$)/, roots: [staffNotifKeys.all] },
  { test: /^\/v1\/notifications\/log(\/|$)/, roots: [notifLogKeys.all] },

  // ── Tenant config: narrower paths first ─────────────────────────────────
  { test: /^\/v1\/tenant\/container-capacities(\/|$)/, roots: [containerCapacityKeys.all] },
  // A charge type or CBM/dollar rate change re-prices what billing displays.
  { test: /^\/v1\/tenant\/charge-types(\/|$)/, roots: [configKeys.all, billingKeys.all] },
  { test: /^\/v1\/tenant\/(cbm-rate|dollar-rate)$/, roots: [configKeys.all, billingKeys.all] },
  { test: /^\/v1\/tenant\/notification-templates(\/|$)/, roots: [configKeys.all] },
  { test: /^\/v1\/tenant\/config(\/|$)/, roots: [configKeys.all] },
  // Toggling the public signup link is tenant configuration; the card
  // showing it reads through the same config root.
  { test: /^\/v1\/tenant\/registration-link$/, roots: [configKeys.all] },
  { test: /^\/v1\/tenant\/users(\/|$)/, roots: [staffKeys.all] },
  // The signed-in user's own profile feeds the shell, and their name appears as
  // an actor on staff lists.
  { test: /^\/v1\/tenant\/me$/, roots: [staffKeys.all, configKeys.all] },

  // ── Platform ────────────────────────────────────────────────────────────
  { test: /^\/v1\/platform\/onboarding-requests(\/|$)/, roots: [onboardingRequestKeys.all] },
  // Provisioning a tenant closes the lead it came from, and changes the dashboard's totals and its activity feed.
  {
    test: /^\/v1\/platform\/tenants(\/|$)/,
    roots: [platformTenantKeys.all, onboardingRequestKeys.all, platformDashboardKeys.all, platformAuditKeys.all],
  },
  // Plan limits change every tenant's effective limits (the tenant list shows users x/limit).
  {
    test: /^\/v1\/platform\/(settings|plans)(\/|$)/,
    roots: [platformSettingsKeys.all, platformTenantKeys.all, platformAuditKeys.all],
  },
]

/** The rule for a path, or undefined when nothing matches. */
export function ruleForPath(path: string): Rule | undefined {
  const clean = path.split('?')[0] ?? path
  return RULES.find((r) => r.test.test(clean))
}

/** Exposed for the drift test; not part of the runtime contract. */
export const INVALIDATION_RULES: readonly Rule[] = RULES
