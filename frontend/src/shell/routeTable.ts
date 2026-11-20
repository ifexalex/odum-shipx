import type { UserRole } from '../auth/types'

export type RouteLayout = 'staff' | 'customer' | 'none'

export interface RouteDef {
  path: string
  /** 'public' means no RoleGuard at all — rendered outside any auth check. */
  allow: UserRole[] | 'public'
  title: string
  layout: RouteLayout
  /**
   * The page this one sits under in the breadcrumb (FD-45/46), e.g. `/billing/:id` under `/billing`. Absent for a
   * top-level page, which shows no breadcrumb. Parameters are filled from the current URL, so `/packing-lists/:id/edit`
   * links back to the same list.
   */
  parent?: string
  /**
   * The page's name in a breadcrumb, short and in sentence case ("New container", "Dollar rate"). For a record page
   * it is the fallback until the page supplies the record's own label (`useBreadcrumbLabel`). Defaults to `title`.
   */
  crumb?: string
}

// One declarative table — every route in 06_routing_rbac_and_navigation.md's
// per-role tables, plus its guard and layout — so a route's existence, its
// guard list, and which shell it renders inside can never drift apart the
// way three hand-maintained lists would. routes.tsx maps over this; nothing
// else hand-builds <Route> elements.
//
// Judgment calls made resolving ambiguity in the source doc (flagged here,
// not silently assumed):
// - `/dashboard` is listed only under the Tenant Admin table, but the
//   Nigeria Office sidebar prose also lists "Dashboard" as its first item —
//   allowed for both roles.
// - The Operations/Release Notes tables list "customer (own)" as a reader of
//   `/packing-lists/:id` and `/release-notes(/:id)`, but the Customer Portal
//   table doesn't repeat these paths — customers reach the same data through
//   their own `/my-shipments/:code` (customer layout), not these staff-layout
//   routes. Customer is deliberately *not* in `allow` here, so a customer
//   can never land inside the staff sidebar shell (AC: customer portal must
//   stay on the horizontal top-nav layout, never the staff one).
export const routeTable: RouteDef[] = [
  // Public
  { path: '/login', allow: 'public', title: 'Sign in', layout: 'none' },
  { path: '/register', allow: 'public', title: 'Register', layout: 'none' },
  { path: '/register/:slug', allow: 'public', title: 'Register', layout: 'none' },
  { path: '/invite/:token', allow: 'public', title: 'Create your account', layout: 'none' },
  { path: '/activate/:token', allow: 'public', title: 'Activate your account', layout: 'none' },
  { path: '/forgot-password', allow: 'public', title: 'Forgot password', layout: 'none' },
  { path: '/reset-password', allow: 'public', title: 'Reset password', layout: 'none' },
  { path: '/track', allow: 'public', title: 'Track a shipment', layout: 'none' },
  { path: '/track/:code', allow: 'public', title: 'Track a shipment', layout: 'none' },
  // Shipping-company onboarding request (a lead — NOT customer sign-up; no
  // account is created here). See RequestOnboardingScreen.
  { path: '/get-started', allow: 'public', title: 'Partner with ShipX', layout: 'none' },
  // Entra interactive-login redirect target (BFF auth-code callback).
  { path: '/auth/callback', allow: 'public', title: 'Signing in', layout: 'none' },

  // Platform admin
  { path: '/platform/dashboard', allow: ['platform_admin'], title: 'Platform dashboard', layout: 'staff' },
  { path: '/platform/onboarding-requests', allow: ['platform_admin'], title: 'Onboarding requests', layout: 'staff' },
  { path: '/platform/tenants', allow: ['platform_admin'], title: 'Tenants', layout: 'staff', crumb: 'Tenants' },
  { path: '/platform/tenants/new', allow: ['platform_admin'], title: 'New tenant', layout: 'staff', parent: '/platform/tenants', crumb: 'New tenant' },
  { path: '/platform/tenants/:id', allow: ['platform_admin'], title: 'Tenant', layout: 'staff', parent: '/platform/tenants', crumb: 'Tenant' },
  { path: '/platform/settings', allow: ['platform_admin'], title: 'Platform settings', layout: 'staff', crumb: 'Settings' },
  {
    path: '/platform/settings/notifications',
    allow: ['platform_admin'],
    title: 'Platform notification settings',
    layout: 'staff',
    parent: '/platform/settings',
    crumb: 'Notifications',
  },
  { path: '/platform/settings/plans', allow: ['platform_admin'], title: 'Plans', layout: 'staff', parent: '/platform/settings', crumb: 'Plans' },
  { path: '/platform/audit-log', allow: ['platform_admin'], title: 'Audit log', layout: 'staff' },

  // Tenant admin
  { path: '/dashboard', allow: ['tenant_admin', 'nigeria_office_staff'], title: 'Dashboard', layout: 'staff' },
  // The China office's home: rejected and draft packing lists, unverified manifests, escalated disputes (UX-10).
  { path: '/work-queue', allow: ['china_office_staff'], title: 'Work queue', layout: 'staff' },
  { path: '/admin/users', allow: ['tenant_admin'], title: 'Staff', layout: 'staff', crumb: 'Staff' },
  { path: '/admin/users/:id', allow: ['tenant_admin'], title: 'Staff member', layout: 'staff', parent: '/admin/users', crumb: 'Staff member' },
  { path: '/admin/customers', allow: ['tenant_admin'], title: 'Customers', layout: 'staff', crumb: 'Customers' },
  { path: '/admin/customers/:id', allow: ['tenant_admin'], title: 'Customer', layout: 'staff', parent: '/admin/customers', crumb: 'Customer' },
  { path: '/admin/config', allow: ['tenant_admin'], title: 'Company settings', layout: 'staff', crumb: 'Settings' },
  { path: '/admin/config/dollar-rate', allow: ['tenant_admin'], title: 'Dollar rate', layout: 'staff', parent: '/admin/config', crumb: 'Dollar rate' },
  { path: '/admin/config/cbm-rate', allow: ['tenant_admin'], title: 'CBM rate', layout: 'staff', parent: '/admin/config', crumb: 'CBM rate' },
  { path: '/admin/config/charge-types', allow: ['tenant_admin'], title: 'Charge types', layout: 'staff', parent: '/admin/config', crumb: 'Charge types' },
  { path: '/admin/config/container-capacities', allow: ['tenant_admin'], title: 'Container capacities', layout: 'staff', parent: '/admin/config', crumb: 'Container capacities' },
  { path: '/admin/config/warehouses', allow: ['tenant_admin'], title: 'Warehouses', layout: 'staff', parent: '/admin/config', crumb: 'Warehouses' },
  { path: '/admin/config/notifications', allow: ['tenant_admin'], title: 'Notification templates', layout: 'staff', parent: '/admin/config', crumb: 'Notification templates' },
  { path: '/admin/config/webhooks', allow: ['tenant_admin'], title: 'Webhooks', layout: 'staff', parent: '/admin/config', crumb: 'Webhooks' },
  { path: '/admin/config/payments', allow: ['tenant_admin'], title: 'Payments', layout: 'staff', parent: '/admin/config', crumb: 'Payments' },
  { path: '/admin/reports', allow: ['tenant_admin'], title: 'Reports', layout: 'staff' },
  { path: '/admin/notifications/log', allow: ['tenant_admin'], title: 'Notification log', layout: 'staff' },
  { path: '/admin/activity-log', allow: ['tenant_admin'], title: 'Activity log', layout: 'staff' },
  {
    path: '/announcements',
    allow: ['tenant_admin', 'nigeria_office_staff'],
    title: 'Announcements',
    layout: 'staff',
  },
  {
    path: '/profile',
    allow: ['platform_admin', 'tenant_admin', 'china_office_staff', 'nigeria_office_staff', 'warehouse_attendant'],
    title: 'My profile',
    layout: 'staff',
  },

  // Operations — containers, packing lists, manifests
  {
    path: '/containers',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Containers',
    layout: 'staff',
    crumb: 'Containers',
  },
  { path: '/containers/new', allow: ['china_office_staff'], title: 'New container', layout: 'staff', parent: '/containers', crumb: 'New container' },
  {
    path: '/containers/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Container',
    layout: 'staff',
    parent: '/containers',
    crumb: 'Container',
  },
  {
    path: '/packing-lists',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Packing lists',
    layout: 'staff',
    crumb: 'Packing lists',
  },
  { path: '/packing-lists/new', allow: ['china_office_staff'], title: 'New packing list', layout: 'staff', parent: '/packing-lists', crumb: 'New packing list' },
  { path: '/packing-lists/:id/edit', allow: ['china_office_staff'], title: 'Edit packing list', layout: 'staff', parent: '/packing-lists/:id', crumb: 'Edit' },
  { path: '/packing-lists/import', allow: ['china_office_staff'], title: 'Import packing lists', layout: 'staff', parent: '/packing-lists', crumb: 'Import from Excel' },
  {
    path: '/packing-lists/:id/print',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Print packing list',
    layout: 'none',
  },
  {
    path: '/packing-lists/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Packing list',
    layout: 'staff',
    parent: '/packing-lists',
    crumb: 'Packing list',
  },
  {
    path: '/manifests',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Manifests',
    layout: 'staff',
    crumb: 'Manifests',
  },
  {
    path: '/manifests/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Manifest',
    layout: 'staff',
    parent: '/manifests',
    crumb: 'Manifest',
  },

  // Billing & disputes
  { path: '/billing', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Billing', layout: 'staff', crumb: 'Billing' },
  {
    path: '/billing/disputes',
    allow: ['nigeria_office_staff', 'tenant_admin', 'china_office_staff'],
    title: 'CBM disputes',
    layout: 'staff',
    parent: '/billing',
    crumb: 'CBM disputes',
  },
  // Nigeria staff and admins manage a dispute inline on BillingDetail (DisputeCard). China staff are asked
  // to resolve disputes but may not open invoices, so they get this measurement-only screen instead (UX-01).
  {
    path: '/billing/disputes/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'CBM dispute',
    layout: 'staff',
    parent: '/billing/disputes',
    crumb: 'Dispute',
  },
  { path: '/billing/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Invoice', layout: 'staff', parent: '/billing', crumb: 'Invoice' },
  {
    path: '/billing/carryovers',
    allow: ['nigeria_office_staff', 'tenant_admin'],
    title: 'Carryover ledger',
    layout: 'staff',
    parent: '/billing',
    crumb: 'Carryover ledger',
  },

  // Claims & refunds
  { path: '/claims', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Damage claims', layout: 'staff', crumb: 'Damage claims' },
  { path: '/claims/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Damage claim', layout: 'staff', parent: '/claims', crumb: 'Claim' },
  {
    path: '/claims/missing-items',
    // China staff record the supply and loading check on a missing item (UX-08); they get no other claims route.
    allow: ['nigeria_office_staff', 'tenant_admin', 'china_office_staff'],
    title: 'Missing items',
    layout: 'staff',
  },
  {
    path: '/claims/seized-items',
    allow: ['nigeria_office_staff', 'tenant_admin'],
    title: 'Seized items',
    layout: 'staff',
  },
  { path: '/refunds', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Refunds', layout: 'staff', crumb: 'Refunds' },
  { path: '/refunds/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Refund', layout: 'staff', parent: '/refunds', crumb: 'Refund' },

  // Release notes & warehouse
  {
    path: '/release-notes',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Release notes',
    layout: 'staff',
    crumb: 'Release notes',
  },
  {
    path: '/release-notes/:id',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Release note',
    layout: 'staff',
    parent: '/release-notes',
    crumb: 'Release note',
  },
  {
    path: '/release-notes/:id/print',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Print release note',
    layout: 'none',
  },
  { path: '/warehouse', allow: ['warehouse_attendant'], title: 'Warehouse', layout: 'staff' },

  // Customer portal
  { path: '/my-shipments', allow: ['customer'], title: 'My shipments', layout: 'customer', crumb: 'My shipments' },
  { path: '/my-shipments/:code', allow: ['customer'], title: 'Shipment', layout: 'customer', parent: '/my-shipments', crumb: 'Shipment' },
  { path: '/my-billing', allow: ['customer'], title: 'My billing', layout: 'customer', crumb: 'Billing' },
  { path: '/my-billing/:id', allow: ['customer'], title: 'Invoice', layout: 'customer', parent: '/my-billing', crumb: 'Invoice' },
  { path: '/my-release-notes/:id', allow: ['customer'], title: 'Release note', layout: 'customer', parent: '/my-shipments', crumb: 'Release note' },
  { path: '/my-billing/:id/payment-success', allow: ['customer'], title: 'Payment received', layout: 'customer', parent: '/my-billing/:id', crumb: 'Payment received' },
  { path: '/payment-failed', allow: ['customer'], title: 'Payment failed', layout: 'customer', parent: '/my-billing', crumb: 'Payment failed' },
  { path: '/my-billing/:id/refund-request', allow: ['customer'], title: 'Request a refund', layout: 'customer', parent: '/my-billing/:id', crumb: 'Request a refund' },
  { path: '/my-claims', allow: ['customer'], title: 'My claims', layout: 'customer', crumb: 'Claims' },
  { path: '/my-claims/new', allow: ['customer'], title: 'New claim', layout: 'customer', parent: '/my-claims', crumb: 'New claim' },
  { path: '/my-claims/:id', allow: ['customer'], title: 'Claim', layout: 'customer', parent: '/my-claims', crumb: 'Claim' },
  { path: '/account', allow: ['customer'], title: 'Account', layout: 'customer' },
]
