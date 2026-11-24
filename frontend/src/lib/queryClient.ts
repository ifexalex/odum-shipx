import { MutationCache, QueryClient } from '@tanstack/react-query'
import { toast } from '../design/toast'

/** What a mutation's toast says once it succeeds (FD-21): words, or words worked out from the response. */
export type SuccessToast = string | { title: string; body?: string } | ((data: unknown) => { title: string; body?: string })

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: { successToast?: SuccessToast }
  }
}

/** Every mutation that declares `meta.successToast` confirms itself with a toast; nothing per page. */
const mutationCache = new MutationCache({
  onSuccess: (data, _variables, _context, mutation) => {
    const spec = mutation.meta?.successToast
    if (!spec) return
    const message = typeof spec === 'string' ? { title: spec } : typeof spec === 'function' ? spec(data) : spec
    toast.success(message.title, message.body)
  },
})

/**
 * Singleton QueryClient shared across the app.
 *
 * staleTime strategy — matched to ShipX data volatility:
 *
 * Default (3 min): Containers, packing lists, billing, claims, manifests, refunds.
 * These only change when a staff member explicitly acts. Mutations call invalidateQueries
 * immediately, so the timer is just a safety net for data changed by *another user* on
 * a different session. 3 minutes is generous — no shipping operation moves faster than that.
 *
 * Override to Infinity: Config (rates, webhook). Never changes without an explicit Save.
 * Override to 5 min: Staff users, customers, platform tenants. Rarely change.
 * Override to 30s: Notification log only — genuinely gets new entries from background SQS.
 *
 * refetchOnWindowFocus: false — logistics data doesn't change spontaneously. Tab switches
 * should NOT fire DB queries. Mutations + invalidateQueries handle freshness correctly.
 *
 * HOW that is guaranteed (added 2026-11-03): it used to be an assumption, and a false
 * one — 40 of the 45 files that mutate never invalidated anything, so with
 * refetchOnWindowFocus off and a 3-minute staleTime, nothing corrected a stale list and
 * a deleted row survived until a hard reload. Invalidation now happens centrally in
 * `api/client.ts` on every successful non-GET, driven by the path→key registry in
 * `api/cacheInvalidation.ts`. Do NOT re-enable refetchOnWindowFocus to paper over
 * staleness: if something looks stale, the registry is missing a rule or a cross-domain
 * effect, and `api/cacheInvalidation.test.ts` is where that gets pinned.
 *
 * IMPORTANT: queryClient.clear() is called on every tenant-context switch (login, logout,
 * impersonation enter/exit) — wired in App.tsx via SessionProvider.onSessionChange.
 */

const THREE_MINUTES = 3 * 60 * 1000

export const queryClient = new QueryClient({
  mutationCache,
  defaultOptions: {
    queries: {
      staleTime: THREE_MINUTES,
      gcTime: 10 * 60 * 1000,
      retry: (failureCount, error) => {
        // Never retry 4xx — they won't resolve on retry.
        if (error instanceof Error && 'status' in error) {
          const status = (error as unknown as { status: number }).status
          if (status >= 400 && status < 500) return false
        }
        return failureCount < 1
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
})

/** Use on config queries (dollar rate, CBM rate, webhook, notification templates). */
export const STALE_FOREVER = Infinity

/** Use on reference data (staff users, customers, platform tenants). */
export const STALE_5_MIN = 5 * 60 * 1000

/** Use on the notification log — new entries arrive from background SQS. */
export const STALE_30S = 30_000
