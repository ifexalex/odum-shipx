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
}

// ─── Packing lists ────────────────────────────────────────────────────────────
export const packingListKeys = {
  all: ['packing-lists'] as const,
  list: (params?: Record<string, unknown>) => [...packingListKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...packingListKeys.all, 'detail', id] as const,
}

// ─── Manifests ────────────────────────────────────────────────────────────────
export const manifestKeys = {
  all: ['manifests'] as const,
  list: (params?: Record<string, unknown>) => [...manifestKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...manifestKeys.all, 'detail', id] as const,
}

// ─── Billing ──────────────────────────────────────────────────────────────────
export const billingKeys = {
  all: ['billing'] as const,
  list: (params?: Record<string, unknown>) => [...billingKeys.all, 'list', params ?? {}] as const,
  stats: () => [...billingKeys.all, 'stats'] as const,
  report: (params?: Record<string, unknown>) => [...billingKeys.all, 'report', params ?? {}] as const,
  detail: (id: string) => [...billingKeys.all, 'detail', id] as const,
  forCustomer: (customerId: string) => [...billingKeys.all, 'customer', customerId] as const,
  // GET /v1/billing/carryovers — a child of billingKeys.all, which the
  // /v1/billing/carryovers/ invalidation rule already covers.
  carryovers: (params?: Record<string, unknown>) => [...billingKeys.all, 'carryovers', params ?? {}] as const,
}

// ─── Claims ───────────────────────────────────────────────────────────────────
export const disputeKeys = {
  all: ['disputes'] as const,
  list: (params?: Record<string, unknown>) => ['disputes', 'list', params ?? {}] as const,
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
  // GET /v1/tenant/config (webhook + branding live in the same response —
  // webhook() above predates this and is kept for WebhookConfig's cache slot).
  tenantConfig: () => [...configKeys.all, 'tenant-config'] as const,
  // GET /v1/tenant/activity — the shared ActivityFeed widget; `actorId`
  // narrows it to one staff member, so it is part of the key.
  activity: (params?: Record<string, unknown>) => [...configKeys.all, 'activity', params ?? {}] as const,
}

// ─── Notifications log ────────────────────────────────────────────────────────
export const notifLogKeys = {
  all: ['notif-log'] as const,
  list: (params?: Record<string, unknown>) => [...notifLogKeys.all, 'list', params ?? {}] as const,
  detail: (id: string) => [...notifLogKeys.all, 'detail', id] as const,
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
  list: () => [...platformTenantKeys.all, 'list'] as const,
  detail: (id: string) => [...platformTenantKeys.all, 'detail', id] as const,
  // GET /v1/platform/tenants/{id}/usage — a child of platformTenantKeys.all,
  // which the /v1/platform/tenants/ invalidation rule already covers (and
  // quota-override lives under that same path).
  usage: (id: string) => [...platformTenantKeys.all, 'usage', id] as const,
}

// ─── Platform audit log (cross-tenant) ────────────────────────────────────────
export const platformAuditKeys = {
  all: ['platform-audit'] as const,
  list: (params?: Record<string, unknown>) => [...platformAuditKeys.all, 'list', params ?? {}] as const,
}

// ─── Platform onboarding requests (shipping-company leads) ────────────────────
export const onboardingRequestKeys = {
  all: ['onboarding-requests'] as const,
  list: (status?: string) => [...onboardingRequestKeys.all, 'list', status ?? 'all'] as const,
  detail: (id: string) => [...onboardingRequestKeys.all, 'detail', id] as const,
}
