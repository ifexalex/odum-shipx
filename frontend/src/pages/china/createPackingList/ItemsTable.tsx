import { useEffect, useRef, useState, type JSX } from 'react'
import {
  applyMinCbm,
  baleSizeAbbr,
  buildPackageMix,
  formatPackageMix,
} from '../../../api/packingListRules'
import { PACKAGE_UNITS, type PackageUnit } from '../../../api/packingList'
import {
  Badge,
  Button,
  Card,
  Icon,
  Mono,
  IconButton,
  CellSelect,
  CellInput,
  CellCheckbox,
} from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../CreatePackingList.module.css'
import { blockInvalidNumberKeys, clampQuantity, emptyItem, sanitizeNumber } from './items'
import type { PackingListForm } from './useCreatePackingListForm'
import { formatCbm, formatKg } from '../../../lib/format'

/** The line items: spacious two-row cards with package type, dimensions, CBM, weight, qty and declared value. */
export function ItemsTable({ form }: { form: PackingListForm }): JSX.Element {
  const {
    items,
    setItems,
    deliveryDateMode,
    deliveryDate,
    loadingDate,
    today,
    itemDateErrors,
    minCbm,
    totals,
    exceedsCapacity,
    remainingCapacityCbm,
    rawCbm,
    qtyOf,
    updateItem,
    removeItem,
    duplicateItem,
    removeBatch,
    batchSize,
  } = form
  const listRef = useRef<HTMLDivElement>(null)
  const focusRowIndexRef = useRef<number | null>(null)
  const [customLoadOpen, setCustomLoadOpen] = useState<Record<number, boolean>>({})

  useEffect(() => {
    const idx = focusRowIndexRef.current
    if (idx === null) return
    focusRowIndexRef.current = null
    const input = listRef.current?.querySelector<HTMLInputElement>(
      `input[aria-label="Description, item ${idx + 1}"]`,
    )
    input?.focus()
  }, [items.length])

  function handleAddRow(): void {
    focusRowIndexRef.current = items.length
    setItems((prev) => [...prev, emptyItem()])
  }

  return (
    <Card padding="none">
      <div className={styles.itemsHead}>
        <SectionHead
          title="Line items"
          sub={`Pick a package type per item. CBM is computed from L × W × H and floored at ${minCbm} CBM per unit.`}
        />
        <div className={styles.actionsGroup}>
          <Button variant="primary" size="sm" icon="plus" onClick={handleAddRow}>
            Add item
          </Button>
        </div>
      </div>

      <div ref={listRef} className={styles.itemList}>
        {items.map((item, index) => {
          const raw = rawCbm(item)
          const hasData = item.description.trim() !== '' || raw > 0
          const effectiveCbm = applyMinCbm(raw, minCbm)
          const floored = raw > 0 && raw < minCbm
          const isBale = item.package_unit === 'bale'
          const qty = qtyOf(item)
          const lineCbm = effectiveCbm * qty
          return (
            <div key={index} className={styles.itemCard}>
              {/* Header bar: item index + tag status on the left, live CBM/bale badges + row actions on the right */}
              <div className={styles.itemCardHead}>
                <div className={styles.itemIndexGroup}>
                  <span className={styles.itemNumber}>#{index + 1}</span>
                  <span className={styles.assignedOnSave}>Tag assigned on save</span>
                </div>
                <div className={styles.itemBadgesAndActions}>
                  <div className={styles.cbmCell}>
                    <span className={styles.cbmChip}>
                      {hasData ? `${formatCbm(lineCbm)} CBM` : '— CBM'}
                    </span>
                    {hasData && floored && (
                      <span
                        className={styles.minTag}
                        title={`Floored to the ${minCbm} CBM minimum per unit`}
                      >
                        min
                      </span>
                    )}
                    {isBale && hasData && (
                      <Badge variant={effectiveCbm >= 0.3 ? 'info' : 'neutral'} size="sm">
                        {baleSizeAbbr(effectiveCbm)}
                      </Badge>
                    )}
                  </div>
                  <div className={styles.itemRowActions}>
                    <IconButton
                      icon="copy"
                      variant="ghost"
                      size="sm"
                      label={`Duplicate item ${index + 1}`}
                      title="Duplicate this item"
                      onClick={() => {
                        focusRowIndexRef.current = index + 1
                        duplicateItem(index)
                      }}
                    />
                    <IconButton
                      icon="x"
                      variant="danger-ghost"
                      size="sm"
                      label={
                        batchSize(item.batch_ref) > 1
                          ? `Remove all ${batchSize(item.batch_ref)} packages in this batch`
                          : `Remove item ${index + 1}`
                      }
                      title={
                        batchSize(item.batch_ref) > 1
                          ? `Removes all ${batchSize(item.batch_ref)} identical packages entered together`
                          : 'Remove item'
                      }
                      disabled={items.length === 1}
                      onClick={() =>
                        batchSize(item.batch_ref) > 1 && item.batch_ref
                          ? removeBatch(item.batch_ref)
                          : removeItem(index)
                      }
                    />
                  </div>
                </div>
              </div>

              {/* Row 1: Description and Package Type */}
              <div className={styles.itemRowPrimary}>
                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>Description</span>
                  <CellInput
                    label={`Description, item ${index + 1}`}
                    className={styles.cellInput}
                    value={item.description}
                    placeholder="e.g. Electronics (mixed)"
                    onChange={(event) =>
                      updateItem(index, {
                        description: event.target.value,
                      })
                    }
                  />
                </div>

                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>Type</span>
                  <CellSelect
                    label={`Package type for item ${index + 1}`}
                    className={styles.typeSelect}
                    value={item.package_unit ?? 'carton'}
                    onChange={(event) =>
                      updateItem(index, {
                        package_unit: event.target.value as PackageUnit,
                      })
                    }
                  >
                    {PACKAGE_UNITS.map((u) => (
                      <option key={u.value} value={u.value}>
                        {u.label}
                      </option>
                    ))}
                  </CellSelect>
                </div>
              </div>

              {/* Row 2: Dispatch weight, Actual weight, Dimensions (L × W × H cm), Qty, Declared value per unit */}
              <div className={styles.itemRowMetrics}>
                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>Wt disp. (kg)</span>
                  <CellInput
                    label={`Dispatch weight (kg), item ${index + 1}`}
                    className={styles.cellInputNumber}
                    type="number"
                    min={0}
                    placeholder="0"
                    inputMode="decimal"
                    value={item.weight_dispatch_kg ?? ''}
                    onKeyDown={blockInvalidNumberKeys}
                    onChange={(event) =>
                      updateItem(index, {
                        weight_dispatch_kg: sanitizeNumber(event.target.value),
                      })
                    }
                  />
                </div>

                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>Wt act. (kg)</span>
                  <CellInput
                    label={`Actual weight (kg), item ${index + 1}`}
                    className={styles.cellInputNumber}
                    type="number"
                    min={0}
                    placeholder="0"
                    inputMode="decimal"
                    value={item.weight_actual_kg ?? ''}
                    onKeyDown={blockInvalidNumberKeys}
                    onChange={(event) =>
                      updateItem(index, {
                        weight_actual_kg: sanitizeNumber(event.target.value),
                      })
                    }
                  />
                </div>

                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>L × W × H (cm)</span>
                  <div className={styles.dimRow}>
                    <CellInput
                      label={`Length (cm), item ${index + 1}`}
                      className={styles.dimInput}
                      type="number"
                      min={0}
                      placeholder="L"
                      inputMode="decimal"
                      value={item.length_cm ?? ''}
                      onKeyDown={blockInvalidNumberKeys}
                      onChange={(event) =>
                        updateItem(index, {
                          length_cm: sanitizeNumber(event.target.value),
                        })
                      }
                    />
                    <span className={styles.dimSep}>×</span>
                    <CellInput
                      label={`Width (cm), item ${index + 1}`}
                      className={styles.dimInput}
                      type="number"
                      min={0}
                      placeholder="W"
                      inputMode="decimal"
                      value={item.width_cm ?? ''}
                      onKeyDown={blockInvalidNumberKeys}
                      onChange={(event) =>
                        updateItem(index, {
                          width_cm: sanitizeNumber(event.target.value),
                        })
                      }
                    />
                    <span className={styles.dimSep}>×</span>
                    <CellInput
                      label={`Height (cm), item ${index + 1}`}
                      className={styles.dimInput}
                      type="number"
                      min={0}
                      placeholder="H"
                      inputMode="decimal"
                      value={item.height_cm ?? ''}
                      onKeyDown={blockInvalidNumberKeys}
                      onChange={(event) =>
                        updateItem(index, {
                          height_cm: sanitizeNumber(event.target.value),
                        })
                      }
                    />
                  </div>
                </div>

                <div className={styles.itemField}>
                  <div className={styles.qtyHeaderRow}>
                    <span className={styles.itemFieldLabel}>Qty</span>
                    <label
                      className={[
                        styles.qtyConfirm,
                        item.identical_confirmed ? styles.qtyConfirmOn : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      title={
                        'Tick only when every package on this line has the same dimensions ' +
                        'and weight. One wrong measurement is repeated across all of them, ' +
                        'and CBM drives billing.'
                      }
                    >
                      <CellCheckbox
                        checked={item.identical_confirmed ?? false}
                        label={`Item ${index + 1}: all packages identical`}
                        onChange={(event) =>
                          updateItem(index, {
                            identical_confirmed: event.target.checked,
                            ...(event.target.checked ? {} : { quantity: 1 }),
                          })
                        }
                      />
                      <span>identical</span>
                    </label>
                  </div>
                  <CellInput
                    className={styles.qtyInput}
                    type="number"
                    min={1}
                    step={1}
                    inputMode="numeric"
                    label={`Item ${index + 1}: quantity`}
                    disabled={!(item.identical_confirmed ?? false)}
                    title={
                      item.identical_confirmed
                        ? 'How many identical packages under one tag (bounded by container CBM capacity)'
                        : 'Tick "identical" first — all packages share one tag'
                    }
                    value={item.quantity ?? ''}
                    onKeyDown={blockInvalidNumberKeys}
                    onChange={(event) =>
                      updateItem(index, {
                        quantity: clampQuantity(event.target.value),
                      })
                    }
                  />
                </div>

                <div className={styles.itemField}>
                  <span className={styles.itemFieldLabel}>Decl. / unit (USD)</span>
                  <CellInput
                    label={`Declared value per unit (USD), item ${index + 1}`}
                    className={styles.cellInputNumber}
                    type="number"
                    min={0}
                    placeholder="0"
                    inputMode="decimal"
                    value={item.declared_value_usd ?? ''}
                    onKeyDown={blockInvalidNumberKeys}
                    onChange={(event) =>
                      updateItem(index, {
                        declared_value_usd: sanitizeNumber(event.target.value),
                      })
                    }
                  />
                </div>
              </div>

              {/* Row 3 (ENG-3): Per-item delivery date (multiple_days mode) and optional per-item loading date override */}
              {(deliveryDateMode === 'multiple_days' ||
                Boolean(item.loading_date) ||
                customLoadOpen[index]) ? (
                <div className={styles.itemDatesRow}>
                  {deliveryDateMode === 'multiple_days' && (
                    <div className={styles.itemField}>
                      <span className={styles.itemFieldLabel}>Delivery date</span>
                      <CellInput
                        label={`Delivery date, item ${index + 1}`}
                        className={styles.itemDateInput}
                        type="date"
                        max={today}
                        value={item.received_date ?? ''}
                        onChange={(event) =>
                          updateItem(index, {
                            received_date: event.target.value || undefined,
                          })
                        }
                      />
                    </div>
                  )}
                  <div className={styles.itemField}>
                    <span className={styles.itemFieldLabel}>
                      Loading date override (optional)
                    </span>
                    <CellInput
                      label={`Loading date override, item ${index + 1}`}
                      className={styles.itemDateInput}
                      type="date"
                      min={
                        (deliveryDateMode === 'same_day' ? deliveryDate : item.received_date) ||
                        undefined
                      }
                      value={item.loading_date ?? ''}
                      onChange={(event) =>
                        updateItem(index, {
                          loading_date: event.target.value || undefined,
                        })
                      }
                    />
                  </div>
                  {itemDateErrors[index] && (
                    <span className={styles.itemDateError}>{itemDateErrors[index]}</span>
                  )}
                </div>
              ) : (
                <div className={styles.itemDateToggleWrap}>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setCustomLoadOpen((prev) => ({ ...prev, [index]: true }))
                    }
                  >
                    Different loading date?
                    {loadingDate ? ` (default: ${loadingDate})` : ''}
                  </Button>
                </div>
              )}

              {qty > 1 && (
                <div className={styles.qtyPreviewWrap}>
                  <span className={styles.qtyPreview}>
                    <Icon name="plus" size={12} />
                    {[
                      `${qty} ${item.package_unit ?? 'carton'}${qty === 1 ? '' : 's'}`,
                      hasData ? `${formatCbm(lineCbm)} CBM` : null,
                      item.weight_actual_kg != null
                        ? `${formatKg(item.weight_actual_kg * qty)} kg`
                        : null,
                      item.declared_value_usd != null
                        ? `$${(item.declared_value_usd * qty).toFixed(0)} declared ($${item.declared_value_usd}/unit)`
                        : null,
                      'one tag for all packages',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Totals footer bar — always visible with zero horizontal scrolling */}
      <div className={styles.itemTotalsBar}>
        <span className={styles.totalsLabel}>
          Totals — {formatPackageMix(buildPackageMix(items))}
        </span>
        <div className={styles.itemTotalsMetrics}>
          <span>
            <span className={styles.itemTotalKey}>Disp.</span>{' '}
            <Mono>{formatKg(totals.weightDispatch)} kg</Mono>
          </span>
          <span>
            <span className={styles.itemTotalKey}>Actual</span>{' '}
            <Mono>{formatKg(totals.weight)} kg</Mono>
          </span>
          <span>
            <span className={styles.itemTotalKey}>Volume</span>{' '}
            <Mono color={exceedsCapacity ? 'var(--color-error)' : 'var(--color-primary-text)'}>
              {formatCbm(totals.cbm)} CBM
            </Mono>
            {exceedsCapacity && remainingCapacityCbm != null && (
              <>
                {' '}
                <Badge variant="error" size="sm">
                  +{formatCbm(totals.cbm - remainingCapacityCbm)} CBM over capacity
                </Badge>
              </>
            )}
          </span>
          <span>
            <span className={styles.itemTotalKey}>Declared</span>{' '}
            <Mono>${totals.declaredUsd.toFixed(0)}</Mono>
          </span>
        </div>
      </div>

      <div className={styles.addAnotherRow}>
        <Button variant="ghost" icon="plus" onClick={handleAddRow}>
          Add another item
        </Button>
      </div>
    </Card>
  )
}
