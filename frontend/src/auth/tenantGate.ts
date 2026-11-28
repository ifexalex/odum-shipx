/**
 * Tenant-blocked gate (audit gap A4 / prototype 16.12).
 *
 * When the backend reports the whole tenant as gone — HTTP 410
 * `TENANT_OFFBOARDED` or 403 `TENANT_SUSPENDED` (shared/exceptions.py, raised
 * by shared/auth.py's fail-closed tenant-status check on *every* request) —
 * individual per-page error banners are the wrong shape: every screen would
 * fail identically. The same holds for 503 `MAINTENANCE_MODE`, returned on every
 * request while a platform admin has ShipX in maintenance mode (audit PA-01). The API client reports the code here, and the layouts
 * render a single full-page state (TenantBlockedScreen) instead of routed
 * content.
 *
 * Module-level store (same pattern as tokenStore/sessionBridge): the API
 * client is a plain module and can't use React context. React components
 * subscribe via useSyncExternalStore.
 */
import { useSyncExternalStore } from 'react'

export type TenantBlockedKind = 'offboarded' | 'suspended' | 'maintenance'

const KIND_BY_CODE: Record<string, TenantBlockedKind> = {
  TENANT_OFFBOARDED: 'offboarded',
  TENANT_SUSPENDED: 'suspended',
  MAINTENANCE_MODE: 'maintenance',
}

let blocked: TenantBlockedKind | null = null
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

/** Called by api/client.ts when a response carries a tenant-level block code. */
export function reportTenantBlocked(errorCode: string): void {
  const next: TenantBlockedKind | null = KIND_BY_CODE[errorCode] ?? null
  if (next && next !== blocked) {
    blocked = next
    emit()
  }
}

/** Cleared on every session transition (login/logout) — see App.tsx. */
export function clearTenantBlocked(): void {
  if (blocked !== null) {
    blocked = null
    emit()
  }
}

export function getTenantBlocked(): TenantBlockedKind | null {
  return blocked
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useTenantBlocked(): TenantBlockedKind | null {
  return useSyncExternalStore(subscribe, getTenantBlocked)
}
