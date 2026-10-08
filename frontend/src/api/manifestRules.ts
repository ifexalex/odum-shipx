import type { UserRole } from '../auth/types'
import type { Manifest } from './manifest'

// Ground truth: services/manifest/handler.py's _VERIFY_ROLES/_RESOLVE_ROLES.
// Note china_office_staff can verify (it owns the China-side packing-list
// approval that triggers manifest creation) but cannot resolve a logged
// discrepancy — that's Nigeria-side warehouse/admin territory.
const VERIFY_ROLES: UserRole[] = ['china_office_staff', 'nigeria_office_staff']
const RESOLVE_ROLES: UserRole[] = ['nigeria_office_staff', 'tenant_admin']
const REVOKE_ROLES: UserRole[] = ['china_office_staff', 'nigeria_office_staff', 'tenant_admin']

export function canVerifyManifest(manifest: Manifest, role: UserRole): boolean {
  return manifest.verification_status === 'pending' && VERIFY_ROLES.includes(role)
}

export function canResolveDiscrepancy(manifest: Manifest, role: UserRole): boolean {
  return manifest.verification_status === 'discrepancies_found' && RESOLVE_ROLES.includes(role)
}

export function canRevokeVerification(manifest: Manifest, role: UserRole): boolean {
  // Verification can only be revoked while the container is still in 'loading' —
  // once sealed, the physical container has left and the manifest is locked in.
  const containerStillLoading = manifest.container_status === 'loading' || manifest.container_status == null
  return manifest.verification_status === 'verified' && containerStillLoading && REVOKE_ROLES.includes(role)
}

// B11 — a manifest is overdue when it's still awaiting verification while its
// container has already reached Nigeria: the cargo is here but the manifest
// hasn't been checked, which blocks billing + release. Derived from real
// fields (no separate SLA endpoint). Shared by ManifestList and the Nigeria
// dashboard "awaiting verification" queue (P2-5).
export const ARRIVED_IN_NG = new Set(['arrived', 'customs_clearance', 'cleared', 'at_warehouse'])

export function isManifestOverdue(manifest: Manifest): boolean {
  return (
    manifest.verification_status === 'pending' &&
    !!manifest.container_status &&
    ARRIVED_IN_NG.has(manifest.container_status)
  )
}
