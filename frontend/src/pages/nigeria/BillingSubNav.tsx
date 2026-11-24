import type { JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../../auth/useSession'
import { Tabs } from '../../shell/Tabs'

export type BillingSubNavTab = 'invoices' | 'disputes' | 'carryovers'

const TABS: { key: BillingSubNavTab; label: string; to: string }[] = [
  { key: 'invoices', label: 'Invoices', to: '/billing' },
  { key: 'disputes', label: 'CBM disputes', to: '/billing/disputes' },
  { key: 'carryovers', label: 'Carryovers', to: '/billing/carryovers' },
]

/**
 * Shared sub-navigation across the Billing workspace (Invoices · CBM disputes · Carryovers).
 * Hidden for China office staff, who only have access to CBM disputes and may not read invoices.
 */
export function BillingSubNav({ active }: { active: BillingSubNavTab }): JSX.Element | null {
  const navigate = useNavigate()
  const { session } = useSession()

  if (session?.role !== 'nigeria_office_staff' && session?.role !== 'tenant_admin') {
    return null
  }

  return (
    <Tabs
      items={TABS.map(({ key, label }) => ({ key, label }))}
      active={active}
      onChange={(key) => {
        const target = TABS.find((t) => t.key === key)
        if (target && target.key !== active) navigate(target.to)
      }}
    />
  )
}
