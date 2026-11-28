import { apiRequest, apiRequestList } from './client'

// ---------------------------------------------------------------------------
// Customer types (partially defined here since 7.1 pulled customersApi forward)
// ---------------------------------------------------------------------------

export interface Customer {
  id: string
  tenant_id: string
  name: string | null
  phone: string | null
  email: string | null
  whatsapp: string | null
  address: string | null
  anonymised_at: string | null
  user_id: string | null
  consent_given_at: string | null
  created_at?: string
  notification_consent: string[] | null
  /** Notification language (migration 029) — selects the EN/ZH template set for SMS/WhatsApp/email. */
  locale?: 'en' | 'zh' | null
  // Derived aggregate: lifetime packing lists (shipments) for this customer.
  // Present on the list endpoint (GET /v1/customers); may be absent on single-get.
  shipment_count?: number
  // Expiry of this customer's current unconsumed account-creation invite, if
  // any — null when there's no login (no invite ever sent, or it expired)
  // and when the customer already has an active login (user_id set).
  pending_invite_expires_at?: string | null
}

export interface CustomerListParams {
  q?: string
  cursor?: string
  limit?: number
}

export interface CustomerExport {
  customer: Customer
  billing: unknown[]
  shipments: unknown[]
  damage_claims: unknown[]
  exported_at: string
}

export interface CustomerInvite {
  id: string
  customer_id: string
  expires_at: string
  sent_channel: 'sms' | 'whatsapp' | 'email'
  sent_to_masked: string | null
}

/** Aggregate customer counts for stat cards — computed server-side so they
 *  stay correct regardless of how many rows the list endpoint returns. */
export interface CustomerStats {
  total: number
  active: number
  anonymised: number
  with_whatsapp: number
  shipments: number
}

export const customersApi = {
  list: (params: CustomerListParams = {}) =>
    apiRequestList<Customer>({
      method: 'GET',
      path: '/v1/customers',
      query: params as Record<string, string | number | undefined>,
    }),

  stats: () =>
    apiRequest<CustomerStats>({ method: 'GET', path: '/v1/customers/stats' }),

  get: (id: string) =>
    apiRequest<Customer>({ method: 'GET', path: `/v1/customers/${id}` }),

  create: (body: { name: string; phone?: string; email?: string; address?: string; whatsapp?: string; notification_consent?: string[] }) =>
    apiRequest<Customer>({ method: 'POST', path: '/v1/customers', body }),

  update: (id: string, body: { name?: string; phone?: string; email?: string; address?: string; whatsapp?: string; delivery_address?: string; notification_consent?: string[]; locale?: 'en' | 'zh' }) =>
    apiRequest<Customer>({ method: 'PATCH', path: `/v1/customers/${id}`, body }),

  /** GDPR Art. 17 — Right to erasure. Returns 204 (undefined). */
  anonymise: (id: string) =>
    apiRequest<undefined>({ method: 'DELETE', path: `/v1/customers/${id}` }),

  /** GDPR Art. 20 — Data portability export. */
  export: (id: string) =>
    apiRequest<CustomerExport>({ method: 'GET', path: `/v1/customers/${id}/export` }),

  /**
   * Issue (or resend) an account-creation invite. Resending invalidates
   * any previously unconsumed link for this customer.
   */
  invite: (id: string) =>
    apiRequest<CustomerInvite>({ method: 'POST', path: `/v1/customers/${id}/invite` }),
}

// ---------------------------------------------------------------------------
// Container capacity presets — ten well-known defaults (read-only) + tenant
// custom presets. Drives the create-container capacity picker and the
// utilization bar's capacity denominator.
// ---------------------------------------------------------------------------

export interface ContainerCapacity {
  /** `default:<name>` for built-ins, a UUID for custom ones. */
  id: string
  name: string
  capacity_cbm: number
  recommended_cbm: number | null
  is_custom: boolean
}

export interface CreateContainerCapacityInput {
  name: string
  capacity_cbm: number
  recommended_cbm?: number
}

/** Editable fields. For a default preset only `recommended_cbm` applies
 *  (name/capacity are physical constants); custom presets accept all three.
 *  `recommended_cbm: null` on a default reverts it to the built-in value. */
export interface UpdateContainerCapacityInput {
  name?: string
  capacity_cbm?: number
  recommended_cbm?: number | null
}

export const containerCapacitiesApi = {
  list: () =>
    apiRequest<ContainerCapacity[]>({ method: 'GET', path: '/v1/tenant/container-capacities' }),

  create: (body: CreateContainerCapacityInput) =>
    apiRequest<ContainerCapacity>({ method: 'POST', path: '/v1/tenant/container-capacities', body }),

  update: (id: string, body: UpdateContainerCapacityInput) =>
    apiRequest<ContainerCapacity>({
      method: 'PATCH',
      path: `/v1/tenant/container-capacities/${encodeURIComponent(id)}`,
      body,
    }),

  remove: (id: string) =>
    apiRequest<undefined>({
      method: 'DELETE',
      path: `/v1/tenant/container-capacities/${encodeURIComponent(id)}`,
    }),
}

// ---------------------------------------------------------------------------
// Tenant users (staff management)
// ---------------------------------------------------------------------------

export type TenantUserRole =
  | 'tenant_admin'
  | 'china_office_staff'
  | 'nigeria_office_staff'
  | 'warehouse_attendant'
  | 'customer'

export interface TenantUser {
  id: string
  tenant_id: string
  email: string
  full_name: string
  /** Primary role — kept for every existing single-role consumer (badges, reports). */
  role: TenantUserRole
  /** Every role assigned to this user (multi-role staff support). Always includes `role`. */
  roles: TenantUserRole[]
  /** Only these two exist. The DB CHECK constraint on `tenant_user.status`
   *  is `('active','deactivated')` — this said `'inactive'`, a value the
   *  database can never contain, so anything comparing against it never
   *  matched real data. */
  status: 'active' | 'deactivated'
  /** Notification template language — 'en' (default) or 'zh'. Only relevant for China Office Staff. */
  locale: 'en' | 'zh' | null
  created_at: string
}

// Breaking change (2026-07-20): `role` (singular) → `roles` + `primary_role` —
// mirrors services/tenant_management/models.py CreateTenantUserRequest /
// UpdateTenantUserRequest. No dual-path back-compat; there are no production
// tenants yet.
export interface CreateUserInput {
  email: string
  full_name: string
  roles: TenantUserRole[]
  /** Defaults server-side to roles[0] when omitted. */
  primary_role?: TenantUserRole
}

export interface UpdateUserInput {
  full_name?: string
  roles?: TenantUserRole[]
  /** Must be one of `roles` when both are present; defaults to roles[0] when omitted. */
  primary_role?: TenantUserRole
  locale?: 'en' | 'zh'
}

export const usersApi = {
  list: () =>
    apiRequest<TenantUser[]>({ method: 'GET', path: '/v1/tenant/users' }),

  get: (id: string) =>
    apiRequest<TenantUser>({ method: 'GET', path: `/v1/tenant/users/${id}` }),

  create: (body: CreateUserInput) =>
    apiRequest<TenantUser>({ method: 'POST', path: '/v1/tenant/users', body }),

  update: (id: string, body: UpdateUserInput) =>
    apiRequest<TenantUser>({ method: 'PATCH', path: `/v1/tenant/users/${id}`, body }),

  /** Returns 204 with no body — the caller gets `undefined`, not a row. This
   *  was typed `TenantUser`, which let a caller believe it could read the new
   *  status off the result; the only honest source for that is the next fetch
   *  or an optimistic value. `reactivate` below does return the updated row. */
  deactivate: (id: string) =>
    apiRequest<void>({ method: 'DELETE', path: `/v1/tenant/users/${id}` }),

  /** Undo a deactivation: re-enables the identity and sets status back to
   *  active. Refused with 429 when the tenant is at its seat limit, by the
   *  same rule that blocks creating a user. */
  reactivate: (id: string) =>
    apiRequest<TenantUser>({ method: 'POST', path: `/v1/tenant/users/${id}/reactivate`, body: {} }),

  resendInvite: (id: string) =>
    apiRequest<{ message: string }>({ method: 'POST', path: `/v1/tenant/users/${id}/resend-invite`, body: {} }),

  resetPassword: (id: string) =>
    apiRequest<{ message: string }>({ method: 'POST', path: `/v1/tenant/users/${id}/reset-password`, body: {} }),

  /** Re-send the ShipX account-activation (set-password) link to a provisioned user. */
  resendActivation: (id: string) =>
    apiRequest<{ message: string; email: string }>({
      method: 'POST',
      path: `/v1/tenant/users/${id}/resend-activation`,
      body: {},
    }),

  /** Self-service: update the calling user's own locale. Uses PATCH /v1/tenant/me. */
  updateMe: (locale: 'en' | 'zh') =>
    apiRequest<TenantUser>({ method: 'PATCH', path: '/v1/tenant/me', body: { locale } }),
}

// ---------------------------------------------------------------------------
// Tenant config — rates, charge types, notification templates
// ---------------------------------------------------------------------------

export interface RateHistoryEntry {
  id: string
  rate_type: string
  /** JSONB — e.g. {"rate": 1650} for dollar_rate, {"currency", "rate_mode",
   *  "carton_rate", "bag_rate", "bale_rate"} for cbm_rate. */
  rate_value: Record<string, unknown>
  previous_value: Record<string, unknown> | null
  changed_by: string | null
  effective_from: string
  created_at: string
}

export interface TenantActivityEntry {
  id: string
  /**
   * The four generic actions, or a named one written by a specific operation
   * (e.g. `EXPORT`, `BULK_APPROVE`, `PASSWORD_RESET_SENT`): `audit_log.action`
   * has had no CHECK since migration 045.
   */
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'STATUS_CHANGE' | (string & {})
  entity_type: string
  entity_id: string
  actor_id: string | null
  actor_role: string | null
  actor_name: string | null
  /** What the record looked like before this action — null for CREATE. */
  before_state: Record<string, unknown> | null
  /** What changed — the actual amounts/statuses/reasons, not just that
   *  something happened. Sensitive fields (id_number, account_number,
   *  account_name, delegate_phone) are masked server-side before storage. */
  after_state: Record<string, unknown> | null
  created_at: string
}

export interface DollarRateConfig {
  /** Effective rate (base_rate with the tenant's markup applied) — what customers are billed at. */
  rate: number
  /** Raw Bybit P2P black-market rate, before markup. */
  base_rate: number
  markup_type: 'percentage' | 'flat'
  markup_value: number
  /** The market feed: always "bybit_p2p" today. */
  source: string
  /**
   * Where this base rate came from (audit BE-11): `live` (fetched within the 10-minute cache), `last_known` (the feed
   * is down; the last fetched rate), or `hardcoded` (no rate has ever been fetched; invoicing refuses it).
   */
  rate_source: 'live' | 'last_known' | 'hardcoded'
  /** When the underlying Bybit rate was fetched; null for the hard-coded value, which never was. */
  fetched_at: string | null
  currency_pair: string
  /** When the markup was last changed by an admin — "" if never changed. */
  effective_from: string
}

export interface UpdateDollarRateMarkupInput {
  markup_type: 'percentage' | 'flat'
  markup_value: number
}

export type CbmRateCurrency = 'usd' | 'ngn'
export type CbmRateMode = 'flat' | 'per_package_type'

export interface CbmRateConfig {
  currency: CbmRateCurrency
  rate_mode: CbmRateMode
  /** "flat" mode means bag_rate/bale_rate always equal carton_rate — the
   *  backend enforces this, not just the form. */
  carton_rate: number
  bag_rate: number
  bale_rate: number
  effective_from: string
  /** Minimum billable CBM per line item (floor applied at packing-list entry). */
  min_cbm_per_item: number
}

export interface UpdateCbmRateInput {
  currency: CbmRateCurrency
  rate_mode: CbmRateMode
  carton_rate: number
  bag_rate?: number
  bale_rate?: number
  /** Omit to leave the current minimum CBM unchanged. */
  min_cbm_per_item?: number
}

export interface ChargeType {
  id: string
  name: string
  description: string | null
  amount_ngn: string
  is_active: boolean
  /** Misc charges attributed to this type via charge_type_id (§4.4 usage analytics). */
  usage_count?: number
}

export interface NotificationTemplate {
  id?: string
  tenant_id?: string
  event_type: string
  channel: 'sms' | 'whatsapp' | 'email'
  template_body: string
  subject: string | null
  updated_at?: string
}

export type WebhookEventType =
  | 'container.status_updated'
  | 'billing.payment_due'
  | 'release_note.generated'
  | 'packing_list.approved'

export interface WebhookConfig {
  endpoint_url: string
  enabled: boolean
  events: WebhookEventType[]
  /** Always `"****"` from the API — only the last 4 chars of the real secret are shown. */
  secret: string
}

/**
 * Tenant branding + document identity (prototype 4.1 — Company Settings).
 * Stored as free-form JSONB in `tenant.branding_config` via
 * PUT /v1/tenant/config {branding} — this interface is the canonical shape the
 * frontend writes and every consumer (print documents, ThemeProvider, sidebar
 * TenantBrand) reads. All fields optional: absent = fall back to defaults.
 */
/** A presigned direct-to-storage upload: PUT the file to `upload_url` with `upload_headers`, then use `file_key`. */
export interface PresignedUpload {
  file_key: string
  upload_url: string
  upload_method?: string
  upload_headers?: Record<string, string>
}

export interface BrandingConfig {
  /** Company name as shown on documents and the portal (may differ from the legal `tenant.company_name`). */
  display_name?: string
  /** Optional strapline under the logo on documents. */
  tagline?: string
  /** Hex colour driving the tenant-scoped theme (ThemeProvider derives shades). */
  primary_color?: string
  /**
   * A short-lived link to the uploaded logo (FD-29), or absent for the initials tile. Read-only: the logo is set through
   * `configApi.setLogo`, and the API ignores this field on a branding save.
   */
  logo_url?: string
  /** Multiline pickup address printed on release notes. */
  warehouse_address?: string
  pickup_hours?: string
  pickup_phone?: string
  support_email?: string
  support_whatsapp?: string
  /** Optional China origin warehouse identity for Loading Receipts & Packing Lists (ENG-1). */
  chinese_display_name?: string
  china_warehouse_address?: string
  china_warehouse_phone?: string
  /** Multiline boilerplate at the bottom of generated documents. */
  document_footer?: string
}

/**
 * Multi-tenant Paystack (2026-07-19) — each tenant connects their own
 * Paystack account so customer payments land directly with them; there is
 * no platform-wide key. The secret key itself is never returned by the API
 * (encrypted at rest, unlike webhook_config.secret's masked-plaintext) —
 * only enough to render a status card. `null` (or the key absent from
 * `TenantConfig`) means the tenant hasn't connected one yet, and "Pay
 * online" is unavailable for their customers until they do.
 */
export interface PaystackConfig {
  enabled: boolean
  last4: string | null
  environment: 'test' | 'live' | null
  configured_by: string | null
  configured_at: string | null
}

/**
 * This tenant's own bank account for the "Manual bank transfer" payment
 * option (MyBillingDetail.tsx). Ground-truth gap found live: the frontend
 * previously hardcoded a single tenant's bank details for every tenant's
 * customers — this makes it a real per-tenant setting instead.
 */
export interface BankTransferConfig {
  bank_name: string
  account_name: string
  account_number: string
  sort_code: string | null
  instructions: string | null
}

export interface TenantConfig {
  webhook_config: WebhookConfig | null
  branding_config?: BrandingConfig | null
  paystack_config?: PaystackConfig | null
  bank_transfer_config?: BankTransferConfig | null
  /** Default transit duration in days used to compute ETA when a container moves to In Transit (default 45). */
  default_transit_days?: number
}

export interface WebhookTestResult {
  success: boolean
  status_code: number | null
  error: string | null
}

export interface PaystackTestResult {
  success: boolean
  environment: 'test' | 'live' | null
}

/** The company-facing view of the public customer signup link. */
export interface RegistrationLinkSettings {
  /** False means the public signup route refuses this tenant. */
  enabled: boolean
  /** The tenant's URL slug — the `{slug}` in /register/{slug}. */
  slug: string | null
  updated_at?: string | null
}

export const configApi = {
  getRegistrationLink: () =>
    apiRequest<RegistrationLinkSettings>({ method: 'GET', path: '/v1/tenant/registration-link' }),

  setRegistrationLinkEnabled: (enabled: boolean) =>
    apiRequest<RegistrationLinkSettings>({
      method: 'PATCH',
      path: '/v1/tenant/registration-link',
      body: { enabled },
    }),

  getDollarRate: () =>
    apiRequest<DollarRateConfig>({ method: 'GET', path: '/v1/tenant/dollar-rate' }),

  updateDollarRate: (body: UpdateDollarRateMarkupInput) =>
    apiRequest<DollarRateConfig>({ method: 'PUT', path: '/v1/tenant/dollar-rate', body }),

  getCbmRate: () =>
    apiRequest<CbmRateConfig>({ method: 'GET', path: '/v1/tenant/cbm-rate' }),

  updateCbmRate: (body: UpdateCbmRateInput) =>
    apiRequest<CbmRateConfig>({ method: 'PUT', path: '/v1/tenant/cbm-rate', body }),

  listChargeTypes: () =>
    apiRequest<ChargeType[]>({ method: 'GET', path: '/v1/tenant/charge-types' }),

  createChargeType: (body: { name: string; amount_ngn: string; description?: string }) =>
    apiRequest<ChargeType>({ method: 'POST', path: '/v1/tenant/charge-types', body }),

  updateChargeType: (id: string, body: { name?: string; amount_ngn?: string; description?: string }) =>
    apiRequest<ChargeType>({ method: 'PUT', path: `/v1/tenant/charge-types/${id}`, body }),

  deactivateChargeType: (id: string) =>
    apiRequest<ChargeType>({ method: 'DELETE', path: `/v1/tenant/charge-types/${id}` }),

  listNotificationTemplates: () =>
    apiRequest<NotificationTemplate[]>({ method: 'GET', path: '/v1/tenant/notification-templates' }),

  upsertNotificationTemplate: (eventType: string, channel: string, body: { template_body: string; subject?: string }) =>
    apiRequest<NotificationTemplate>({
      method: 'PUT',
      path: `/v1/tenant/notification-templates/${eventType}/${channel}`,
      body,
    }),

  /** Append-only audit of dollar/cbm rate changes (migration 025).
   *  Ground-truth fix: the backend has always written rate_type="cbm_rate"
   *  (services/tenant_management/service.py::update_cbm_rate) — this used
   *  to query "cbm_rate_per_unit" (the tenant_config *key*, not the
   *  rate_history *rate_type*), so the CBM rate-history table/chart never
   *  matched any row. */
  rateHistory: (rateType: 'dollar_rate' | 'cbm_rate', limit = 20) =>
    apiRequestList<RateHistoryEntry>({
      method: 'GET',
      path: '/v1/tenant/rate-history',
      query: { rate_type: rateType, limit },
    }),

  /**
   * B6 — tenant-scoped activity feed (audit gap). Admin-only. `actorId` narrows
   * to one staff member (staff-profile activity table, prototype 3.4).
   *
   * Full filter set added 2026-09-07 for the Activity Log page: `entityTypes`
   * (one or more — a category maps to several at once, comma-joined on the
   * wire, same contract as GET /v1/containers's multi-status filter), `action`,
   * `q` (matches the actor's name or the record's id — paste a UUID to find
   * every action ever taken on that specific record), `createdAfter`/
   * `createdBefore` (ISO dates), `sort` ('asc' | 'desc', default 'desc').
   */
  activity: (params: {
    actorId?: string
    entityTypes?: string[]
    action?: string
    q?: string
    createdAfter?: string
    createdBefore?: string
    sort?: 'asc' | 'desc'
    limit?: number
    cursor?: string
  } = {}) =>
    apiRequestList<TenantActivityEntry>({
      method: 'GET',
      path: '/v1/tenant/activity',
      query: {
        actor_id: params.actorId,
        entity_type: params.entityTypes?.length ? params.entityTypes.join(',') : undefined,
        action: params.action,
        q: params.q,
        created_after: params.createdAfter,
        created_before: params.createdBefore,
        sort: params.sort,
        limit: params.limit,
        cursor: params.cursor,
      },
    }),

  getConfig: () =>
    apiRequest<TenantConfig>({ method: 'GET', path: '/v1/tenant/config' }),

  /** Presign the logo upload (FD-29): PNG, JPEG or WebP, at most 5 MB. */
  getLogoUploadUrl: (body: { filename: string; content_type: string; size_bytes: number }) =>
    apiRequest<PresignedUpload>({ method: 'POST', path: '/v1/tenant/config/logo/upload-url', body }),

  /** Use the uploaded file as the logo; returns the branding with its new `logo_url`. */
  setLogo: (fileKey: string) =>
    apiRequest<BrandingConfig>({ method: 'PUT', path: '/v1/tenant/config/logo', body: { file_key: fileKey } }),

  /** Stop using a logo: documents go back to the initials tile. */
  removeLogo: () => apiRequest<BrandingConfig>({ method: 'DELETE', path: '/v1/tenant/config/logo' }),

  updateConfig: (body: {
    webhook_config?: Partial<Omit<WebhookConfig, 'secret'>>
    branding?: BrandingConfig
    bank_transfer_config?: BankTransferConfig
    default_transit_days?: number
  }) => apiRequest<TenantConfig>({ method: 'PUT', path: '/v1/tenant/config', body }),

  rotateWebhookSecret: () =>
    apiRequest<{ secret: string }>({ method: 'POST', path: '/v1/tenant/config/webhook/rotate-secret', body: {} }),

  testWebhook: () =>
    apiRequest<WebhookTestResult>({ method: 'POST', path: '/v1/tenant/config/webhook/test', body: {} }),

  /** Connect (or replace) this tenant's own Paystack secret key. Always a
   * full replace — there's nothing to partially merge, unlike webhook_config. */
  updatePaystackConfig: (secretKey: string) =>
    apiRequest<PaystackConfig>({ method: 'PUT', path: '/v1/tenant/config/paystack', body: { secret_key: secretKey } }),

  /** Disconnect Paystack — online payment reverts to bank-transfer-only for this tenant. */
  deletePaystackConfig: () =>
    apiRequest<{ enabled: false }>({ method: 'DELETE', path: '/v1/tenant/config/paystack' }),

  /** Live connectivity check against the stored key — proves it actually works, not just present. */
  testPaystackConnection: () =>
    apiRequest<PaystackTestResult>({ method: 'POST', path: '/v1/tenant/config/paystack/test', body: {} }),
}

// ---------------------------------------------------------------------------
// Platform admin — tenant management
// ---------------------------------------------------------------------------

export type TenantStatus = 'active' | 'suspended' | 'offboarded'
export type SubscriptionTier = 'starter' | 'business' | 'enterprise'

export interface Tenant {
  id: string
  company_name: string
  slug: string
  primary_contact_email: string
  primary_contact_phone: string | null
  subscription_tier: SubscriptionTier
  status: TenantStatus
  created_at: string
  offboarded_at: string | null
  reactivated_at: string | null
  /** Staff seats in use: active users who are not customer portal accounts (shared/seats.py) — list endpoint only. */
  user_count?: number
  /** Effective users limit (tier ⊕ plan ⊕ tenant override) — list endpoint only. */
  users_limit?: number | null
}

// Matches services/tenant_management/models.py CreateTenantRequest — note the
// nested initial_admin (the previous flat shape failed backend validation).
export interface CreateTenantInput {
  company_name: string
  primary_contact_email: string
  primary_contact_phone?: string
  subscription_tier: SubscriptionTier
  initial_admin: { email: string; full_name: string }
  /** Set when provisioning from a company onboarding lead — links + closes it. */
  onboarding_request_id?: string
}

export type OnboardingRequestStatus = 'new' | 'contacted' | 'approved' | 'rejected' | 'provisioned'

export interface OnboardingRequest {
  id: string
  company_name: string
  contact_name: string
  contact_email: string
  contact_phone: string | null
  origin_country: string
  destination_country: string
  monthly_volume: string | null
  notes: string | null
  status: OnboardingRequestStatus
  rejection_reason: string | null
  tenant_id: string | null
  created_at: string
}

/** Server-side filters of GET /v1/platform/tenants (audit PA-02). */
export interface TenantListParams {
  status?: TenantStatus
  tier?: SubscriptionTier
  q?: string
  cursor?: string
  limit?: number
}

/** Page size the fetch-all helper asks for: the API's maximum. */
const TENANT_PAGE_LIMIT = 100
/** Stops a runaway loop if the API ever kept returning a cursor: 50 pages of 100 is far past any real tenant count. */
const MAX_TENANT_PAGES = 50

/** PATCH /v1/platform/tenants/{id}/reactivate (services/tenant_management/tenants.py reactivate_tenant). */
export interface TenantReactivation {
  tenant: Tenant
  /** Notices the platform admin must relay to the tenant before processing resumes, each "CODE: sentence". */
  notices: string[]
}

export const platformApi = {
  /** One page of tenants, filtered and searched on the server. */
  listTenants: (params: TenantListParams = {}) =>
    apiRequestList<Tenant>({
      method: 'GET',
      path: '/v1/platform/tenants',
      query: params as Record<string, string | number | undefined>,
    }),

  /**
   * Every tenant, following the cursor page by page. For views that need the whole set at once (the dashboard's
   * health table, the audit log's tenant filter); the Tenants page itself pages on the server.
   */
  listAllTenants: async (): Promise<Tenant[]> => {
    const all: Tenant[] = []
    let cursor: string | undefined
    for (let page = 0; page < MAX_TENANT_PAGES; page += 1) {
      const result = await platformApi.listTenants({ limit: TENANT_PAGE_LIMIT, ...(cursor ? { cursor } : {}) })
      all.push(...result.data)
      const { has_more: hasMore, next_cursor: next } = result.meta.pagination
      if (!hasMore || !next) return all
      cursor = next
    }
    return all
  },

  /** Edit a tenant's name, contact or plan (PATCH /v1/platform/tenants/{id}). */
  updateTenant: (id: string, body: { company_name?: string; primary_contact_email?: string; subscription_tier?: SubscriptionTier }) =>
    apiRequest<Tenant>({ method: 'PATCH', path: `/v1/platform/tenants/${id}`, body }),

  /** Bring an offboarded tenant back within its 90 days, under a new agreement. */
  reactivateTenant: (id: string) =>
    apiRequest<TenantReactivation>({ method: 'PATCH', path: `/v1/platform/tenants/${id}/reactivate`, body: {} }),

  getTenant: (id: string) =>
    apiRequest<Tenant>({ method: 'GET', path: `/v1/platform/tenants/${id}` }),

  createTenant: (body: CreateTenantInput) =>
    apiRequest<{ tenant: Tenant; admin_user: TenantUser }>({
      method: 'POST',
      path: '/v1/platform/tenants',
      body,
    }),

  // Shipping-company onboarding leads (admin review queue).
  listOnboardingRequests: (status?: OnboardingRequestStatus) =>
    apiRequest<OnboardingRequest[]>({
      method: 'GET',
      path: status ? `/v1/platform/onboarding-requests?status=${status}` : '/v1/platform/onboarding-requests',
    }),

  getOnboardingRequest: (id: string) =>
    apiRequest<OnboardingRequest>({ method: 'GET', path: `/v1/platform/onboarding-requests/${id}` }),

  updateOnboardingRequest: (id: string, status: OnboardingRequestStatus, rejection_reason?: string) =>
    apiRequest<OnboardingRequest>({
      method: 'PATCH',
      path: `/v1/platform/onboarding-requests/${id}`,
      body: { status, rejection_reason },
    }),

  suspendTenant: (id: string, reason: string) =>
    apiRequest<Tenant>({ method: 'PATCH', path: `/v1/platform/tenants/${id}/suspend`, body: { reason } }),

  activateTenant: (id: string) =>
    apiRequest<Tenant>({ method: 'PATCH', path: `/v1/platform/tenants/${id}/activate`, body: {} }),

  offboardTenant: (id: string, reason: string) =>
    apiRequest<Tenant>({ method: 'DELETE', path: `/v1/platform/tenants/${id}`, body: { reason } }),

  impersonate: (id: string) =>
    // Wire shape from services/tenant_management/impersonation.py — the
    // signed JWT is in `token`, not `id_token` (previous mismatch meant the
    // impersonation session was seeded with undefined and always crashed).
    apiRequest<{
      token: string
      session_id: string
      expires_at: string
      target_user_id: string
      target_tenant_id: string
      read_only: boolean
    }>({
      method: 'POST',
      path: `/v1/platform/tenants/${id}/impersonate`,
      body: {},
    }),

  /** Revoke an active impersonation session server-side and record IMPERSONATION_END. */
  endImpersonation: (sessionId: string) =>
    apiRequest<{ session_id: string; ended_at?: string }>({
      method: 'DELETE',
      path: `/v1/platform/impersonation/${sessionId}`,
    }),

  /** Cross-tenant aggregates for the platform dashboard (2.1). */
  dashboard: () =>
    apiRequest<PlatformDashboardStats>({ method: 'GET', path: '/v1/platform/dashboard' }),

  /** Cross-tenant audit log with tenant/action filters (14.7). */
  auditLog: (params: { tenant_id?: string; action?: string; cursor?: string; limit?: number } = {}) =>
    apiRequestList<PlatformAuditEntry>({
      method: 'GET',
      path: '/v1/platform/audit-log',
      query: params as Record<string, string | number | undefined>,
    }),

  /** Staff users within a tenant (TenantDetail Users tab). */
  tenantUsers: (id: string) =>
    apiRequest<TenantUser[]>({ method: 'GET', path: `/v1/platform/tenants/${id}/users` }),

  /** Read-only tenant config view (TenantDetail Config tab). Secrets masked server-side. */
  tenantConfig: (id: string) =>
    apiRequest<Record<string, unknown>>({ method: 'GET', path: `/v1/platform/tenants/${id}/config` }),

  /** Usage + effective limits (metering service). */
  tenantUsage: (id: string, period?: string) =>
    apiRequest<TenantUsage>({
      method: 'GET',
      path: `/v1/platform/tenants/${id}/usage`,
      query: period ? { period } : undefined,
    }),

  /** Where the offboarded tenant's data export stands (audit BE-10). */
  offboardingExport: (id: string) =>
    apiRequest<OffboardingExport>({ method: 'GET', path: `/v1/platform/tenants/${id}/offboarding-export` }),

  /** Queue an export for an offboarded tenant with none, or whose export gave up. */
  queueOffboardingExport: (id: string) =>
    apiRequest<OffboardingExport>({ method: 'POST', path: `/v1/platform/tenants/${id}/offboarding-export`, body: {} }),

  /** A five-minute download link to the completed archive. Each one is recorded in the platform audit log. */
  offboardingExportLink: (id: string) =>
    apiRequest<OffboardingExportLink>({
      method: 'POST',
      path: `/v1/platform/tenants/${id}/offboarding-export/link`,
      body: {},
    }),

  /** Per-tenant quota override; empty body clears the override. */
  setQuotaOverride: (id: string, body: Partial<PlanLimits>) =>
    apiRequest<{ tenant_id: string; override: Partial<PlanLimits>; effective_limits: PlanLimits }>({
      method: 'POST',
      path: `/v1/platform/tenants/${id}/quota-override`,
      body,
    }),
}

/** `none`: nothing is queued for the tenant's current offboarding. */
export type OffboardingExportStatus = 'none' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

/** GET /v1/platform/tenants/{id}/offboarding-export (audit BE-10). */
export interface OffboardingExport {
  tenant_status: TenantStatus
  status: OffboardingExportStatus
  export_id: string | null
  requested_at: string | null
  completed_at: string | null
  size_bytes: number | null
  sha256: string | null
  row_count: number | null
  attempts: number
  max_attempts: number
  /** Failed, with attempts left: the hourly job will try again. */
  retrying: boolean
  /** A platform admin may queue a new export now. */
  can_queue: boolean
  /** When the 90-day cleanup deletes the tenant, the archive with it. */
  deletion_scheduled_at: string | null
}

export interface OffboardingExportLink {
  download_url: string
  expires_at: string
  filename: string
  size_bytes: number | null
  sha256: string | null
}

export interface PlatformDashboardStats {
  tenants: {
    active_tenants: number
    suspended_tenants: number
    offboarded_tenants: number
    starter_tenants: number
    business_tenants: number
    enterprise_tenants: number
  }
  total_users: number
  total_containers: number
}

export interface PlatformSettingsMap {
  default_subscription_tier?: string
  max_tenants?: number
  maintenance_mode?: boolean
  platform_email_from?: string
  platform_name?: string
  support_email?: string
  default_trial_days?: number
  [key: string]: unknown
}

export interface GatewayConfigs {
  sms: { api_key?: string; sender_id?: string; [k: string]: unknown }
  whatsapp: { access_token?: string; phone_number_id?: string; [k: string]: unknown }
  email: { server_token?: string; from_email?: string; [k: string]: unknown }
}

export type GatewayKind = keyof GatewayConfigs

export interface PlanLimits {
  users: number
  containers_per_month: number
  storage_gb: number
}

export interface TenantUsage {
  tenant_id: string
  period: string
  subscription_tier: SubscriptionTier
  limits: {
    users: { used: number; max: number }
    containers_per_month: { used: number; max: number }
    storage_gb: { used: number; max: number }
  }
  api_calls: number
  notifications: { sms_sent: number; whatsapp_sent: number; emails_sent: number }
}

export const platformSettingsApi = {
  get: () => apiRequest<PlatformSettingsMap>({ method: 'GET', path: '/v1/platform/settings' }),
  update: (body: Partial<PlatformSettingsMap>) =>
    apiRequest<PlatformSettingsMap>({ method: 'PUT', path: '/v1/platform/settings', body }),

  getGateways: () => apiRequest<GatewayConfigs>({ method: 'GET', path: '/v1/platform/settings/gateways' }),
  updateGateway: (kind: GatewayKind, body: Record<string, unknown>) =>
    apiRequest<Partial<GatewayConfigs>>({ method: 'PUT', path: `/v1/platform/settings/${kind}-gateway`, body }),
  testGateway: (kind: GatewayKind) =>
    apiRequest<{ success: boolean; error: string | null }>({
      method: 'POST',
      path: `/v1/platform/settings/${kind}-gateway/test`,
      body: {},
    }),

  getPlans: () => apiRequest<{ plans: Record<SubscriptionTier, PlanLimits> }>({ method: 'GET', path: '/v1/platform/plans' }),
  updatePlan: (tier: SubscriptionTier, body: Partial<PlanLimits>) =>
    apiRequest<{ plans: Record<SubscriptionTier, PlanLimits> }>({ method: 'PUT', path: `/v1/platform/plans/${tier}`, body }),
}

export interface PlatformAuditEntry {
  id: string
  action: string
  /** The platform admin's identity subject; null for a platform job. Names arrive with the admin directory (Phase 1). */
  actor_id: string | null
  target_tenant_id: string | null
  /** The tenant's name, joined by the server, so a row never needs the whole tenant list to be labelled. */
  target_tenant_name?: string | null
  details: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Tenant quota
// ---------------------------------------------------------------------------

export interface QuotaDimension {
  used: number
  max: number
}

export interface TenantQuota {
  tenant_id: string
  period: string
  subscription_tier: SubscriptionTier
  limits: {
    users: QuotaDimension
    containers_per_month: QuotaDimension
    storage_gb: QuotaDimension
  }
  api_calls: number
  notifications: {
    sms_sent: number
    whatsapp_sent: number
    emails_sent: number
  }
}

export const quotaApi = {
  getMyQuota: () => apiRequest<TenantQuota>({ method: 'GET', path: '/v1/tenants/me/quota' }),
}
