import type { UserRole } from '../auth/types'
import type { IconName } from '../design/components'
import type { Role } from '../design/theme'

export interface NavLinkDef {
  icon?: IconName
  label: string
  path: string
  count?: string | number
}

export interface NavLinkGroup {
  group?: string
  items: NavLinkDef[]
}

// UserRole (backend JWT role enum) -> Role (visual tint used by Sidebar/Avatar,
// theme.ts) — kept distinct on purpose (see auth/types.ts), this is the one
// place they're mapped together.
const VISUAL_ROLE: Record<UserRole, Role> = {
  platform_admin: 'platform',
  tenant_admin: 'admin',
  china_office_staff: 'china',
  nigeria_office_staff: 'nigeria',
  warehouse_attendant: 'warehouse',
  customer: 'customer',
}

export function visualRoleFor(role: UserRole): Role {
  return VISUAL_ROLE[role]
}

// Reverse lookup: which of a multi-role user's assigned roles "owns" the current
// path in its nav tree? Used to keep the active-role selector in sync with the
// actual page after a reload or a direct/bookmarked navigation — the active role
// is UI-only state and is deliberately never persisted (no localStorage/sessionStorage
// in src/auth/, see 11_security_and_compliance.md), so a reload always rebuilds
// `session.role` from the JWT's primary role, which can disagree with whatever
// route the URL still points at. Prefers the currently-active role when its own
// nav already contains the path (avoids flip-flopping on routes shared across
// several of the user's roles, e.g. /billing for tenant_admin + nigeria_office_staff).
export function roleForPath(pathname: string, roles: UserRole[], preferred: UserRole): UserRole | null {
  const ownsPath = (role: UserRole): boolean =>
    navConfig[role].some((group) =>
      group.items.some((item) => pathname === item.path || pathname.startsWith(`${item.path}/`)),
    )
  if (roles.includes(preferred) && ownsPath(preferred)) return preferred
  return roles.find(ownsPath) ?? null
}

// One declarative nav tree per role — Sidebar/CustomerTopNav render this data,
// and routeTable.ts's `allow` lists are the guard for the same paths, so "what's
// in the nav" and "what's actually reachable" can't drift apart
// (06_routing_rbac_and_navigation.md).
const OPERATIONS_GROUP: NavLinkGroup = {
  group: 'Operations',
  items: [
    { icon: 'container', label: 'Containers', path: '/containers' },
    { icon: 'package', label: 'Packing Lists', path: '/packing-lists' },
    { icon: 'file', label: 'Manifests', path: '/manifests' },
  ],
}

const BILLING_CLAIMS_GROUP: NavLinkGroup = {
  group: 'Billing & Disputes',
  items: [
    { icon: 'coin', label: 'Billing', path: '/billing' },
    { icon: 'warn', label: 'Claims', path: '/claims' },
    { icon: 'package', label: 'Missing Items', path: '/claims/missing-items' },
    { icon: 'warn', label: 'Seized Items', path: '/claims/seized-items' },
    { icon: 'card', label: 'Refunds', path: '/refunds' },
    { icon: 'file', label: 'Release Notes', path: '/release-notes' },
  ],
}

export const navConfig: Record<UserRole, NavLinkGroup[]> = {
  platform_admin: [
    {
      items: [
        { icon: 'grid', label: 'Dashboard', path: '/platform/dashboard' },
        { icon: 'mail', label: 'Onboarding Requests', path: '/platform/onboarding-requests' },
        { icon: 'building', label: 'Tenants', path: '/platform/tenants' },
        { icon: 'settings', label: 'Settings', path: '/platform/settings' },
        { icon: 'log', label: 'Audit Log', path: '/platform/audit-log' },
      ],
    },
  ],
  tenant_admin: [
    {
      items: [
        { icon: 'grid', label: 'Dashboard', path: '/dashboard' },
        { icon: 'users', label: 'Users', path: '/admin/users' },
        { icon: 'user', label: 'Customers', path: '/admin/customers' },
        { icon: 'settings', label: 'Configuration', path: '/admin/config' },
        { icon: 'chart', label: 'Reports', path: '/admin/reports' },
        { icon: 'bell', label: 'Notifications', path: '/admin/notifications/log' },
        { icon: 'bell', label: 'Announcements', path: '/announcements' },
        { icon: 'log', label: 'Activity Log', path: '/admin/activity-log' },
      ],
    },
    OPERATIONS_GROUP,
    BILLING_CLAIMS_GROUP,
  ],
  china_office_staff: [
    { items: [{ icon: 'grid', label: 'Work queue', path: '/work-queue' }] },
    {
      group: 'Operations',
      items: [
        { icon: 'container', label: 'Containers', path: '/containers' },
        { icon: 'plus', label: 'Create container', path: '/containers/new' },
      ],
    },
    {
      group: 'Packing lists',
      items: [
        { icon: 'package', label: 'All packing lists', path: '/packing-lists' },
        { icon: 'plus', label: 'Create packing list', path: '/packing-lists/new' },
        { icon: 'upload', label: 'Import from Excel', path: '/packing-lists/import' },
      ],
    },
    {
      group: 'Coordination',
      items: [
        { icon: 'file', label: 'Manifests', path: '/manifests' },
        // china_office_staff can see & resolve CBM disputes (_DISPUTE_LIST_ALL_ROLES)
        { icon: 'warn', label: 'CBM disputes', path: '/billing/disputes' },
        // ...and record the supply and loading check on a missing item (UX-08)
        { icon: 'package', label: 'Missing items', path: '/claims/missing-items' },
      ],
    },
  ],
  nigeria_office_staff: [
    {
      items: [
        { icon: 'grid', label: 'Dashboard', path: '/dashboard' },
        { icon: 'bell', label: 'Announcements', path: '/announcements' },
      ],
    },
    // Nigeria staff own the arrived -> at_warehouse transitions and are allowed on both pages
    // (routeTable.ts), but the menu used to offer neither; they reached containers only through
    // dashboard cards. Manifests comes from this group, so it is no longer listed twice.
    OPERATIONS_GROUP,
    BILLING_CLAIMS_GROUP,
  ],
  warehouse_attendant: [
    {
      items: [
        { icon: 'package', label: 'Warehouse', path: '/warehouse' },
        { icon: 'file', label: 'Release Notes', path: '/release-notes' },
      ],
    },
  ],
  customer: [
    {
      items: [
        { icon: 'package', label: 'My Shipments', path: '/my-shipments' },
        { icon: 'coin', label: 'Billing', path: '/my-billing' },
        { icon: 'warn', label: 'Claims', path: '/my-claims' },
        { icon: 'user', label: 'Account', path: '/account' },
      ],
    },
  ],
}
