import type { UserRole } from './types'

// Single source of truth for "where does this role land" — used by
// LoginScreen's post-login redirect and by RoleGuard's wrong-role redirect,
// so the two can never drift out of sync (06_routing_rbac_and_navigation.md).
const ROLE_HOME: Record<UserRole, string> = {
  platform_admin: '/platform/dashboard',
  tenant_admin: '/dashboard',
  china_office_staff: '/work-queue',
  nigeria_office_staff: '/dashboard',
  warehouse_attendant: '/warehouse',
  customer: '/my-shipments',
}

export function homePathForRole(role: UserRole): string {
  return ROLE_HOME[role]
}
