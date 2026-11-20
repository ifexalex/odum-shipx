import { Fragment, type JSX } from 'react'
import {
  applyMinCbm,
  baleSizeAbbr,
  buildPackageMix,
  formatPackageMix,
} from '../../../api/packingListRules'
import { MAX_ITEM_QUANTITY, PACKAGE_UNITS, type PackageUnit } from '../../../api/packingList'
import { Badge, Button, Card, Icon, Mono, IconButton, CellSelect, CellInput, CellCheckbox } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../CreatePackingList.module.css'
import { blockInvalidNumberKeys, clampQuantity, emptyItem, sanitizeNumber } from './items'
import type { PackingListForm } from './useCreatePackingListForm'
import { formatCbm, formatKg } from '../../../lib/format'

/** The line items: one row per carton or batch, with package type, size, CBM, weight and value. */
export function ItemsTable({ form }: { form: PackingListForm }): JSX.Element {
  const {
    navigate,
    items,
    setItems,
    minCbm,
    totals,
    rawCbm,
    qtyOf,
    updateItem,
    removeItem,
    removeBatch,
    batchSize,
  } = form
  return (
    <Card padding="none">
      <div className={styles.itemsHead}>
        <SectionHead
          title="Line items"
          sub={`Pick a package type per row. CBM is computed from L × W × H and floored at ${minCbm} CBM.`}
        />
        <div className={styles.actionsGroup}>
          <Button
            variant="secondary"
            size="sm"
            icon="upload"
            onClick={() => navigate('/packing-lists/import')}
          >
            Import CSV
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon="plus"
            onClick={() => setItems((prev) => [...prev, emptyItem()])}
          >
            Add item
          </Button>
        </div>
      </div>
      <div className={styles.itemsTableWrap}>
        <table className={styles.itemsTable}>
          <thead>
            <tr>
              <th>Tag</th>
              <th>Description</th>
              <th>Type</th>
              <th className={styles.right}>Wt disp. (kg)</th>
              <th className={styles.right}>Wt act. (kg)</th>
              <th className={styles.center}>L × W × H (cm)</th>
              <th className={[styles.right, styles.cbmHead].join(' ')}>CBM</th>
              <th className={styles.center}>Qty</th>
              <th className={styles.right}>Decl. (USD)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const raw = rawCbm(item)
              const hasData = item.description.trim() !== '' || raw > 0
              const effectiveCbm = applyMinCbm(raw, minCbm)
              const floored = raw > 0 && raw < minCbm
              const isBale = item.package_unit === 'bale'
              return (
                // Fragment: a bulk line renders its own preview row
                // beneath the inputs, so the map yields two <tr>s.
                <Fragment key={index}>
                  <tr key={index}>
                    <td>
                      <span className={styles.assignedOnSave}>On save</span>
                    </td>
                    <td>
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
                    </td>
                    <td>
                      <CellSelect
                        label={`Package type for item ${index + 1}`}
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
                    </td>
                    <td className={styles.right}>
                      <CellInput
                        label={`Dispatch weight (kg), item ${index + 1}`}
                        className={styles.cellInputNumber}
                        type="number"
                        min={0}
                        inputMode="decimal"
                        value={item.weight_dispatch_kg ?? ''}
                        onKeyDown={blockInvalidNumberKeys}
                        onChange={(event) =>
                          updateItem(index, {
                            weight_dispatch_kg: sanitizeNumber(event.target.value),
                          })
                        }
                      />
                    </td>
                    <td className={styles.right}>
                      <CellInput
                        label={`Actual weight (kg), item ${index + 1}`}
                        className={styles.cellInputNumber}
                        type="number"
                        min={0}
                        inputMode="decimal"
                        value={item.weight_actual_kg ?? ''}
                        onKeyDown={blockInvalidNumberKeys}
                        onChange={(event) =>
                          updateItem(index, {
                            weight_actual_kg: sanitizeNumber(event.target.value),
                          })
                        }
                      />
                    </td>
                    <td>
                      <div className={styles.dimRow}>
                        <CellInput
                        label={`Length (cm), item ${index + 1}`}
                          className={styles.dimInput}
                          type="number"
                          min={0}
                          inputMode="decimal"
                          value={item.length_cm ?? ''}
                          onKeyDown={blockInvalidNumberKeys}
                          onChange={(event) =>
                            updateItem(index, {
                              length_cm: sanitizeNumber(event.target.value),
                            })
                          }
                        />
                        <span>×</span>
                        <CellInput
                        label={`Width (cm), item ${index + 1}`}
                          className={styles.dimInput}
                          type="number"
                          min={0}
                          inputMode="decimal"
                          value={item.width_cm ?? ''}
                          onKeyDown={blockInvalidNumberKeys}
                          onChange={(event) =>
                            updateItem(index, {
                              width_cm: sanitizeNumber(event.target.value),
                            })
                          }
                        />
                        <span>×</span>
                        <CellInput
                        label={`Height (cm), item ${index + 1}`}
                          className={styles.dimInput}
                          type="number"
                          min={0}
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
                    </td>
                    <td className={styles.right}>
                      <div className={styles.cbmCell}>
                        <span className={styles.cbmChip}>
                          {hasData ? formatCbm(effectiveCbm) : '—'}
                        </span>
                        {hasData && floored && (
                          <span
                            className={styles.minTag}
                            title={`Floored to the ${minCbm} CBM minimum`}
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
                    </td>
                    <td className={styles.center}>
                      {/* The affirmation sits directly above the input it
                        unlocks, so the relationship reads without
                        explanation. Kept there rather than moved beside
                        the row or into the preview: the hazard is not a
                        typo — a typo looks wrong — it is an oversight,
                        100 cartons recorded at one carton's weight
                        because they were nearly identical. Putting the
                        assertion in the path to the number is the whole
                        point, and anywhere else loosens that. The server
                        enforces the same rule, so this is a prompt, not
                        the protection. */}
                      <div className={styles.qtyCell}>
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
                                // Unticking returns the line to a single
                                // package, so a stale 100 cannot be saved
                                // by clearing the box and missing the
                                // input.
                                ...(event.target.checked ? {} : { quantity: 1 }),
                              })
                            }
                          />
                          <span>identical</span>
                        </label>
                        <CellInput
                          className={styles.qtyInput}
                          type="number"
                          min={1}
                          max={MAX_ITEM_QUANTITY}
                          step={1}
                          inputMode="numeric"
                          label={`Item ${index + 1}: quantity`}
                          disabled={!(item.identical_confirmed ?? false)}
                          title={
                            item.identical_confirmed
                              ? `How many identical packages (up to ${MAX_ITEM_QUANTITY})`
                              : 'Tick "identical" first — each package is created separately'
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
                    </td>
                    <td className={styles.right}>
                      <CellInput
                        label={`Declared value (USD), item ${index + 1}`}
                        className={styles.cellInputNumber}
                        type="number"
                        min={0}
                        inputMode="decimal"
                        value={item.declared_value_usd ?? ''}
                        onKeyDown={blockInvalidNumberKeys}
                        onChange={(event) =>
                          updateItem(index, {
                            declared_value_usd: sanitizeNumber(event.target.value),
                          })
                        }
                      />
                    </td>
                    <td>
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
                            : undefined
                        }
                        disabled={items.length === 1}
                        onClick={() =>
                          batchSize(item.batch_ref) > 1 && item.batch_ref
                            ? removeBatch(item.batch_ref)
                            : removeItem(index)
                        }
                      />
                    </td>
                  </tr>
                  {qtyOf(item) > 1 && (
                    /* Spell out what this line will become. The count is
                     what was typed; the CBM and weight are what it costs.
                     A wrong quantity is far easier to notice as "60.00
                     CBM" than as a digit in a small box. */
                    <tr className={styles.qtyPreviewRow}>
                      <td />
                      <td colSpan={9}>
                        <span className={styles.qtyPreview}>
                          <Icon name="plus" size={12} />
                          {[
                            `Creates ${qtyOf(item)} ${item.package_unit ?? 'carton'}${
                              qtyOf(item) === 1 ? '' : 's'
                            }`,
                            hasData ? `${formatCbm(effectiveCbm * qtyOf(item))} CBM` : null,
                            item.weight_actual_kg != null
                              ? `${formatKg(item.weight_actual_kg * qtyOf(item))} kg`
                              : null,
                            'separate tags, one per package',
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3} className={styles.totalsLabel}>
                Totals — {formatPackageMix(buildPackageMix(items))}
              </td>
              <td className={styles.right}>
                <Mono>{formatKg(totals.weightDispatch)} kg</Mono>
              </td>
              <td className={styles.right}>
                <Mono>{formatKg(totals.weight)} kg</Mono>
              </td>
              <td />
              <td className={styles.right}>
                <Mono color="var(--color-success)">{formatCbm(totals.cbm)}</Mono>
              </td>
              {/* Qty has no meaningful total of its own — the package
                  count is already stated as "N items" on the left — but
                  the cell must exist, or every figure after CBM shifts a
                  column left and the declared total lands under Qty. */}
              <td />
              <td className={styles.right}>
                <Mono>${totals.declaredUsd.toFixed(0)}</Mono>
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <div className={styles.addAnotherRow}>
        <Button
          variant="ghost"
          icon="plus"
          onClick={() => setItems((prev) => [...prev, emptyItem()])}
        >
          Add another item
        </Button>
      </div>
    </Card>
  )
}
