# Task FE-09 — State Management & Data Fetching

## Objective

Standardize how every page fetches, caches, and mutates server data, so 150+ pages don't reinvent loading/error/refetch logic independently.

## Depends On

Task 05 (API client).

## Library Choice: TanStack Query

Server state (everything from the API) goes through TanStack Query. Client-only UI state (modal open/closed, form draft values, sidebar collapsed) uses local component state or a tiny `useState`/`useReducer` — don't reach for a global store (Redux/Zustand) for this; the app has no significant cross-page client state that isn't either server data (→ Query) or session/theme (→ the providers from Tasks 02/04).

## Query Key Convention

```ts
// One key factory per domain, colocated with that domain's api module
export const packingListKeys = {
  all: ["packing-lists"] as const,
  list: (params: ListParams) => [...packingListKeys.all, "list", params] as const,
  detail: (id: string) => [...packingListKeys.all, "detail", id] as const,
};
```

Always namespace by tenant implicitly through the session-aware API client (Task 05) — **never** put `tenantId` in the query key itself. Instead, invalidate/clear the entire query cache on tenant switch (impersonation enter/exit, Task 04/08) so there's no risk of one tenant's cached data leaking into another tenant's view after a context switch. This is the frontend's one real tenant-isolation responsibility: not filtering data (the backend does that), but not **caching across a tenant boundary**.

```ts
// On impersonation exit (Task 04) and on logout:
queryClient.clear();
```

## Pagination Hook

One generic hook wraps the cursor pattern from Task 05, used by every list page in Task 07:

```ts
function useCursorPagination<T>(
  queryKeyBase: readonly unknown[],
  fetchPage: (cursor: string | undefined, limit: number) => Promise<ListResponse<T>>,
  limit = 20,
) {
  // useInfiniteQuery under the hood; getNextPageParam reads meta.pagination.next_cursor
  // exposes: { items: T[], hasMore, totalCount, loadMore, isLoading, isFetchingNextPage, error }
}
```

Don't build "page number" pagination UI anywhere — the backend is cursor-only (no offset, no total-pages). Use "Load more" / infinite scroll, or a "Next" button that's disabled when `hasMore` is false. Never expose a jump-to-page-N control; there's no backend support for it.

## Mutations

```ts
const { mutate, isPending } = useMutation({
  mutationFn: () => packingListApi.approve(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: packingListKeys.detail(id) });
    queryClient.invalidateQueries({ queryKey: packingListKeys.all }); // list views showing this item
  },
});
```

### Invalidation is automatic (2026-11-03)

**You no longer have to remember the `onSuccess` block above.** Every successful
non-GET request invalidates the query roots its path affects, centrally, in
`api/client.ts`. The example above still works and is still the clearest way to
express a *narrow* invalidation (e.g. one detail key), but it is no longer what
keeps the UI correct.

**Why this changed.** `lib/queryClient.ts` justified `refetchOnWindowFocus: false`
and a 3-minute `staleTime` with "mutations call invalidateQueries immediately".
An audit found that true in **5 of 45** files that mutate. With nothing else to
correct the cache, a deleted row stayed on screen until a hard reload — reported
from live use as deleting a container and still seeing it in the list.

`ContainerDetail.tsx` was typical and worth studying: it held its data in
`useState`, called `containersApi.delete()` **directly**, and navigated back to a
`ContainerList` reading a cached `useInfiniteQuery`. A `useDeleteContainer` hook
that *would* have invalidated existed and was never wired up. Patching 40 call
sites would have left the 41st free to reintroduce it, so the guarantee moved to
one place.

**How to add an endpoint.** Add a rule to `api/cacheInvalidation.ts`. If you
forget, `api/cacheInvalidation.test.ts` fails: it scrapes every mutating path out
of `api/*.ts` (via `import.meta.glob`, not `node:fs` — the app tsconfig has no
Node types) and asserts each one matches a rule. A dev-only `console.warn` also
fires at runtime.

**Design decisions worth knowing:**

| Decision | Reason |
|---|---|
| Invalidate **roots** (`['containers']`), not exact keys | A list key embeds its filters, and a mutation cannot know which filter combinations are cached. React Query only refetches queries with active observers, so cost is bounded by what is on screen. |
| **Cross-domain effects are explicit** per rule | Deleting a container frees its packing lists; approving a packing list moves container CBM and can create billing. Those are listed in the rule, not left to callers. |
| **Fire-and-forget**, never awaited, never throws | A cache problem must not turn a write that actually succeeded into an error the user sees. |
| **Nothing on GET** | Invalidating on reads is how you build a refetch loop. |
| **Nothing on a failed write** | It changed nothing, and refetching would repaint the list and mask the failure. |
| Pre-auth paths map to an **empty** root set | They must still *match*, so the drift test cannot later be satisfied by an accidental catch-all. |

**~~Known limitation.~~ Closed 2026-11-08 (master plan 7.150).** This originally
fixed only *cross-page* staleness: a page holding its own copy in `useState` is
not a query observer, so invalidation could not refresh it, and those pages
reloaded themselves manually. Every page named here (`ContainerDetail`,
`Warehouses`, the config pages) now reads through a query, so the automatic
invalidation reaches the open page as well as the lists — which is why the
manual `load()` reloads beside each mutation could be **deleted** rather than
rewritten.

One consequence worth knowing when adding a page: a mutation whose write does
not pass through `api/client.ts` is not covered. The only current case is the
container **document upload**, a direct PUT to presigned storage — the presign
POST fires the invalidation *before* the bytes land, so `DocumentsTab`
invalidates `containerKeys.documents(id)` explicitly after the upload resolves.

**Do not re-enable `refetchOnWindowFocus` to paper over staleness.** If something
looks stale, the registry is missing a rule or a cross-domain effect.

**Optimistic updates** are worth it only for high-frequency, low-risk actions (e.g. toggling a notification preference, marking a notification read). For anything with a state machine or money attached (approve/reject, payment recording, refund approval), wait for the real response — these are exactly the places a stale optimistic UI causes the most damage if the mutation actually fails (e.g. self-approval rejection, illegal transition).

## Read-Only Impersonation Interaction

When `session.readOnly` is true (Task 08), mutation hooks should still be wired normally — the *button* is disabled/hidden by the `Action` wrapper (Task 08), not the mutation hook itself. Don't special-case `useMutation` calls for read-only; keep the guard at the UI-affordance layer so there's exactly one place (the `Action` component) responsible for the read-only rule, per the "single chokepoint" pattern already used on the backend (`get_tenant_context`).

## Polling / Live-ish Data

A few screens benefit from light polling rather than websockets (not in scope — no realtime infra exists):

- Impersonation countdown: client-side timer, not polling (Task 08).
- Notification bell unread count: poll `GET /v1/notifications/log` (or a lighter unread-count if one exists) on a ~60s interval while the tab is focused, pause when backgrounded (`document.visibilitychange`).
- Excel import progress (Task 10): short-interval poll against the import job status while the wizard's "validating" step is active, stop once terminal status is reached.

## Stale Time Strategy

Default `staleTime` is **3 minutes** — logistics data only changes when a staff member explicitly acts, and `invalidateQueries` in every mutation hook handles freshness for your own changes immediately.

| Domain | staleTime | Rationale |
|---|---|---|
| Containers, billing, claims, refunds, manifests, packing lists | `3 min` (default) | State-machine-driven; mutations invalidate instantly |
| KPI stat-count queries (`limit: 500`) | `5 min` (`STALE_5_MIN`) | Badge numbers don't need to be second-accurate |
| Config (dollar rate, CBM rate, webhook) | `Infinity` (`STALE_FOREVER`) | Never changes without an explicit Save |
| Staff users, customers, platform tenants | `5 min` (`STALE_5_MIN`) | Reference data, changes rarely |
| Notification log | `30s` (`STALE_30S`) | Only domain with autonomous change (background SQS) |

`refetchOnWindowFocus: false` globally — tab switches do not fire DB queries. Freshness is driven by user actions, not timers.

Constants exported from `src/lib/queryClient.ts`: `STALE_FOREVER`, `STALE_5_MIN`, `STALE_30S`.

## Implementation Notes

- `src/lib/queryClient.ts` — singleton `QueryClient` with global defaults; exports stale-time constants.
- `App.tsx` — `QueryClientProvider` wraps both local dev and production provider trees; `SessionProvider.onSessionChange={() => queryClient.clear()}` wires cache eviction on every session transition.
- `src/hooks/useCursorPagination.ts` — generic `useInfiniteQuery` wrapper; exposes `{ items, hasMore, totalCount, loadMore, isLoading, isFetchingMore, error, refetch }`.
- `src/api/keys.ts` — query key factories for all 10 domains; `tenantId` never appears in any key.
- Domain hooks: `useContainers`, `usePackingLists`, `useManifests`, `useBilling`, `useClaims`, `useRefunds`, `useNotifications`, `useConfig`, `useStaff` — each exports list, detail, and mutation hooks with correct `invalidateQueries` wiring.
- `src/test/queryWrapper.tsx` — `withQuery()` / `createTestQueryClient()` for tests. A component calling `useQuery` without a provider throws `No QueryClient set` with a stack pointing at the component, not the test, so it reads like a product bug.
- Pages refactored: **all of them**, as of master plan 7.150 (2026-11-08). `ContainerList`, `BillingList` and `ClaimList` came first; the remaining 25 hand-rolled `useEffect`+`useState` fetches were migrated area by area and the greppable `migrate to TanStack Query` suppressions are now at **zero**. The one surviving hand-rolled loader, `ActivityLog.tsx`, was never part of that set — 7.149 resolved its render-purity problems a different way, so it carries no suppression; migrating it is optional follow-up.

## Acceptance Criteria

- [x] `queryClient.clear()` is called on every tenant-context switch (login, logout, impersonation enter, impersonation exit) — wired in `App.tsx` via `SessionProvider.onSessionChange`
- [x] `tenantId` never appears inside any query key
- [x] One shared `useCursorPagination` hook exists; `ContainerList`, `BillingList`, `ClaimList` use it; no manual cursor state in those pages
- [x] Optimistic updates not implemented — all mutations wait for server confirmation (correct for state-machine + money operations)
- [x] No page calls `apiRequest`/api modules directly — **done (2026-07-10)**: all list pages now consume domain query hooks (`useContainerList`/`usePackingListList`/`useManifestList`/`useDisputeList`/`useReleaseNoteList`/`useRefundList`/`useMissing/SeizedItemList`/`useCustomerList`/`useStaffList`/`usePlatformTenantList`). NotificationLog migrated to `useNotifLogPolling`. Remaining direct calls are one-shot mutations inside mutation handlers (correct).
- [x] Notification polling pauses when tab is backgrounded — **done (2026-07-10)**: `useCursorPagination` gained a `refetchIntervalMs` option whose `refetchInterval` callback returns `false` while `document.hidden` (plus `refetchIntervalInBackground: false`). `useNotifLogPolling` uses it (60s). Unit-tested in `useNotifLogPolling.test.tsx`.

## No page loads server data in a `useEffect` (audit FE-05, 2026-11-16)

The last 16 files (about 20 effects) that fetched by hand now read through React Query hooks in `src/hooks/`. `shell/noFetchInEffect.test.ts` fails if an effect in `pages/`, `shell/` or `design/` calls an API module, directly or through a function in the same file. **One documented exception:** `PaymentSuccess` POSTs the Paystack reference once on landing so the server can verify and record the payment; that is a write, and a query would retry and refetch it.

| Page | Was | Now |
|---|---|---|
| `ManifestList`, `ReleaseNoteList` (stats rows) | `xApi.stats()` in an effect | `useManifestStats`, `useReleaseNoteStats` (new `stats()` keys under each domain root) |
| `PrintPackingList`, `PrintReleaseNote` | `get(id)` in an effect | `usePackingList`, `useReleaseNote` (share the detail page's cache entry, so the print view opens from it) |
| `CbmRateConfig`, `DollarRateConfig`, `RateHistoryTable` | load + `setState` | `useCbmRate`/`useDollarRate` with `freshOnOpen`, `useRateHistory` (new `configKeys.rateHistory`, so saving a rate now refreshes its history table, which it did not before) |
| `PaymentGatewayConfig` (two panels), `WebhookConfig` | each panel fetched `GET /v1/tenant/config` itself | `useTenantConfig({ freshOnOpen })`; the bank-transfer panel takes the loaded value as a prop, so the page makes **one** request, not two |
| `PlatformSettings` (General, Providers, Plans) | three effects | `usePlatformGeneralSettings`, `usePlatformGateways`, `usePlatformPlans` (new `platformSettingsKeys`) |
| `PlatformDashboard` | `Promise.all` + audit log in an effect | `usePlatformDashboardStats` (new `platformDashboardKeys`), `usePlatformTenantList`, `useRecentPlatformActivity` (`platformAuditKeys.recent`, not `list`, which the audit-log page pages through as an infinite query) |
| tenant `Dashboard` (six queues) | three effects, six fetches | `hooks/useDashboard.ts`, each under its domain's `lookup` key, so approving a packing list, recording a payment or a pickup now refreshes the queue (before, it showed whatever was true when the dashboard opened) |
| `BillingDetail` Add-charge dialog | `listChargeTypes()` in an effect | `useChargeTypes` |
| `Account` | `customersApi.list()` in an effect | `useOwnCustomer` |
| `ImportPackingLists`, `CreatePackingList` | pickers, rates and the draft in one large effect | `useContainerLookup`, `useCustomerLookup`, `useWarehouses`, the two rate hooks, `usePackingListForEdit` |

**Forms: read fresh, copy once.** A settings or edit form must not be filled from a cached copy that someone else has since changed, and a background refetch must not overwrite what the user is typing. `FRESH_ON_OPEN` (`staleTime: 0, refetchOnMount: 'always'`) makes the form's read ignore the cache's age, and `useSeedOnce(query, seed)` copies the freshly fetched value into the form's own state exactly once (`hooks/useSeedOnce.ts`). After a save the page writes the response into the cache with `setQueryData`; the write also invalidates the domain through the central rules.

**Invalidation.** Every key the migrated reads use sits under a root with a rule in `api/cacheInvalidation.ts`. New rules: platform settings and plan writes invalidate `platformSettingsKeys`, the tenant list and the audit feed; tenant writes also invalidate the platform dashboard totals and the audit feed. `api/cacheInvalidation.test.ts` pins them and that each `lookup` key is a child of its domain root.

**Tests.** Pages that now use a query needed a provider in their tests (`withQuery`). `PlatformSettings` and `WebhookConfig` had no tests and now do. Four tests had a latent race (a synchronous read immediately after the first await) that the new timing exposed; they now wait for the row. Checked in a real browser: all fourteen migrated pages render with no error boundary and no repeated data request.
