import { type JSX } from 'react'
import { Avatar, Badge, Card, Icon, Mono } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../CreatePackingList.module.css'
import { formatCbm, formatNgn } from '../../../lib/format'
import type { PackingListForm } from './useCreatePackingListForm'

/** Who and where this cargo is for, kept in view while the items are entered. */
export function ContextBar({ form }: { form: PackingListForm }): JSX.Element {
  const { selectedCustomer, selectedContainer } = form
  return (
    <Card padding="default">
      <div className={styles.contextBar}>
        {selectedCustomer && (
          <div className={styles.contextParty}>
            <Avatar size={32} name={selectedCustomer.name ?? '?'} roleColor="nigeria" />
            <div>
              <div className={styles.contextName}>{selectedCustomer.name}</div>
              {selectedCustomer.phone && (
                <div className={styles.contextSub}>{selectedCustomer.phone}</div>
              )}
            </div>
          </div>
        )}
        <span className={styles.dividerDot}>·</span>
        <div className={styles.contextParty}>
          <Icon name="container" size={16} color="var(--color-info)" />
          <div>
            <Mono>{selectedContainer?.container_number}</Mono>
            {selectedContainer?.vessel_name && (
              <div className={styles.contextSub}>
                {selectedContainer.vessel_name}
                {selectedContainer.estimated_arrival_date &&
                  ` · ETA ${selectedContainer.estimated_arrival_date}`}
              </div>
            )}
          </div>
        </div>
        <span className={styles.contextSpacer} />
        <Badge variant="neutral">Draft — assigned on save</Badge>
      </div>
    </Card>
  )
}

/** The live estimate from the current CBM and dollar rates; the invoice itself is made in Nigeria. */
export function PricingEstimate({ form }: { form: PackingListForm }): JSX.Element {
  const { cbmRate, cbmCurrency, fxRate, totals, shippingUsd, shippingNgn } = form
  return (
    <Card>
      <SectionHead
        title="Live pricing estimate"
        sub="Computed from the current CBM + FX rates · final billing happens in Nigeria"
      />
      <div className={styles.spacerSm} />
      <div className={styles.priceTiles}>
        <div className={styles.priceTile}>
          <div className={styles.priceLabel}>Total CBM</div>
          <div className={styles.priceValue}>{formatCbm(totals.cbm)}</div>
          <div className={styles.priceSub}>auto-computed</div>
        </div>
        <div className={styles.priceTile}>
          <div className={styles.priceLabel}>CBM rate</div>
          <div className={styles.priceValue}>
            {cbmRate != null ? `${cbmCurrency === 'ngn' ? '₦' : '$'}${cbmRate.toFixed(2)}` : '—'}
          </div>
          <div className={styles.priceSub}>per cubic meter</div>
        </div>
        <div className={styles.priceTile}>
          <div className={styles.priceLabel}>Shipping (USD)</div>
          <div className={styles.priceValue}>
            {shippingUsd != null ? `$${shippingUsd.toFixed(2)}` : '—'}
          </div>
          <div className={styles.priceSub}>
            {cbmCurrency === 'usd'
              ? cbmRate != null
                ? `${formatCbm(totals.cbm)} × $${cbmRate.toFixed(2)}`
                : 'rate unavailable'
              : fxRate != null
                ? 'derived from ₦ via FX'
                : 'FX unavailable'}
          </div>
        </div>
        <div className={[styles.priceTile, styles.priceTileHighlight].join(' ')}>
          <div className={styles.priceLabel}>Shipping (NGN)</div>
          <div className={styles.priceValue}>
            {shippingNgn != null ? formatNgn(Math.round(shippingNgn)) : '—'}
          </div>
          <div className={styles.priceSub}>
            {cbmCurrency === 'ngn'
              ? cbmRate != null
                ? `${formatCbm(totals.cbm)} × ₦${cbmRate.toFixed(2)}`
                : 'rate unavailable'
              : fxRate != null
                ? `× ${formatNgn(fxRate)} FX`
                : 'FX unavailable'}
          </div>
        </div>
      </div>
    </Card>
  )
}
