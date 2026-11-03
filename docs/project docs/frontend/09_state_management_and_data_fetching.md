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

**Known limitation.** This fixes *cross-page* staleness, which is the reported
class of bug. A page that holds its own copy in `useState` (there are many —
`ContainerDetail`, `Warehouses`, most config pages) is not a query observer, so
invalidation cannot refresh it; those pages still reload themselves manually.
Migrating them onto the existing mutation hooks is follow-up work, deliberately
not bundled with this change.

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
- Pages refactored: `ContainerList`, `BillingList`, `ClaimList`. Remaining pages follow the same pattern — replace `useEffect`+`useState` with the corresponding domain hook.

## Acceptance Criteria

- [x] `queryClient.clear()` is called on every tenant-context switch (login, logout, impersonation enter, impersonation exit) — wired in `App.tsx` via `SessionProvider.onSessionChange`
- [x] `tenantId` never appears inside any query key
- [x] One shared `useCursorPagination` hook exists; `ContainerList`, `BillingList`, `ClaimList` use it; no manual cursor state in those pages
- [x] Optimistic updates not implemented — all mutations wait for server confirmation (correct for state-machine + money operations)
- [x] No page calls `apiRequest`/api modules directly — **done (2026-07-10)**: all list pages now consume domain query hooks (`useContainerList`/`usePackingListList`/`useManifestList`/`useDisputeList`/`useReleaseNoteList`/`useRefundList`/`useMissing/SeizedItemList`/`useCustomerList`/`useStaffList`/`usePlatformTenantList`). NotificationLog migrated to `useNotifLogPolling`. Remaining direct calls are one-shot mutations inside mutation handlers (correct).
- [x] Notification polling pauses when tab is backgrounded — **done (2026-07-10)**: `useCursorPagination` gained a `refetchIntervalMs` option whose `refetchInterval` callback returns `false` while `document.hidden` (plus `refetchIntervalInBackground: false`). `useNotifLogPolling` uses it (60s). Unit-tested in `useNotifLogPolling.test.tsx`.
