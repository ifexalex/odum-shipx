import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { configKeys } from '../api/keys'
import { configApi, type BrandingConfig, type UpdateCbmRateInput, type UpdateDollarRateMarkupInput } from '../api/tenantManagement'
import { STALE_FOREVER } from '../lib/queryClient'
import { uploadTenantLogo } from '../api/uploads'
import { FRESH_ON_OPEN } from './useSeedOnce'

/** `freshOnOpen` is for the settings form: see FRESH_ON_OPEN. */
interface ConfigReadOptions {
  freshOnOpen?: boolean
}

export function useDollarRate(options: ConfigReadOptions = {}) {
  return useQuery({
    queryKey: configKeys.dollar(),
    queryFn: () => configApi.getDollarRate(),
    ...(options.freshOnOpen ? FRESH_ON_OPEN : {}),
    // Not STALE_FOREVER like the other rate/config hooks — the effective
    // rate now tracks Bybit's live P2P market (shared/fx_rate.py, ~10 min
    // server-side cache) rather than a value an admin sets once and rarely
    // touches again, so this needs to be allowed to refetch.
  })
}

export function useCbmRate(options: ConfigReadOptions = {}) {
  return useQuery({
    queryKey: configKeys.cbm(),
    queryFn: () => configApi.getCbmRate(),
    staleTime: STALE_FOREVER,
    ...(options.freshOnOpen ? FRESH_ON_OPEN : {}),
  })
}

export function useWebhookConfig(options: ConfigReadOptions = {}) {
  return useQuery({
    queryKey: configKeys.webhook(),
    queryFn: () => configApi.getConfig(),
    staleTime: STALE_FOREVER,
    ...(options.freshOnOpen ? FRESH_ON_OPEN : {}),
  })
}

/** The tenant's charge types (active and retired). Any charge-type write invalidates it. */
export function useChargeTypes() {
  return useQuery({ queryKey: configKeys.chargeTypes(), queryFn: () => configApi.listChargeTypes() })
}

/** Every change to a rate, newest first, for the history table and trend chart. Non-fatal: the table degrades to empty. */
export function useRateHistory(rateType: 'dollar_rate' | 'cbm_rate') {
  return useQuery({
    queryKey: configKeys.rateHistory(rateType),
    queryFn: () => configApi.rateHistory(rateType),
  })
}

export function useUpdateDollarRate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateDollarRateMarkupInput) => configApi.updateDollarRate(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: configKeys.dollar() }) },
  })
}

export function useUpdateCbmRate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateCbmRateInput) => configApi.updateCbmRate(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: configKeys.cbm() }) },
  })
}

export function useSaveWebhookConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof configApi.updateConfig>[0]) => configApi.updateConfig(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: configKeys.webhook() }) },
  })
}

export function useRotateWebhookSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => configApi.rotateWebhookSecret(),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: configKeys.webhook() }) },
  })
}

export function useTestWebhook() {
  return useMutation({
    mutationFn: () => configApi.testWebhook(),
  })
}

/**
 * Tenant branding (prototype 4.1 — Company Settings). Readable by every staff
 * role (GET /v1/tenant/config was widened for exactly this — the print
 * documents and staff shell theme both consume it); writes stay tenant_admin.
 * `enabled` lets non-staff surfaces (customer portal) skip the fetch entirely.
 */
export function useBranding(enabled = true) {
  const query = useQuery({
    queryKey: configKeys.tenantConfig(),
    queryFn: () => configApi.getConfig(),
    staleTime: STALE_FOREVER,
    enabled,
  })
  return { ...query, branding: query.data?.branding_config ?? null }
}

/**
 * The whole tenant config (GET /v1/tenant/config), for the settings forms that edit one part of it. Shares
 * `configKeys.tenantConfig()` with `useBranding` and `useBankTransferConfig`, so two panels on one page make one request.
 */
export function useTenantConfig(options: ConfigReadOptions = {}) {
  return useQuery({
    queryKey: configKeys.tenantConfig(),
    queryFn: () => configApi.getConfig(),
    staleTime: STALE_FOREVER,
    ...(options.freshOnOpen ? FRESH_ON_OPEN : {}),
  })
}

/**
 * Bank-transfer details for the customer-facing manual-payment panel.
 *
 * Shares `configKeys.tenantConfig()` with `useBranding` — both read the same
 * GET /v1/tenant/config response, so the customer billing page reuses whatever
 * the shell already fetched instead of issuing its own request.
 */
export function useBankTransferConfig(enabled = true) {
  const query = useQuery({
    queryKey: configKeys.tenantConfig(),
    queryFn: () => configApi.getConfig(),
    staleTime: STALE_FOREVER,
    enabled,
  })
  return { ...query, bankConfig: query.data?.bank_transfer_config ?? null }
}

export function useSaveBranding() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (branding: BrandingConfig) => configApi.updateConfig({ branding }),
    onSuccess: (updated) => {
      // PUT returns the full updated config — write it into the cache directly
      // so the form re-syncs to the saved state without a refetch race.
      qc.setQueryData(configKeys.tenantConfig(), updated)
      // webhook() caches the same GET /v1/tenant/config response shape.
      void qc.invalidateQueries({ queryKey: configKeys.webhook() })
    },
  })
}

/**
 * Upload a logo or stop using one (FD-29). Either way the config is read again, so every consumer (the settings page,
 * printed documents) gets the new `logo_url`.
 */
export function useTenantLogo() {
  const qc = useQueryClient()
  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: configKeys.tenantConfig() })
  }
  const upload = useMutation({ mutationFn: (file: File) => uploadTenantLogo(file), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => configApi.removeLogo(), onSuccess: refresh })
  return { upload, remove }
}
