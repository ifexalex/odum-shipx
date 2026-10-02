import { createContext, useContext } from 'react'
import type { UserRole } from './types'

// The 6 single-role dev identities plus one fixed multi-role identity
// ('nigeria_warehouse' = nigeria_office_staff + warehouse_attendant) used to
// exercise the role-switch toggle locally without redesigning the whole
// switcher — see LocalAuthProvider's IDENTITY_ROLES map.
export type DevIdentityKey = UserRole | 'nigeria_warehouse'

export interface LocalRoleContextValue {
  identity: DevIdentityKey
  setIdentity: (identity: DevIdentityKey) => void
}

export const LocalRoleContext = createContext<LocalRoleContextValue | null>(null)

export function useLocalRole(): LocalRoleContextValue {
  const ctx = useContext(LocalRoleContext)
  if (!ctx) throw new Error('useLocalRole must be used within a LocalAuthProvider')
  return ctx
}
