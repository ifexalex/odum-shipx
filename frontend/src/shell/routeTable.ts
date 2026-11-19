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
  { path: '/login', allow: 'public', title: 'Sign In', layout: 'none' },
  { path: '/register', allow: 'public', title: 'Register', layout: 'none' },
  { path: '/register/:slug', allow: 'public', title: 'Register', layout: 'none' },
  { path: '/invite/:token', allow: 'public', title: 'Create Your Account', layout: 'none' },
  { path: '/activate/:token', allow: 'public', title: 'Activate Your Account', layout: 'none' },
  { path: '/forgot-password', allow: 'public', title: 'Forgot Password', layout: 'none' },
  { path: '/reset-password', allow: 'public', title: 'Reset Password', layout: 'none' },
  { path: '/track', allow: 'public', title: 'Track Shipment', layout: 'none' },
  { path: '/track/:code', allow: 'public', title: 'Track Shipment', layout: 'none' },
  // Shipping-company onboarding request (a lead — NOT customer sign-up; no
  // account is created here). See RequestOnboardingScreen.
  { path: '/get-started', allow: 'public', title: 'Partner with ShipX', layout: 'none' },
  // Entra interactive-login redirect target (BFF auth-code callback).
  { path: '/auth/callback', allow: 'public', title: 'Signing in', layout: 'none' },

  // Platform admin
  { path: '/platform/dashboard', allow: ['platform_admin'], title: 'Platform Dashboard', layout: 'staff' },
  { path: '/platform/onboarding-requests', allow: ['platform_admin'], title: 'Onboarding Requests', layout: 'staff' },
  { path: '/platform/tenants', allow: ['platform_admin'], title: 'Tenants', layout: 'staff', crumb: 'Tenants' },
  { path: '/platform/tenants/new', allow: ['platform_admin'], title: 'Create Tenant', layout: 'staff', parent: '/platform/tenants', crumb: 'New tenant' },
  { path: '/platform/tenants/:id', allow: ['platform_admin'], title: 'Tenant Detail', layout: 'staff', parent: '/platform/tenants', crumb: 'Tenant' },
  { path: '/platform/settings', allow: ['platform_admin'], title: 'Platform Settings', layout: 'staff', crumb: 'Settings' },
  {
    path: '/platform/settings/notifications',
    allow: ['platform_admin'],
    title: 'Platform Notifications',
    layout: 'staff',
    parent: '/platform/settings',
    crumb: 'Notifications',
  },
  { path: '/platform/settings/plans', allow: ['platform_admin'], title: 'Platform Plans', layout: 'staff', parent: '/platform/settings', crumb: 'Plans' },
  { path: '/platform/audit-log', allow: ['platform_admin'], title: 'Platform Audit Log', layout: 'staff' },

  // Tenant admin
  { path: '/dashboard', allow: ['tenant_admin', 'nigeria_office_staff'], title: 'Dashboard', layout: 'staff' },
  // The China office's home: rejected and draft packing lists, unverified manifests, escalated disputes (UX-10).
  { path: '/work-queue', allow: ['china_office_staff'], title: 'Work queue', layout: 'staff' },
  { path: '/admin/users', allow: ['tenant_admin'], title: 'Staff Users', layout: 'staff', crumb: 'Staff' },
  { path: '/admin/users/:id', allow: ['tenant_admin'], title: 'Staff User Profile', layout: 'staff', parent: '/admin/users', crumb: 'Staff member' },
  { path: '/admin/customers', allow: ['tenant_admin'], title: 'Customers', layout: 'staff', crumb: 'Customers' },
  { path: '/admin/customers/:id', allow: ['tenant_admin'], title: 'Customer Profile', layout: 'staff', parent: '/admin/customers', crumb: 'Customer' },
  { path: '/admin/config', allow: ['tenant_admin'], title: 'Company Settings', layout: 'staff', crumb: 'Configuration' },
  { path: '/admin/config/dollar-rate', allow: ['tenant_admin'], title: 'Dollar Rate', layout: 'staff', parent: '/admin/config', crumb: 'Dollar rate' },
  { path: '/admin/config/cbm-rate', allow: ['tenant_admin'], title: 'CBM Rate', layout: 'staff', parent: '/admin/config', crumb: 'CBM rate' },
  { path: '/admin/config/charge-types', allow: ['tenant_admin'], title: 'Charge Types', layout: 'staff', parent: '/admin/config', crumb: 'Charge types' },
  { path: '/admin/config/container-capacities', allow: ['tenant_admin'], title: 'Container Capacities', layout: 'staff', parent: '/admin/config', crumb: 'Container capacities' },
  { path: '/admin/config/warehouses', allow: ['tenant_admin'], title: 'Warehouses', layout: 'staff', parent: '/admin/config', crumb: 'Warehouses' },
  { path: '/admin/config/notifications', allow: ['tenant_admin'], title: 'Notification Templates', layout: 'staff', parent: '/admin/config', crumb: 'Notification templates' },
  { path: '/admin/config/webhooks', allow: ['tenant_admin'], title: 'Webhook Configuration', layout: 'staff', parent: '/admin/config', crumb: 'Webhooks' },
  { path: '/admin/config/payments', allow: ['tenant_admin'], title: 'Payment Gateway', layout: 'staff', parent: '/admin/config', crumb: 'Payments' },
  { path: '/admin/reports', allow: ['tenant_admin'], title: 'Reports', layout: 'staff' },
  { path: '/admin/notifications/log', allow: ['tenant_admin'], title: 'Notification Log', layout: 'staff' },
  { path: '/admin/activity-log', allow: ['tenant_admin'], title: 'Activity Log', layout: 'staff' },
  {
    path: '/announcements',
    allow: ['tenant_admin', 'nigeria_office_staff'],
    title: 'Announcements',
    layout: 'staff',
  },
  {
    path: '/profile',
    allow: ['platform_admin', 'tenant_admin', 'china_office_staff', 'nigeria_office_staff', 'warehouse_attendant'],
    title: 'My Profile',
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
  { path: '/containers/new', allow: ['china_office_staff'], title: 'Create Container', layout: 'staff', parent: '/containers', crumb: 'New container' },
  {
    path: '/containers/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Container Detail',
    layout: 'staff',
    parent: '/containers',
    crumb: 'Container',
  },
  {
    path: '/packing-lists',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Packing Lists',
    layout: 'staff',
    crumb: 'Packing lists',
  },
  { path: '/packing-lists/new', allow: ['china_office_staff'], title: 'Create Packing List', layout: 'staff', parent: '/packing-lists', crumb: 'New packing list' },
  { path: '/packing-lists/:id/edit', allow: ['china_office_staff'], title: 'Edit Packing List', layout: 'staff', parent: '/packing-lists/:id', crumb: 'Edit' },
  { path: '/packing-lists/import', allow: ['china_office_staff'], title: 'Bulk Import', layout: 'staff', parent: '/packing-lists', crumb: 'Import from Excel' },
  {
    path: '/packing-lists/:id/print',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Print Packing List',
    layout: 'none',
  },
  {
    path: '/packing-lists/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'Packing List Detail',
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
    title: 'Manifest Detail',
    layout: 'staff',
    parent: '/manifests',
    crumb: 'Manifest',
  },

  // Billing & disputes
  { path: '/billing', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Billing', layout: 'staff', crumb: 'Billing' },
  {
    path: '/billing/disputes',
    allow: ['nigeria_office_staff', 'tenant_admin', 'china_office_staff'],
    title: 'CBM Disputes',
    layout: 'staff',
    parent: '/billing',
    crumb: 'CBM disputes',
  },
  // Nigeria staff and admins manage a dispute inline on BillingDetail (DisputeCard). China staff are asked
  // to resolve disputes but may not open invoices, so they get this measurement-only screen instead (UX-01).
  {
    path: '/billing/disputes/:id',
    allow: ['china_office_staff', 'nigeria_office_staff', 'tenant_admin'],
    title: 'CBM Dispute',
    layout: 'staff',
    parent: '/billing/disputes',
    crumb: 'Dispute',
  },
  { path: '/billing/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Billing Detail', layout: 'staff', parent: '/billing', crumb: 'Invoice' },
  {
    path: '/billing/carryovers',
    allow: ['nigeria_office_staff', 'tenant_admin'],
    title: 'Carryover Ledger',
    layout: 'staff',
    parent: '/billing',
    crumb: 'Carryover ledger',
  },

  // Claims & refunds
  { path: '/claims', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Damage Claims', layout: 'staff', crumb: 'Damage claims' },
  { path: '/claims/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Claim Detail', layout: 'staff', parent: '/claims', crumb: 'Claim' },
  {
    path: '/claims/missing-items',
    // China staff record the supply and loading check on a missing item (UX-08); they get no other claims route.
    allow: ['nigeria_office_staff', 'tenant_admin', 'china_office_staff'],
    title: 'Missing Items',
    layout: 'staff',
  },
  {
    path: '/claims/seized-items',
    allow: ['nigeria_office_staff', 'tenant_admin'],
    title: 'Seized Items',
    layout: 'staff',
  },
  { path: '/refunds', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Refund Requests', layout: 'staff', crumb: 'Refunds' },
  { path: '/refunds/:id', allow: ['nigeria_office_staff', 'tenant_admin'], title: 'Refund Detail', layout: 'staff', parent: '/refunds', crumb: 'Refund' },

  // Release notes & warehouse
  {
    path: '/release-notes',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Release Notes',
    layout: 'staff',
    crumb: 'Release notes',
  },
  {
    path: '/release-notes/:id',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Release Note Detail',
    layout: 'staff',
    parent: '/release-notes',
    crumb: 'Release note',
  },
  {
    path: '/release-notes/:id/print',
    allow: ['nigeria_office_staff', 'tenant_admin', 'warehouse_attendant'],
    title: 'Print Release Note',
    layout: 'none',
  },
  { path: '/warehouse', allow: ['warehouse_attendant'], title: 'Warehouse', layout: 'staff' },

  // Customer portal
  { path: '/my-shipments', allow: ['customer'], title: 'My Shipments', layout: 'customer', crumb: 'My shipments' },
  { path: '/my-shipments/:code', allow: ['customer'], title: 'Shipment Detail', layout: 'customer', parent: '/my-shipments', crumb: 'Shipment' },
  { path: '/my-billing', allow: ['customer'], title: 'My Billing', layout: 'customer', crumb: 'Billing' },
  { path: '/my-billing/:id', allow: ['customer'], title: 'Billing Detail', layout: 'customer', parent: '/my-billing', crumb: 'Invoice' },
  { path: '/my-release-notes/:id', allow: ['customer'], title: 'Release Note', layout: 'customer', parent: '/my-shipments', crumb: 'Release note' },
  { path: '/my-billing/:id/payment-success', allow: ['customer'], title: 'Payment Successful', layout: 'customer', parent: '/my-billing/:id', crumb: 'Payment received' },
  { path: '/payment-failed', allow: ['customer'], title: 'Payment Failed', layout: 'customer', parent: '/my-billing', crumb: 'Payment failed' },
  { path: '/my-billing/:id/refund-request', allow: ['customer'], title: 'Refund Request', layout: 'customer', parent: '/my-billing/:id', crumb: 'Request a refund' },
  { path: '/my-claims', allow: ['customer'], title: 'My Claims', layout: 'customer', crumb: 'Claims' },
  { path: '/my-claims/new', allow: ['customer'], title: 'File a Claim', layout: 'customer', parent: '/my-claims', crumb: 'New claim' },
  { path: '/my-claims/:id', allow: ['customer'], title: 'Claim', layout: 'customer', parent: '/my-claims', crumb: 'Claim' },
  { path: '/account', allow: ['customer'], title: 'Account', layout: 'customer' },
]
