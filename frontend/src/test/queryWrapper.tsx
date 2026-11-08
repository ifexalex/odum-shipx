/**
 * Test helpers for pages that read through TanStack Query.
 *
 * A component calling `useQuery`/`useQueryClient` throws
 * `No QueryClient set, use QueryClientProvider to set one` when rendered
 * without a provider — and the stack points at the component, not the test, so
 * it reads like a product bug rather than a missing harness. Every page
 * migrated under master plan 7.150 needs one of these.
 *
 * `retry: false` matters: a stubbed endpoint that rejects would otherwise be
 * retried three times with backoff, turning a clear failure into a timeout.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { JSX, ReactNode } from 'react'

/** A throwaway client with retries and caching off, for one test. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

/**
 * Wrap a tree in a fresh `QueryClientProvider`.
 *
 * Composes with whatever providers a harness already has, rather than
 * replacing them:
 *
 *     render(withQuery(
 *       <MemoryRouter>…</MemoryRouter>,
 *     ))
 *
 * Pass `client` when the test needs to assert on the cache or spy on
 * `invalidateQueries`.
 */
export function withQuery(children: ReactNode, client = createTestQueryClient()): JSX.Element {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
