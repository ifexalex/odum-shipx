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
  phone: string | null
  is_default: boolean
  is_active?: boolean
}

export interface CreateWarehouseInput {
  name: string
  address?: string
  city?: string
  state?: string
  phone?: string
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

  // Soft-deactivate (is_active = false). The backend refuses to remove the
  // default or the last active warehouse.
  deactivate: (id: string) =>
    apiRequest<Warehouse>({ method: 'DELETE', path: `/v1/warehouses/${id}` }),
}
