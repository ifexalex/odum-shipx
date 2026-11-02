/**
 * Warehouse (branch/office) API — the letterhead picker for release-note
 * generation and pickup recording. A real paper "Goods Release Note" the
 * user shared lists ~9 branches for one company; migration 041 backfilled
 * exactly one default warehouse per pre-existing tenant, but nothing let a
 * tenant register more, or let a tenant onboarded afterwards get one at
 * all until this API existed.
 */

import { apiRequest } from './client'

export interface Warehouse {
  id: string
  name: string
  address: string | null
  city: string | null
  state: string | null
  /** Destination country for this branch — anchors the state picker (migration 057). */
  country?: string | null
  phone: string | null
  is_default: boolean
  is_active?: boolean
}

export interface CreateWarehouseInput {
  name: string
  address?: string
  city?: string
  state?: string
  country?: string
  phone?: string
  // Promote this warehouse to the tenant's default as part of creating it. The
  // first warehouse a tenant creates becomes the default server-side regardless.
  is_default?: boolean
}

export type UpdateWarehouseInput = Partial<CreateWarehouseInput>

export const warehousesApi = {
  list: () => apiRequest<Warehouse[]>({ method: 'GET', path: '/v1/warehouses' }),

  create: (body: CreateWarehouseInput) =>
    apiRequest<Warehouse>({ method: 'POST', path: '/v1/warehouses', body }),

  update: (id: string, body: UpdateWarehouseInput) =>
    apiRequest<Warehouse>({ method: 'PATCH', path: `/v1/warehouses/${id}`, body }),

  setDefault: (id: string) =>
    apiRequest<Warehouse>({ method: 'PATCH', path: `/v1/warehouses/${id}/set-default` }),

  /**
   * Permanently delete a warehouse.
   *
   * Really deletes it — the name becomes reusable. Rejects with
   * `BUSINESS_RULE_VIOLATION` / rule_id `WAREHOUSE_IN_USE` when a release note,
   * pickup record, payment record or packing list references it, because those
   * records must not lose the warehouse they were issued against. Callers should
   * offer `deactivate` in that case. Also refuses the default warehouse
   * (`WAREHOUSE_DEFAULT_IMMUTABLE`) and the last active one
   * (`WAREHOUSE_LAST_ACTIVE`).
   */
  remove: (id: string) => apiRequest<Warehouse>({ method: 'DELETE', path: `/v1/warehouses/${id}` }),

  // Retire without deleting (is_active = false) — the path for a warehouse that
  // handover documents reference. It stops appearing in pickers, those records
  // keep their history, and its name becomes reusable.
  deactivate: (id: string) =>
    apiRequest<Warehouse>({ method: 'PATCH', path: `/v1/warehouses/${id}/deactivate` }),
}
