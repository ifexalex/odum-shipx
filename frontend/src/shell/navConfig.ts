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
//
// FD-15: sentence case; within a role no two items share an icon; "Create …" pages are not menu items (each list
// page's header has that button); the tenant admin's menu is grouped Overview, Operations, Billing and claims, Admin.
const OPERATIONS_GROUP: NavLinkGroup = {
  group: 'Operations',
  items: [
    { icon: 'container', label: 'Containers', path: '/containers' },
    { icon: 'package', label: 'Packing lists', path: '/packing-lists' },
    { icon: 'file', label: 'Manifests', path: '/manifests' },
  ],
}

const BILLING_CLAIMS_GROUP: NavLinkGroup = {
  group: 'Billing and claims',
  items: [
    { icon: 'coin', label: 'Billing', path: '/billing' },
    { icon: 'alert', label: 'Damage claims', path: '/claims' },
    { icon: 'search', label: 'Missing items', path: '/claims/missing-items' },
    { icon: 'shield', label: 'Seized items', path: '/claims/seized-items' },
    { icon: 'refresh', label: 'Refunds', path: '/refunds' },
    { icon: 'qr', label: 'Release notes', path: '/release-notes' },
  ],
}

/**
 * The platform console's 8 areas, in sidebar order (platform audit target design, Phase 1c). An area with no page built
 * yet is left out rather than shown empty: Revenue arrives in Phase 4, Operations in Phase 3, Support in Phases 2–3.
 * Plans and limits has its own area; its page is still the Plans tab of Platform settings until Phase 4.
 */
export const PLATFORM_AREAS: NavLinkGroup[] = [
  { group: 'Overview', items: [{ icon: 'grid', label: 'Overview', path: '/platform/dashboard' }] },
  {
    group: 'Tenants',
    items: [
      { icon: 'building', label: 'Tenants', path: '/platform/tenants' },
      { icon: 'mail', label: 'Onboarding requests', path: '/platform/onboarding-requests' },
    ],
  },
  { group: 'Revenue', items: [] },
  { group: 'Plans', items: [{ icon: 'pie', label: 'Plans and limits', path: '/platform/settings/plans' }] },
  { group: 'Operations', items: [] },
  { group: 'Support', items: [] },
  {
    group: 'Security',
    items: [
      { icon: 'check', label: 'Approvals', path: '/platform/approvals' },
      { icon: 'users', label: 'Platform admins', path: '/platform/admins' },
      { icon: 'log', label: 'Audit log', path: '/platform/audit-log' },
    ],
  },
  { group: 'Settings', items: [{ icon: 'settings', label: 'Settings', path: '/platform/settings' }] },
]

export const navConfig: Record<UserRole, NavLinkGroup[]> = {
  platform_admin: PLATFORM_AREAS.filter((area) => area.items.length > 0),
  tenant_admin: [
    {
      group: 'Overview',
      items: [
        { icon: 'grid', label: 'Dashboard', path: '/dashboard' },
        { icon: 'chart', label: 'Reports', path: '/admin/reports' },
        { icon: 'clock', label: 'Activity log', path: '/admin/activity-log' },
      ],
    },
    OPERATIONS_GROUP,
    BILLING_CLAIMS_GROUP,
    {
      group: 'Admin',
      items: [
        { icon: 'users', label: 'Staff', path: '/admin/users' },
        { icon: 'user', label: 'Customers', path: '/admin/customers' },
        { icon: 'bell', label: 'Announcements', path: '/announcements' },
        { icon: 'mail', label: 'Notification log', path: '/admin/notifications/log' },
        { icon: 'settings', label: 'Settings', path: '/admin/config' },
      ],
    },
  ],
  china_office_staff: [
    { group: 'Overview', items: [{ icon: 'grid', label: 'Work queue', path: '/work-queue' }] },
    OPERATIONS_GROUP,
    {
      group: 'Coordination',
      items: [
        // china_office_staff can see & resolve CBM disputes (_DISPUTE_LIST_ALL_ROLES)
        { icon: 'warn', label: 'CBM disputes', path: '/billing/disputes' },
        // ...and record the supply and loading check on a missing item (UX-08)
        { icon: 'search', label: 'Missing items', path: '/claims/missing-items' },
      ],
    },
  ],
  nigeria_office_staff: [
    {
      group: 'Overview',
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
        { icon: 'building', label: 'Warehouse', path: '/warehouse' },
        { icon: 'qr', label: 'Release notes', path: '/release-notes' },
      ],
    },
  ],
  customer: [
    {
      items: [
        { icon: 'ship', label: 'My shipments', path: '/my-shipments' },
        { icon: 'coin', label: 'Billing', path: '/my-billing' },
        { icon: 'alert', label: 'Claims', path: '/my-claims' },
        { icon: 'user', label: 'Account', path: '/account' },
      ],
    },
  ],
}

/**
 * The menu item for `pathname`: the longest item path that is the page or one of its parents, so
 * `/claims/missing-items` lights Missing items and not Damage claims too, and `/packing-lists/new` lights Packing
 * lists. Null when no item covers the page.
 */
export function activeNavPath(pathname: string, paths: readonly string[]): string | null {
  let best: string | null = null
  for (const path of paths) {
    if ((pathname === path || pathname.startsWith(`${path}/`)) && (!best || path.length > best.length)) best = path
  }
  return best
}
