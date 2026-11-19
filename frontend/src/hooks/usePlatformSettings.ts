import { useQuery } from '@tanstack/react-query'
import { platformSettingsKeys } from '../api/keys'
import { platformSettingsApi } from '../api/tenantManagement'
import { FRESH_ON_OPEN } from './useSeedOnce'

// Each of these feeds a settings form, so each re-reads when the form opens (FRESH_ON_OPEN): a form must not be
// filled from a copy another platform admin has since changed. Any platform settings or plan write invalidates all
// three (api/cacheInvalidation.ts).

export function usePlatformGeneralSettings() {
  return useQuery({ queryKey: platformSettingsKeys.general(), queryFn: () => platformSettingsApi.get(), ...FRESH_ON_OPEN })
}

export function usePlatformGateways() {
  return useQuery({ queryKey: platformSettingsKeys.gateways(), queryFn: () => platformSettingsApi.getGateways(), ...FRESH_ON_OPEN })
}

export function usePlatformPlans() {
  return useQuery({ queryKey: platformSettingsKeys.plans(), queryFn: () => platformSettingsApi.getPlans(), ...FRESH_ON_OPEN })
}
