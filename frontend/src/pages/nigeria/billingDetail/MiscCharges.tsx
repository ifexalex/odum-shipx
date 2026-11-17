import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { billingApi, type Billing } from '../../../api/billing'
import { ApiError } from '../../../api/client'
import { billingKeys } from '../../../api/keys'
import { Button, Card, Mono, Table } from '../../../design/components'
import { formatNgn } from '../../../lib/format'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../BillingDetail.module.css'

interface MiscChargesSectionProps {
  billing: Billing
  /** Tenant admin on an unpaid invoice (the API's own rule). */
  canRemove: boolean
  /** Called after a charge is removed, to refresh the invoice. */
  onChanged: () => void
  onError: (message: string) => void
}

/** Miscellaneous charges, with full rows (and ids) so an admin can remove one (7.2 prototype). */
export function MiscChargesSection({
  billing,
  canRemove,
  onChanged,
  onError,
}: MiscChargesSectionProps): JSX.Element | null {
  const [removingChargeId, setRemovingChargeId] = useState<string | null>(null)
  // Full misc-charge rows (with ids) — the embedded misc_fees list has no ids,
  // so add/remove (prototype 7.2 AddChargeModal + removable rows) needs this.
  const { data: miscCharges = [], refetch: refetchCharges } = useQuery({
    queryKey: [...billingKeys.detail(billing.id), 'charges'],
    queryFn: () => billingApi.listMiscCharges(billing.id),
    staleTime: 5 * 60 * 1000,
  })

  async function handleRemoveCharge(chargeId: string): Promise<void> {
    setRemovingChargeId(chargeId)
    try {
      await billingApi.deleteMiscCharge(billing.id, chargeId)
      await refetchCharges()
      onChanged()
    } catch (err) {
      onError(err instanceof ApiError ? err.message : 'Could not remove charge.')
    } finally {
      setRemovingChargeId(null)
    }
  }

  if (miscCharges.length === 0 && billing.misc_fees.length === 0) return null
  return (
    <div className={styles.section}>
      <SectionHead
        title="Miscellaneous charges"
        sub={miscCharges.length > 0 ? `${miscCharges.length} charge(s)` : undefined}
      />
      <Card padding={0}>
        <Table
          columns={[
            { title: 'Charge' },
            { title: 'Type' },
            { title: 'Amount (₦)', align: 'right' },
            ...(canRemove ? [{ title: '', width: '48px' }] : []),
          ]}
          rows={
            miscCharges.length > 0
              ? miscCharges.map((c) => ({
                  cells: [
                    <span key="desc">{c.description}</span>,
                    <span key="type" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
                      {c.charge_type.replace(/_/g, ' ')}
                    </span>,
                    <Mono key="amt">{formatNgn(c.amount_ngn)}</Mono>,
                    ...(canRemove
                      ? [
                          <Button
                            key="rm"
                            variant="ghost"
                            size="sm"
                            icon="x"
                            aria-label="Remove charge"
                            loading={removingChargeId === c.id}
                            onClick={() => void handleRemoveCharge(c.id)}
                          />,
                        ]
                      : []),
                  ],
                }))
              : billing.misc_fees.map((f) => ({
                  cells: [
                    <span key="desc">{f.description}</span>,
                    <span key="type" />,
                    <Mono key="amt">{formatNgn(f.amount_ngn)}</Mono>,
                    ...(canRemove ? [<span key="rm" />] : []),
                  ],
                }))
          }
        />
      </Card>
    </div>
  )
}
