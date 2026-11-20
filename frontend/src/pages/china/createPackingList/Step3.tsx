import { type JSX } from 'react'
import {
  applyMinCbm,
  buildPackageMix,
  computeCbm,
  formatPackageMix,
} from '../../../api/packingListRules'
import { Banner, Button, Card, Kvp, Mono } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../CreatePackingList.module.css'
import type { PackingListForm } from './useCreatePackingListForm'
import { formatCbm, formatKg } from '../../../lib/format'

/** Step 3: review, then save as a draft or submit for approval. */
export function Step3({ form }: { form: PackingListForm }): JSX.Element {
  const {
    setStep,
    arrivalWarehouseId,
    loadingDate,
    deliveryDate,
    items,
    submitting,
    warehouses,
    minCbm,
    selectedCustomer,
    selectedContainer,
    totals,
    qtyOf,
    requestSave,
  } = form
  return (
    <div className={styles.reviewGrid}>
      <div>
        <Card>
          <SectionHead
            title="Ready to submit"
            sub="Review the summary, then submit for approval."
          />
          <div className={styles.spacerSm} />
          <Banner variant="success" title="All items look valid">
            {/* The word "cartons" was hardcoded, so a list of bales or sacks
                  described itself as cartons on the very screen meant for
                  checking it. */}
            {formatPackageMix(buildPackageMix(items))} captured · all dimensions present · CBM
            totals computed.
          </Banner>
        </Card>
        <div className={styles.spacerSm} />
        {/* Document preview — how this packing list will look when printed */}
        <Card padding="none">
          <div className={styles.previewHeader}>
            <SectionHead
              title="Document preview"
              sub="How this packing list will appear when printed"
            />
          </div>
          <div className={styles.previewBg}>
            <div className={styles.previewDoc}>
              {/* Doc header */}
              <div className={styles.previewDocHead}>
                <div className={styles.previewTenantBlock}>
                  <div className={styles.previewTenantLogo}>PL</div>
                  <div>
                    <div className={styles.previewTenantName}>Packing List</div>
                    <div className={styles.previewTenantSub}>Shipx Logistics</div>
                  </div>
                </div>
                <div className={styles.previewRefBlock}>
                  <div className={styles.previewDocTitle}>PACKING LIST</div>
                  <div className={styles.previewRefSub}>Draft — ref assigned on save</div>
                </div>
              </div>
              {/* Customer / container grid */}
              <div className={styles.previewMeta}>
                <div>
                  <div className={styles.previewMetaLabel}>Customer</div>
                  <div className={styles.previewMetaValue}>{selectedCustomer?.name ?? '—'}</div>
                  {selectedCustomer?.phone && (
                    <div className={styles.previewMetaMono}>{selectedCustomer.phone}</div>
                  )}
                </div>
                <div>
                  <div className={styles.previewMetaLabel}>Container</div>
                  <div className={styles.previewMetaMono}>
                    {selectedContainer?.container_number ?? '—'}
                  </div>
                  {selectedContainer?.vessel_name && (
                    <div className={styles.previewMetaValue}>
                      {selectedContainer.vessel_name}
                      {selectedContainer.voyage_number
                        ? ` · Voy ${selectedContainer.voyage_number}`
                        : ''}
                    </div>
                  )}
                </div>
                {/* Both dates are entered on step 1 and appeared on no
                      preview, so the screen used to verify a list before
                      submitting could not show when it loads or lands. */}
                <div>
                  <div className={styles.previewMetaLabel}>Loading date</div>
                  <div className={styles.previewMetaValue}>{loadingDate || '—'}</div>
                </div>
                <div>
                  <div className={styles.previewMetaLabel}>Delivery date</div>
                  <div className={styles.previewMetaValue}>{deliveryDate || '—'}</div>
                </div>
                <div>
                  <div className={styles.previewMetaLabel}>Arrival warehouse</div>
                  <div className={styles.previewMetaValue}>
                    {warehouses.find((w) => w.id === arrivalWarehouseId)?.name ?? '—'}
                  </div>
                </div>
              </div>
              {/* Items table */}
              <div className={styles.previewTableHead}>
                <span className={styles.previewCol}>Tag</span>
                <span className={[styles.previewCol, styles.previewColDesc].join(' ')}>
                  Description
                </span>
                {/* Type and Qty were missing here, so the review step could
                      not answer "cartons or bales, and how many?" — the two
                      things a checker most needs before submitting. */}
                <span className={styles.previewCol}>Type</span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>Qty</span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>
                  Wt disp.
                </span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>
                  Wt act.
                </span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>L×W×H</span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>CBM</span>
                <span className={[styles.previewCol, styles.previewColRight].join(' ')}>USD</span>
              </div>
              {items.map((item, i) => {
                const cbm =
                  item.length_cm != null && item.width_cm != null && item.height_cm != null
                    ? computeCbm(item.length_cm, item.width_cm, item.height_cm)
                    : null
                const qty = qtyOf(item)
                return (
                  <div key={i} className={styles.previewRow}>
                    <span className={[styles.previewCol, styles.previewMono].join(' ')}>
                      {qty > 1 ? `×${qty}` : '—'}
                    </span>
                    <span className={[styles.previewCol, styles.previewColDesc].join(' ')}>
                      {item.description || '—'}
                    </span>
                    <span className={styles.previewCol}>{item.package_unit ?? 'carton'}</span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                      ].join(' ')}
                    >
                      {qty}
                    </span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                      ].join(' ')}
                    >
                      {item.weight_dispatch_kg != null
                        ? formatKg(item.weight_dispatch_kg * qty)
                        : '—'}
                    </span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                      ].join(' ')}
                    >
                      {item.weight_actual_kg != null
                        ? formatKg(item.weight_actual_kg * qty)
                        : '—'}
                    </span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                      ].join(' ')}
                    >
                      {item.length_cm != null
                        ? `${item.length_cm}×${item.width_cm}×${item.height_cm}`
                        : '—'}
                    </span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                        styles.previewCbm,
                      ].join(' ')}
                    >
                      {/* Line total, not per package: the row stands for
                            `qty` packages and this is the figure that is
                            billed. */}
                      {cbm != null ? formatCbm(applyMinCbm(cbm, minCbm) * qty) : '—'}
                    </span>
                    <span
                      className={[
                        styles.previewCol,
                        styles.previewColRight,
                        styles.previewMono,
                      ].join(' ')}
                    >
                      {item.declared_value_usd != null
                        ? `$${(item.declared_value_usd * qty).toFixed(0)}`
                        : '—'}
                    </span>
                  </div>
                )
              })}
              {/* Totals */}
              <div className={styles.previewTotals}>
                <span>{formatPackageMix(buildPackageMix(items))}</span>
                <span>·</span>
                <span>{formatKg(totals.weightDispatch)} kg disp.</span>
                <span>·</span>
                <span>{formatKg(totals.weight)} kg act.</span>
                <span>·</span>
                <span className={styles.previewCbm}>{formatCbm(totals.cbm)} CBM</span>
                <span>·</span>
                <span>${totals.declaredUsd.toFixed(0)}</span>
              </div>
            </div>
          </div>
        </Card>
      </div>
      <div className={styles.reviewSidebar}>
        <Card>
          <SectionHead title="Summary" />
          <Kvp label="Customer" value={selectedCustomer?.name ?? '—'} />
          <Kvp
            label="Container"
            value={<Mono>{selectedContainer?.container_number ?? '—'}</Mono>}
          />
          <Kvp label="Cartons" value={<Mono>{totals.cartons}</Mono>} />
          <Kvp label="Total weight" value={<Mono>{formatKg(totals.weight)} kg</Mono>} />
          <Kvp
            label="Total CBM"
            value={<Mono color="var(--color-success)">{formatCbm(totals.cbm)}</Mono>}
          />
          <Kvp
            label="Declared value"
            value={<Mono>${totals.declaredUsd.toFixed(0)} USD</Mono>}
            divider={false}
          />
        </Card>
      </div>

      <div className={styles.actionsRowFull}>
        <Button variant="ghost" icon="arrowleft" onClick={() => setStep(2)}>
          Back: Items
        </Button>
        <div className={styles.actionsGroup}>
          <Button variant="secondary" loading={submitting} onClick={() => void requestSave(false)}>
            Save draft
          </Button>
          <Button
            variant="primary"
            icon="check"
            loading={submitting}
            onClick={() => void requestSave(true)}
          >
            Submit for approval
          </Button>
        </div>
      </div>
    </div>
  )
}
