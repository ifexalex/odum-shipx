import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { configKeys } from '../api/keys'
import { configApi, type BrandingConfig, type UpdateCbmRateInput, type UpdateDollarRateMarkupInput } from '../api/tenantManagement'
import { STALE_FOREVER } from '../lib/queryClient'

export function useDollarRate() {
  return useQuery({
    queryKey: configKeys.dollar(),
    queryFn: () => configApi.getDollarRate(),
    // Not STALE_FOREVER like the other rate/config hooks — the effective
    // rate now tracks Bybit's live P2P market (shared/fx_rate.py, ~10 min
    // server-side cache) rather than a value an admin sets once and rarely
    // touches again, so this needs to be allowed to refetch.
  })
}

export function useCbmRate() {
  return useQuery({
    queryKey: configKeys.cbm(),
    queryFn: () => configApi.getCbmRate(),
    staleTime: STALE_FOREVER,
  })
}

export function useWebhookConfig() {
  return useQuery({
    queryKey: configKeys.webhook(),
    queryFn: () => configApi.getConfig(),
    staleTime: STALE_FOREVER,
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
