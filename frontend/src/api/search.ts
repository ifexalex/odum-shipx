/**
 * Global search (audit UX-05): GET /v1/search?q= — one box that finds a container, shipment, invoice, release
 * note or customer. What comes back depends on the caller's role and is decided by the server, never here:
 * a customer only ever gets their own records, and `customer` results are staff-only.
 */

import { apiRequest } from './client'

export type SearchResultKind = 'container' | 'shipment' | 'invoice' | 'release_note' | 'customer'

export interface SearchResult {
  kind: SearchResultKind
  /** Record id. For `shipment` this is the packing-list id, which both the staff and the customer routes take. */
  id: string
  title: string
  subtitle: string | null
  status: string | null
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
}

/** The server ignores anything shorter than this (and so should the UI, to save the round trip). */
export const MIN_SEARCH_LENGTH = 2
/** The server rejects anything longer than this with a 422; the input enforces it so the user never hits it. */
export const MAX_SEARCH_LENGTH = 64

export const searchApi = {
  search: (q: string): Promise<SearchResponse> => apiRequest<SearchResponse>({ method: 'GET', path: '/v1/search', query: { q } }),
}
