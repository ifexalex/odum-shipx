/**
 * Query key factories — one per domain, following the TanStack Query key-factory pattern.
 *
 * Rules:
 * - NEVER include tenantId in any key. The API client scopes requests to the active session;
 *   the query cache is cleared entirely on tenant switch (App.tsx → SessionProvider.onSessionChange).
 * - Keys are typed `as const` so TypeScript enforces exact matches in invalidateQueries calls.
 * - Keep keys stable: changing a key format silently busts the cache and causes extra fetches.
 */

// ─── Containers ───────────────────────────────────────────────────────────────
export const containerKeys = {
  all: ['containers'] as const,
  list: (params?: Record<string, unknown>) => [...containerKeys.all, 'list', params ?? {}] as const,
  stats: () => [...containerKeys.all, 'stats'] as const,
  detail: (id: string) => [...containerKeys.all, 'detail', id] as const,
  events: (id: string) => [...containerKeys.all, 'detail', id, 'events'] as const,
  documents: (id: string) => [...containerKeys.all, 'detail', id, 'documents'] as const,
  // A flat one-shot read (a dashboard queue, a picker). Not `list()`: see releaseNoteKeys.lookup.
  lookup: (params?: Record<string, unknown>) => [...containerKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Packing lists ────────────────────────────────────────────────────────────
export const packingListKeys = {
  all: ['packing-lists'] as const,
  list: (params?: Record<string, unknown>) => [...packingListKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...packingListKeys.all, 'detail', id] as const,
  /**
   * A FLAT one-shot read, for a page that needs the whole set as a lookup
   * table rather than a paginated screen.
   *
   * Deliberately NOT `list()`. That key belongs to the `useCursorPagination`
   * hook for this domain, which is an INFINITE query caching
   * `{pages: ListResponse[], pageParams}`; a plain `useQuery` on the same key
   * caches a bare `ListResponse`. Whichever mounts first wins and the other
   * reads garbage. Still a child of `all`, so automatic invalidation reaches it.
   */
  lookup: (params?: Record<string, unknown>) => [...packingListKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Manifests ────────────────────────────────────────────────────────────────
export const manifestKeys = {
  all: ['manifests'] as const,
  list: (params?: Record<string, unknown>) => [...manifestKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...manifestKeys.all, 'detail', id] as const,
  stats: () => [...manifestKeys.all, 'stats'] as const,
  // A flat one-shot read (a dashboard queue, a picker). Not `list()`: see releaseNoteKeys.lookup.
  lookup: (params?: Record<string, unknown>) => [...manifestKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Billing ──────────────────────────────────────────────────────────────────
export const billingKeys = {
  all: ['billing'] as const,
  list: (params?: Record<string, unknown>) => [...billingKeys.all, 'list', params ?? {}] as const,
  stats: () => [...billingKeys.all, 'stats'] as const,
  unbilled: () => [...billingKeys.all, 'unbilled'] as const,
  report: (params?: Record<string, unknown>) => [...billingKeys.all, 'report', params ?? {}] as const,
  detail: (id: string) => [...billingKeys.all, 'detail', id] as const,
  forCustomer: (customerId: string) => [...billingKeys.all, 'customer', customerId] as const,
  // GET /v1/billing/carryovers — a child of billingKeys.all, which the
  // /v1/billing/carryovers/ invalidation rule already covers.
  carryovers: (params?: Record<string, unknown>) => [...billingKeys.all, 'carryovers', params ?? {}] as const,
  /**
   * A FLAT one-shot read of GET /v1/billing, for pages that only need a
   * lookup table (e.g. billing-by-container on the customer shipment pages).
   *
   * Deliberately NOT `list()`: that key belongs to `useBillingList`, which is
   * an infinite query and caches `{pages: ListResponse[], pageParams}`. A plain
   * `useQuery` on the same key caches a bare `ListResponse`, so the two
   * overwrite each other's shape and whichever reads second gets garbage —
   * `/my-shipments` then `/my-billing` crashed MyBilling exactly this way.
   */
  lookup: (params?: Record<string, unknown>) => [...billingKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Claims ───────────────────────────────────────────────────────────────────
export const disputeKeys = {
  all: ['disputes'] as const,
  list: (params?: Record<string, unknown>) => ['disputes', 'list', params ?? {}] as const,
  detail: (id: string) => ['disputes', 'detail', id] as const,
  // A flat one-shot read (a dashboard queue, a picker). Not `list()`: see releaseNoteKeys.lookup.
  lookup: (params?: Record<string, unknown>) => ['disputes', 'lookup', params ?? {}] as const,
}

export const seizedItemKeys = {
  all: ['seized-items'] as const,
  list: (params?: Record<string, unknown>) => ['seized-items', 'list', params ?? {}] as const,
  detail: (id: string) => ['seized-items', 'detail', id] as const,
}

export const missingItemKeys = {
  all: ['missing-items'] as const,
  list: (params?: Record<string, unknown>) => ['missing-items', 'list', params ?? {}] as const,
  detail: (id: string) => ['missing-items', 'detail', id] as const,
}

export const claimKeys = {
  all: ['claims'] as const,
  list: (params?: Record<string, unknown>) => [...claimKeys.all, 'list', params ?? {}] as const,
  stats: () => [...claimKeys.all, 'stats'] as const,
  detail: (id: string) => [...claimKeys.all, 'detail', id] as const,
  /**
   * A FLAT one-shot read, for a page that needs the whole set as a lookup
   * table rather than a paginated screen.
   *
   * Deliberately NOT `list()`. That key belongs to the `useCursorPagination`
   * hook for this domain, which is an INFINITE query caching
   * `{pages: ListResponse[], pageParams}`; a plain `useQuery` on the same key
   * caches a bare `ListResponse`. Whichever mounts first wins and the other
   * reads garbage. Still a child of `all`, so automatic invalidation reaches it.
   */
  lookup: (params?: Record<string, unknown>) => [...claimKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Refunds ──────────────────────────────────────────────────────────────────
export const refundKeys = {
  all: ['refunds'] as const,
  list: (params?: Record<string, unknown>) => [...refundKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...refundKeys.all, 'detail', id] as const,
}

// ─── Release notes ────────────────────────────────────────────────────────────
export const releaseNoteKeys = {
  all: ['release-notes'] as const,
  list: (params?: Record<string, unknown>) => [...releaseNoteKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...releaseNoteKeys.all, 'detail', id] as const,
  stats: () => [...releaseNoteKeys.all, 'stats'] as const,
  /**
   * A FLAT one-shot read, for a page that needs the whole set as a lookup
   * table rather than a paginated screen.
   *
   * Deliberately NOT `list()`. That key belongs to the `useCursorPagination`
   * hook for this domain, which is an INFINITE query caching
   * `{pages: ListResponse[], pageParams}`; a plain `useQuery` on the same key
   * caches a bare `ListResponse`. Whichever mounts first wins and the other
   * reads garbage. Still a child of `all`, so automatic invalidation reaches it.
   */
  lookup: (params?: Record<string, unknown>) => [...releaseNoteKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Warehouses (branch/office letterheads) ───────────────────────────────────
export const warehouseKeys = {
  all: ['warehouses'] as const,
}

// ─── Customers (tenant admin) ─────────────────────────────────────────────────
export const customerKeys = {
  all: ['customers'] as const,
  list: (params?: Record<string, unknown>) => [...customerKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...customerKeys.all, 'detail', id] as const,
  stats: () => [...customerKeys.all, 'stats'] as const,
  // A flat one-shot read (a dashboard queue, a picker). Not `list()`: see releaseNoteKeys.lookup.
  lookup: (params?: Record<string, unknown>) => [...customerKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Container capacity presets ─────────────────────────────────────────────────
export const containerCapacityKeys = {
  all: ['container-capacities'] as const,
  list: () => [...containerCapacityKeys.all, 'list'] as const,
}

// ─── Staff users ──────────────────────────────────────────────────────────────
export const staffKeys = {
  all: ['staff-users'] as const,
  list: () => [...staffKeys.all, 'list'] as const,
  detail: (id: string) => [...staffKeys.all, 'detail', id] as const,
}

// ─── Config ───────────────────────────────────────────────────────────────────
export const configKeys = {
  all: ['config'] as const,
  dollar: () => [...configKeys.all, 'dollar-rate'] as const,
  cbm: () => [...configKeys.all, 'cbm-rate'] as const,
  webhook: () => [...configKeys.all, 'webhook'] as const,
  notifications: () => [...configKeys.all, 'notification-templates'] as const,
  chargeTypes: () => [...configKeys.all, 'charge-types'] as const,
  // GET /v1/tenant/rate-history — a child of `all`, so saving either rate refreshes its history table.
  rateHistory: (rateType: string) => [...configKeys.all, 'rate-history', rateType] as const,
  // GET /v1/tenant/config (webhook + branding live in the same response —
  // webhook() above predates this and is kept for WebhookConfig's cache slot).
  tenantConfig: () => [...configKeys.all, 'tenant-config'] as const,
  // GET /v1/tenant/activity — the shared ActivityFeed widget; `actorId`
  // narrows it to one staff member, so it is part of the key.
  activity: (params?: Record<string, unknown>) => [...configKeys.all, 'activity', params ?? {}] as const,
  // GET /v1/tenant/policies & GET /v1/tenant/permissions (Tenant Admin Phase 1)
  policies: () => [...configKeys.all, 'policies'] as const,
  permissions: () => [...configKeys.all, 'permissions'] as const,
}

// ─── Tenant approvals inbox (Tenant Admin Phase 1, TC-02) ────────────────────
export const tenantApprovalKeys = {
  all: ['tenant-approvals'] as const,
  list: (type?: string) => [...tenantApprovalKeys.all, 'list', type ?? 'all'] as const,
  count: () => [...tenantApprovalKeys.all, 'count'] as const,
}

// ─── Notifications log ────────────────────────────────────────────────────────
export const notifLogKeys = {
  all: ['notif-log'] as const,
  list: (params?: Record<string, unknown>) => [...notifLogKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...notifLogKeys.all, 'detail', id] as const,
  /** Flat sample for the stats window — see the `lookup` note on billingKeys. */
  lookup: (params?: Record<string, unknown>) => [...notifLogKeys.all, 'lookup', params ?? {}] as const,
}

// ─── Staff notifications (TopBar bell) ────────────────────────────────────────
export const staffNotifKeys = {
  all: ['staff-notif'] as const,
  list: (params?: Record<string, unknown>) => [...staffNotifKeys.all, 'list', params ?? {}] as const,
  unreadCount: () => [...staffNotifKeys.all, 'unread-count'] as const,
  banner: () => [...staffNotifKeys.all, 'banner'] as const,
}

// ─── Customer notifications (customer portal bell) ────────────────────────────
export const customerNotifKeys = {
  all: ['customer-notif'] as const,
  list: (params?: Record<string, unknown>) => [...customerNotifKeys.all, 'list', params ?? {}] as const,
  unreadCount: () => [...customerNotifKeys.all, 'unread-count'] as const,
  banner: () => [...customerNotifKeys.all, 'banner'] as const,
}

// ─── Announcements (approval queue + banner management) ──────────────────────
export const announcementKeys = {
  all: ['announcements'] as const,
  pending: () => [...announcementKeys.all, 'pending'] as const,
  mine: () => [...announcementKeys.all, 'mine'] as const,
  history: () => [...announcementKeys.all, 'history'] as const,
}

// ─── Platform tenants ─────────────────────────────────────────────────────────
export const platformTenantKeys = {
  all: ['platform-tenants'] as const,
  // Every tenant, all pages followed (dashboard, audit-log filter). The Tenants page pages on the server under `page`.
  list: () => [...platformTenantKeys.all, 'list'] as const,
  page: (params: Record<string, unknown>) => [...platformTenantKeys.all, 'page', params] as const,
  detail: (id: string) => [...platformTenantKeys.all, 'detail', id] as const,
  // GET /v1/platform/tenants/{id}/usage — a child of platformTenantKeys.all,
  // which the /v1/platform/tenants/ invalidation rule already covers (and
  // quota-override lives under that same path).
  usage: (id: string) => [...platformTenantKeys.all, 'usage', id] as const,
  users: (id: string) => [...platformTenantKeys.all, 'users', id] as const,
  config: (id: string) => [...platformTenantKeys.all, 'config', id] as const,
  // The offboarding data export (audit BE-10). Queuing one and issuing a link both POST under
  // /v1/platform/tenants/, which refreshes every key here.
  offboardingExport: (id: string) => [...platformTenantKeys.all, 'offboarding-export', id] as const,
}

// ─── Platform settings (general, notification providers, plan limits) ────────
export const platformSettingsKeys = {
  all: ['platform-settings'] as const,
  general: () => [...platformSettingsKeys.all, 'general'] as const,
  gateways: () => [...platformSettingsKeys.all, 'gateways'] as const,
  plans: () => [...platformSettingsKeys.all, 'plans'] as const,
}

// ─── Platform dashboard (cross-tenant totals) ────────────────────────────────
export const platformDashboardKeys = {
  all: ['platform-dashboard'] as const,
  summary: () => [...platformDashboardKeys.all, 'summary'] as const,
}

// ─── Platform audit log (cross-tenant) ────────────────────────────────────────
export const platformAuditKeys = {
  all: ['platform-audit'] as const,
  list: (params?: Record<string, unknown>) => [...platformAuditKeys.all, 'list', params ?? {}] as const,
  // The dashboard's short activity feed: a flat read, so not `list()`, which the audit-log page pages through as an
  // infinite query (two shapes under one key corrupt each other).
  recent: (limit: number) => [...platformAuditKeys.all, 'recent', limit] as const,
  // One tenant's recent entries (the tenant page's Audit tab): a flat read too.
  forTenant: (tenantId: string) => [...platformAuditKeys.all, 'tenant', tenantId] as const,
}

// ─── Platform security: the caller, the admin directory, approvals (Phase 1) ──
export const platformMeKeys = {
  all: ['platform-me'] as const,
}

export const platformAdminKeys = {
  all: ['platform-admins'] as const,
  list: () => [...platformAdminKeys.all, 'list'] as const,
}

export const platformApprovalKeys = {
  all: ['platform-approvals'] as const,
  list: (status?: string) => [...platformApprovalKeys.all, 'list', status ?? 'all'] as const,
}

// ─── Platform onboarding requests (shipping-company leads) ────────────────────
export const onboardingRequestKeys = {
  all: ['onboarding-requests'] as const,
  list: (status?: string) => [...onboardingRequestKeys.all, 'list', status ?? 'all'] as const,
  detail: (id: string) => [...onboardingRequestKeys.all, 'detail', id] as const,
}

// ─── Global search (read-only, short-lived; no mutation affects it) ──────────
export const searchKeys = {
  all: ['search'] as const,
  query: (q: string) => [...searchKeys.all, 'query', q] as const,
}
