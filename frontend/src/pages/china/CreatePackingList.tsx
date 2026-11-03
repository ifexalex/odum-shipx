import { useEffect, useState, type JSX, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { applyMinCbm, baleSizeAbbr, computeCbm } from '../../api/packingListRules'
import {
  PACKAGE_UNITS,
  packingListApi,
  type PackageUnit,
  type PackingListItemInput,
} from '../../api/packingList'
import { containersApi, type Container } from '../../api/tracking'
import { configApi, customersApi, type CbmRateCurrency, type Customer } from '../../api/tenantManagement'
import { warehousesApi, type Warehouse } from '../../api/warehouses'
import { useIdempotencyKey } from '../../api/useIdempotencyKey'
import { Avatar, Badge, Banner, Button, Card, Combobox, Field, Icon, Kvp, Mono } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './CreatePackingList.module.css'

function emptyItem(): PackingListItemInput {
  return { description: '', package_unit: 'carton' }
}

// Numeric cell helpers: these fields are quantities (weights, dimensions,
// value) — never negative and never alphabetic. type="number" alone still
// lets the user type 'e'/'+'/'-'; block those keys and reject any parsed
// value that isn't a non-negative finite number.
function blockInvalidNumberKeys(e: ReactKeyboardEvent<HTMLInputElement>): void {
  if (['e', 'E', '+', '-'].includes(e.key)) e.preventDefault()
}

function sanitizeNumber(raw: string): number | undefined {
  if (raw.trim() === '') return undefined
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0) return undefined
  return n
}

interface WizardStepsProps {
  current: 1 | 2 | 3
}

function WizardSteps({ current }: WizardStepsProps): JSX.Element {
  const steps: { n: 1 | 2 | 3; label: string; sub: string }[] = [
    { n: 1, label: 'Details', sub: 'Customer + container' },
    { n: 2, label: 'Items', sub: 'Cartons + measurements' },
    { n: 3, label: 'Review', sub: 'Verify + submit' },
  ]
  return (
    <Card padding={0}>
      <div className={styles.steps}>
        {steps.map((step, index) => {
          const done = step.n < current
          const isCurrent = step.n === current
          return (
            <div key={step.n} className={styles.stepWrap}>
              <div className={[styles.step, isCurrent ? styles.stepActive : ''].join(' ')}>
                <div className={[styles.stepCircle, done ? styles.stepDone : '', isCurrent ? styles.stepCurrent : ''].join(' ')}>
                  {done ? <Icon name="check" size={16} stroke={3} color="#fff" /> : step.n}
                </div>
                <div className={styles.stepText}>
                  <div className={styles.stepEyebrow}>Step {step.n}</div>
                  <div className={[styles.stepLabel, done || isCurrent ? '' : styles.stepLabelIdle].join(' ')}>
                    {step.label}
                  </div>
                  <div className={styles.stepSub}>{step.sub}</div>
                </div>
              </div>
              {index < steps.length - 1 && <Icon name="chevright" size={14} color="var(--color-ink-4)" />}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export function CreatePackingList(): JSX.Element {
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id: string }>()
  const isEdit = Boolean(editId)
  const { key, regenerate } = useIdempotencyKey()
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [customers, setCustomers] = useState<Customer[]>([])
  const [containers, setContainers] = useState<Container[]>([])
  const [customerId, setCustomerId] = useState('')
  const [containerId, setContainerId] = useState('')
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [arrivalWarehouseId, setArrivalWarehouseId] = useState('')
  const [loadingDate, setLoadingDate] = useState('')
  const [deliveryDate, setDeliveryDate] = useState('')
  // Minimum billable CBM per item (tenant setting) — tiny parcels are floored
  // to this value, mirroring the backend, so the wizard shows the real value.
  const [minCbm, setMinCbm] = useState(0.1)
  const [items, setItems] = useState<PackingListItemInput[]>([emptyItem()])
  // When editing a draft, the customer/container are fixed (the update API
  // keeps them) — show them read-only once loaded.
  const [editReady, setEditReady] = useState(!isEdit)
  // Tenant rates for the live pricing estimate (Step 2). Null until fetched or
  // if the current role can't read them — the pricing card degrades to "—".
  // This wizard doesn't collect a per-item package type, so it can only ever
  // estimate with one representative rate — carton_rate, the same rate any
  // unrecognized package type bills at (shared/cbm_rate.py).
  const [cbmRate, setCbmRate] = useState<number | null>(null)
  const [cbmCurrency, setCbmCurrency] = useState<CbmRateCurrency>('usd')
  const [fxRate, setFxRate] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Tracked separately from `error`: failing to load warehouses must not read as
  // "this tenant has none", but it also must not block the rest of the form.
  const [warehouseError, setWarehouseError] = useState<string | null>(null)

  useEffect(() => {
    async function loadPickerData(): Promise<void> {
      try {
        // Only 'loading' containers can receive new packing lists — sealed/in-transit
        // containers are closed to additions (enforced by the backend too).
        // The warehouse list is still tolerated failing — it is one optional
        // field on a long form, and a tenant that has configured none is a
        // legitimate state. But the failure must NOT be swallowed into an
        // empty array: doing so rendered "No warehouses configured" for what
        // was actually a 403 (china_office_staff were missing from the read
        // roles), so a permission bug looked like a configuration choice for
        // weeks. Record that it failed and say so in the UI instead.
        const [customerResult, containerResult, warehouseResult] = await Promise.all([
          customersApi.list(),
          containersApi.list({ status: 'loading' }),
          warehousesApi.list().then(
            (rows) => ({ ok: true as const, rows }),
            (err: unknown) => ({ ok: false as const, err }),
          ),
        ])
        setCustomers(customerResult.data)
        setContainers(containerResult.data)
        if (!warehouseResult.ok) {
          const { err } = warehouseResult
          setWarehouseError(
            err instanceof ApiError ? err.message : 'Could not load warehouses.',
          )
          return
        }
        const warehouseRows = warehouseResult.rows
        setWarehouses(warehouseRows)
        // Pre-select the tenant's default warehouse on a fresh create. On edit,
        // loadDraftForEdit sets the saved value instead (don't clobber it).
        if (!isEdit) {
          const def = warehouseRows.find((w) => w.is_default)
          if (def) setArrivalWarehouseId((prev) => prev || def.id)
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load customers or containers.')
      }
    }
    async function loadRates(): Promise<void> {
      // Pricing is a non-blocking nicety — swallow failures so a rate the role
      // can't read (or a transient error) never breaks the create flow.
      try {
        const [cbm, dollar] = await Promise.all([configApi.getCbmRate(), configApi.getDollarRate()])
        setCbmRate(cbm.carton_rate)
        setCbmCurrency(cbm.currency)
        setFxRate(dollar.rate)
        if (cbm.min_cbm_per_item > 0) setMinCbm(cbm.min_cbm_per_item)
      } catch {
        /* leave rates null → pricing tiles show "—" */
      }
    }
    async function loadDraftForEdit(): Promise<void> {
      if (!editId) return
      try {
        const pl = await packingListApi.get(editId)
        if (pl.status !== 'draft' && pl.status !== 'rejected') {
          setError('This packing list can no longer be edited (it has been submitted or approved).')
          return
        }
        setCustomerId(pl.customer_id)
        setContainerId(pl.container_id)
        setArrivalWarehouseId(pl.arrival_warehouse_id ?? '')
        setLoadingDate(pl.loading_date ?? '')
        setDeliveryDate(pl.delivery_date ?? '')
        setItems(
          pl.items.length > 0
            ? pl.items.map((it) => ({
                description: it.description,
                weight_dispatch_kg: it.weight_dispatch_kg != null ? Number(it.weight_dispatch_kg) : undefined,
                weight_actual_kg: it.weight_actual_kg != null ? Number(it.weight_actual_kg) : undefined,
                length_cm: it.length_cm != null ? Number(it.length_cm) : undefined,
                width_cm: it.width_cm != null ? Number(it.width_cm) : undefined,
                height_cm: it.height_cm != null ? Number(it.height_cm) : undefined,
                declared_value_usd: it.declared_value_usd != null ? Number(it.declared_value_usd) : undefined,
                package_unit: (it.package_unit as PackageUnit) ?? 'carton',
              }))
            : [emptyItem()],
        )
        // Ensure the fixed customer/container show even though the pickers only
        // list open containers — inject the current one if missing.
        setContainers((prev) =>
          prev.some((c) => c.id === pl.container_id)
            ? prev
            : [{ id: pl.container_id, container_number: pl.container_number ?? '—' } as Container, ...prev],
        )
        setCustomers((prev) =>
          prev.some((c) => c.id === pl.customer_id)
            ? prev
            : [{ id: pl.customer_id, name: pl.customer_name ?? '—' } as Customer, ...prev],
        )
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load the packing list.')
      } finally {
        setEditReady(true)
      }
    }
    void loadPickerData()
    void loadRates()
    void loadDraftForEdit()
  }, [editId])

  const selectedCustomer = customers.find((c) => c.id === customerId)
  const selectedContainer = containers.find((c) => c.id === containerId)

  // Raw CBM from dimensions (0 when incomplete); the billable value floors it.
  function rawCbm(item: PackingListItemInput): number {
    return item.length_cm != null && item.width_cm != null && item.height_cm != null
      ? computeCbm(item.length_cm, item.width_cm, item.height_cm)
      : 0
  }

  const totals = items.reduce(
    (acc, item) => ({
      cartons: acc.cartons + 1,
      weightDispatch: acc.weightDispatch + (item.weight_dispatch_kg ?? 0),
      weight: acc.weight + (item.weight_actual_kg ?? 0),
      cbm: acc.cbm + applyMinCbm(rawCbm(item), minCbm),
      declaredUsd: acc.declaredUsd + (item.declared_value_usd ?? 0),
    }),
    { cartons: 0, weightDispatch: 0, weight: 0, cbm: 0, declaredUsd: 0 },
  )

  // Live pricing: CBM × rate, in whichever currency the tenant configured —
  // then derive the other currency's tile via the FX rate. Null rates
  // degrade to "—".
  const cbmCharge = cbmRate != null ? totals.cbm * cbmRate : null
  const shippingUsd =
    cbmCharge == null ? null : cbmCurrency === 'usd' ? cbmCharge : fxRate != null ? cbmCharge / fxRate : null
  const shippingNgn =
    cbmCharge == null ? null : cbmCurrency === 'ngn' ? cbmCharge : fxRate != null ? cbmCharge * fxRate : null

  function updateItem(index: number, patch: Partial<PackingListItemInput>): void {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  }

  function removeItem(index: number): void {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  async function handleSave(submitForApproval: boolean): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      let targetId: string
      if (isEdit) {
        const updated = await packingListApi.update(editId!, {
          loading_date: loadingDate || undefined,
          delivery_date: deliveryDate || undefined,
          arrival_warehouse_id: arrivalWarehouseId || undefined,
          items,
        })
        targetId = updated.id
      } else {
        const created = await packingListApi.create(
          {
            container_id: containerId,
            customer_id: customerId,
            loading_date: loadingDate || undefined,
            delivery_date: deliveryDate || undefined,
            arrival_warehouse_id: arrivalWarehouseId || undefined,
            items,
          },
          key,
        )
        regenerate()
        targetId = created.id
      }
      if (submitForApproval) {
        await packingListApi.submit(targetId)
      }
      navigate(`/packing-lists/${targetId}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the packing list.')
    } finally {
      setSubmitting(false)
    }
  }

  // The user's LOCAL date, not UTC. The China office is UTC+8, so for several
  // hours each evening their calendar date is already tomorrow in UTC —
  // comparing against a UTC "today" would flag the date on their own wall
  // calendar as a future date. (The backend allows one day past UTC for the
  // same reason.) Built field by field rather than via toISOString(), which
  // would silently convert to UTC.
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`

  // ISO date strings (YYYY-MM-DD) compare correctly as plain strings, so no
  // Date parsing — and therefore no timezone shifting — is needed here.
  const deliveryDateError =
    deliveryDate && deliveryDate > today
      ? 'Cannot be a future date — this is when the goods were received.'
      : undefined
  const loadingDateError =
    loadingDate && deliveryDate && loadingDate < deliveryDate
      ? 'Cannot be before the delivery date — goods must be received before they are loaded.'
      : undefined

  const canProceedFrom1 =
    Boolean(customerId && containerId) && !deliveryDateError && !loadingDateError
  const canProceedFrom2 = items.length > 0 && items.every((item) => item.description.trim() !== '')

  return (
    <div className={styles.wrap}>
      <PageHeader
        eyebrow="China-side · packing"
        title={isEdit ? 'Edit draft packing list' : 'Create packing list'}
        subtitle="Capture carton-level details for a customer's cargo. Submit for approval when complete."
      />

      {!editReady ? (
        <Card padding={32}>
          <span className={styles.fieldHelper}>Loading draft…</span>
        </Card>
      ) : (
      <>
      <WizardSteps current={step} />
      <div className={styles.spacer} />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't save">{error}</Banner>
        </div>
      )}

      {step === 1 && (
        <Card padding={32}>
          <SectionHead title="Customer & container" sub="Who is this cargo for, and which container is it loading into?" />
          <div className={styles.spacerLg} />
          <div className={styles.grid2}>
            <div className={styles.selectField}>
              <label className={styles.selectLabel} htmlFor="customerSelect">
                Customer<span className={styles.required}>*</span>
              </label>
              <Combobox
                id="customerSelect"
                ariaLabel="Customer"
                options={customers.map((customer) => ({
                  value: customer.id,
                  label: customer.name ?? '—',
                  meta: [customer.phone, customer.email].filter(Boolean).join(' · ') || undefined,
                }))}
                value={customerId}
                onChange={setCustomerId}
                disabled={customers.length === 0 || isEdit}
                placeholder={
                  customers.length === 0 ? 'No customers available' : 'Search or select a customer…'
                }
                searchPlaceholder="Search by name or phone…"
                emptyText="No customer matches"
              />
              {isEdit && <span className={styles.fieldHelper}>Fixed for this draft</span>}
            </div>
            <div className={styles.selectField}>
              <label className={styles.selectLabel} htmlFor="containerSelect">
                Container<span className={styles.required}>*</span>
              </label>
              <Combobox
                id="containerSelect"
                ariaLabel="Container"
                options={containers.map((container) => ({
                  value: container.id,
                  label: container.container_number,
                  meta: [container.container_type, container.vessel_name].filter(Boolean).join(' · ') || undefined,
                }))}
                value={containerId}
                onChange={setContainerId}
                disabled={containers.length === 0 || isEdit}
                placeholder={
                  containers.length === 0 ? 'No open containers available' : 'Search or select a container…'
                }
                searchPlaceholder="Search by container number…"
                emptyText="No container matches"
              />
              <span className={styles.fieldHelper}>
                {isEdit ? 'Fixed for this draft' : 'Only containers in Loading status are eligible'}
              </span>
            </div>
          </div>

          <div className={styles.spacerLg} />
          <SectionHead title="Arrival warehouse" sub="Which destination warehouse this customer's goods are bound for." />
          <div className={styles.spacerSm} />
          <div className={styles.grid2}>
            <div className={styles.selectField}>
              <label className={styles.selectLabel} htmlFor="warehouseSelect">
                Arrival warehouse
              </label>
              <Combobox
                id="warehouseSelect"
                ariaLabel="Arrival warehouse"
                options={warehouses.map((w) => ({
                  value: w.id,
                  label: w.name,
                  meta: [w.city, w.state].filter(Boolean).join(', ') || undefined,
                }))}
                value={arrivalWarehouseId}
                onChange={setArrivalWarehouseId}
                disabled={warehouses.length === 0}
                placeholder={
                  warehouseError
                    ? 'Warehouses unavailable'
                    : warehouses.length === 0
                      ? 'No warehouses configured'
                      : 'Search or select a warehouse…'
                }
                searchPlaceholder="Search by name or city…"
                emptyText="No warehouse matches"
              />
              <span className={styles.fieldHelper}>
                {warehouseError
                  ? `${warehouseError} The list could not be loaded, so this is left unset — ` +
                    'your default warehouse is still applied automatically when you save.'
                  : 'Defaults to your default warehouse — change it per shipment if needed.'}
              </span>
            </div>
          </div>

          <div className={styles.spacerLg} />
          <SectionHead
            title="Goods dates"
            sub="Delivery comes first — cargo has to reach the warehouse before it can be loaded."
          />
          <div className={styles.spacerSm} />
          <div className={styles.grid2}>
            <Field
              label="Delivery date"
              name="deliveryDate"
              type="date"
              optional
              value={deliveryDate}
              onChange={(e) => setDeliveryDate(e.target.value)}
              // Caps the native date picker at today, so the commonest mistake
              // is unreachable rather than merely rejected after submitting.
              max={today}
              error={deliveryDateError}
              helper={
                deliveryDateError ? undefined : 'Received in the China warehouse. Not a future date.'
              }
            />
            <Field
              label="Loading date"
              name="loadingDate"
              type="date"
              optional
              value={loadingDate}
              onChange={(e) => setLoadingDate(e.target.value)}
              // No max: a packing list is written against a container still
              // loading, so a planned load date is legitimate.
              min={deliveryDate || undefined}
              error={loadingDateError}
              helper={
                loadingDateError ? undefined : 'Loaded into the container. Same day as delivery or later.'
              }
            />
          </div>

          <div className={styles.spacerLg} />
          <Banner variant="info" title="What happens next">
            Carton tags and a tracking code are assigned automatically once you save — they aren't predicted here.
          </Banner>

          <div className={styles.actionsRow}>
            <Button variant="ghost" onClick={() => navigate('/packing-lists')}>
              Cancel
            </Button>
            <Button variant="primary" trailingIcon="arrowright" disabled={!canProceedFrom1} onClick={() => setStep(2)}>
              Next: Add items
            </Button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <>
          <Card padding={16}>
            <div className={styles.contextBar}>
              {selectedCustomer && (
                <div className={styles.contextParty}>
                  <Avatar size={32} name={selectedCustomer.name ?? '?'} roleColor="nigeria" />
                  <div>
                    <div className={styles.contextName}>{selectedCustomer.name}</div>
                    {selectedCustomer.phone && <div className={styles.contextSub}>{selectedCustomer.phone}</div>}
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
                      {selectedContainer.estimated_arrival_date && ` · ETA ${selectedContainer.estimated_arrival_date}`}
                    </div>
                  )}
                </div>
              </div>
              <span className={styles.contextSpacer} />
              <Badge variant="neutral">Draft — assigned on save</Badge>
            </div>
          </Card>
          <div className={styles.spacer} />
          <Card padding={0}>
            <div className={styles.itemsHead}>
              <SectionHead
                title="Line items"
                sub={`Pick a package type per row. CBM is computed from L × W × H and floored at ${minCbm} CBM.`}
              />
              <div className={styles.actionsGroup}>
                <Button variant="secondary" size="sm" icon="upload" onClick={() => navigate('/packing-lists/import')}>
                  Import CSV
                </Button>
                <Button variant="primary" size="sm" icon="plus" onClick={() => setItems((prev) => [...prev, emptyItem()])}>
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
                      <tr key={index}>
                        <td>
                          <span className={styles.assignedOnSave}>On save</span>
                        </td>
                        <td>
                          <input
                            className={styles.cellInput}
                            value={item.description}
                            placeholder="e.g. Electronics (mixed)"
                            onChange={(event) => updateItem(index, { description: event.target.value })}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.typeSelect}
                            aria-label={`Package type for item ${index + 1}`}
                            value={item.package_unit ?? 'carton'}
                            onChange={(event) =>
                              updateItem(index, { package_unit: event.target.value as PackageUnit })
                            }
                          >
                            {PACKAGE_UNITS.map((u) => (
                              <option key={u.value} value={u.value}>
                                {u.label}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className={styles.right}>
                          <input
                            className={styles.cellInputNumber}
                            type="number"
                            min={0}
                            inputMode="decimal"
                            value={item.weight_dispatch_kg ?? ''}
                            onKeyDown={blockInvalidNumberKeys}
                            onChange={(event) => updateItem(index, { weight_dispatch_kg: sanitizeNumber(event.target.value) })}
                          />
                        </td>
                        <td className={styles.right}>
                          <input
                            className={styles.cellInputNumber}
                            type="number"
                            min={0}
                            inputMode="decimal"
                            value={item.weight_actual_kg ?? ''}
                            onKeyDown={blockInvalidNumberKeys}
                            onChange={(event) => updateItem(index, { weight_actual_kg: sanitizeNumber(event.target.value) })}
                          />
                        </td>
                        <td>
                          <div className={styles.dimRow}>
                            <input
                              className={styles.dimInput}
                              type="number"
                              min={0}
                              inputMode="decimal"
                              value={item.length_cm ?? ''}
                              onKeyDown={blockInvalidNumberKeys}
                              onChange={(event) => updateItem(index, { length_cm: sanitizeNumber(event.target.value) })}
                            />
                            <span>×</span>
                            <input
                              className={styles.dimInput}
                              type="number"
                              min={0}
                              inputMode="decimal"
                              value={item.width_cm ?? ''}
                              onKeyDown={blockInvalidNumberKeys}
                              onChange={(event) => updateItem(index, { width_cm: sanitizeNumber(event.target.value) })}
                            />
                            <span>×</span>
                            <input
                              className={styles.dimInput}
                              type="number"
                              min={0}
                              inputMode="decimal"
                              value={item.height_cm ?? ''}
                              onKeyDown={blockInvalidNumberKeys}
                              onChange={(event) => updateItem(index, { height_cm: sanitizeNumber(event.target.value) })}
                            />
                          </div>
                        </td>
                        <td className={styles.right}>
                          <div className={styles.cbmCell}>
                            <span className={styles.cbmChip}>{hasData ? effectiveCbm.toFixed(3) : '—'}</span>
                            {hasData && floored && (
                              <span className={styles.minTag} title={`Floored to the ${minCbm} CBM minimum`}>
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
                        <td className={styles.right}>
                          <input
                            className={styles.cellInputNumber}
                            type="number"
                            min={0}
                            inputMode="decimal"
                            value={item.declared_value_usd ?? ''}
                            onKeyDown={blockInvalidNumberKeys}
                            onChange={(event) =>
                              updateItem(index, { declared_value_usd: sanitizeNumber(event.target.value) })
                            }
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className={styles.removeRow}
                            aria-label={`Remove item ${index + 1}`}
                            disabled={items.length === 1}
                            onClick={() => removeItem(index)}
                          >
                            <Icon name="x" size={14} />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} className={styles.totalsLabel}>
                      Totals — {totals.cartons} item(s)
                    </td>
                    <td className={styles.right}>
                      <Mono>{totals.weightDispatch.toFixed(1)} kg</Mono>
                    </td>
                    <td className={styles.right}>
                      <Mono>{totals.weight.toFixed(1)} kg</Mono>
                    </td>
                    <td />
                    <td className={styles.right}>
                      <Mono color="var(--color-success)">{totals.cbm.toFixed(3)}</Mono>
                    </td>
                    <td className={styles.right}>
                      <Mono>${totals.declaredUsd.toFixed(0)}</Mono>
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
            <div className={styles.addAnotherRow}>
              <Button variant="ghost" icon="plus" onClick={() => setItems((prev) => [...prev, emptyItem()])}>
                Add another item
              </Button>
            </div>
          </Card>

          <div className={styles.spacer} />
          <Card>
            <SectionHead
              title="Live pricing estimate"
              sub="Computed from the current CBM + FX rates · final billing happens in Nigeria"
            />
            <div className={styles.spacerSm} />
            <div className={styles.priceTiles}>
              <div className={styles.priceTile}>
                <div className={styles.priceLabel}>Total CBM</div>
                <div className={styles.priceValue}>{totals.cbm.toFixed(3)}</div>
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
                <div className={styles.priceValue}>{shippingUsd != null ? `$${shippingUsd.toFixed(2)}` : '—'}</div>
                <div className={styles.priceSub}>
                  {cbmCurrency === 'usd'
                    ? cbmRate != null ? `${totals.cbm.toFixed(3)} × $${cbmRate.toFixed(2)}` : 'rate unavailable'
                    : fxRate != null ? 'derived from ₦ via FX' : 'FX unavailable'}
                </div>
              </div>
              <div className={[styles.priceTile, styles.priceTileHighlight].join(' ')}>
                <div className={styles.priceLabel}>Shipping (NGN)</div>
                <div className={styles.priceValue}>
                  {shippingNgn != null ? `₦${Math.round(shippingNgn).toLocaleString()}` : '—'}
                </div>
                <div className={styles.priceSub}>
                  {cbmCurrency === 'ngn'
                    ? cbmRate != null ? `${totals.cbm.toFixed(3)} × ₦${cbmRate.toFixed(2)}` : 'rate unavailable'
                    : fxRate != null ? `× ₦${fxRate.toLocaleString()} FX` : 'FX unavailable'}
                </div>
              </div>
            </div>
          </Card>

          <div className={styles.actionsRow}>
            <Button variant="ghost" icon="arrowleft" onClick={() => setStep(1)}>
              Back: Details
            </Button>
            <div className={styles.actionsGroup}>
              <Button variant="secondary" loading={submitting} onClick={() => void handleSave(false)}>
                Save draft
              </Button>
              <Button variant="primary" trailingIcon="arrowright" disabled={!canProceedFrom2} onClick={() => setStep(3)}>
                Next: Review
              </Button>
            </div>
          </div>
        </>
      )}

      {step === 3 && (
        <div className={styles.reviewGrid}>
          <div>
            <Card>
              <SectionHead title="Ready to submit" sub="Review the summary, then submit for approval." />
              <div className={styles.spacerSm} />
              <Banner variant="success" title="All items look valid">
                {totals.cartons} carton(s) captured · all dimensions present · CBM totals computed.
              </Banner>
            </Card>
            <div className={styles.spacerSm} />
            {/* Document preview — how this packing list will look when printed */}
            <Card padding={0}>
              <div className={styles.previewHeader}>
                <SectionHead title="Document preview" sub="How this packing list will appear when printed" />
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
                      {selectedCustomer?.phone && <div className={styles.previewMetaMono}>{selectedCustomer.phone}</div>}
                    </div>
                    <div>
                      <div className={styles.previewMetaLabel}>Container</div>
                      <div className={styles.previewMetaMono}>{selectedContainer?.container_number ?? '—'}</div>
                      {selectedContainer?.vessel_name && (
                        <div className={styles.previewMetaValue}>{selectedContainer.vessel_name}{selectedContainer.voyage_number ? ` · Voy ${selectedContainer.voyage_number}` : ''}</div>
                      )}
                    </div>
                  </div>
                  {/* Items table */}
                  <div className={styles.previewTableHead}>
                    <span className={styles.previewCol}>Tag</span>
                    <span className={[styles.previewCol, styles.previewColDesc].join(' ')}>Description</span>
                    <span className={[styles.previewCol, styles.previewColRight].join(' ')}>Wt (kg)</span>
                    <span className={[styles.previewCol, styles.previewColRight].join(' ')}>L×W×H</span>
                    <span className={[styles.previewCol, styles.previewColRight].join(' ')}>CBM</span>
                    <span className={[styles.previewCol, styles.previewColRight].join(' ')}>USD</span>
                  </div>
                  {items.map((item, i) => {
                    const cbm = item.length_cm != null && item.width_cm != null && item.height_cm != null
                      ? computeCbm(item.length_cm, item.width_cm, item.height_cm)
                      : null
                    return (
                      <div key={i} className={styles.previewRow}>
                        <span className={[styles.previewCol, styles.previewMono].join(' ')}>—</span>
                        <span className={[styles.previewCol, styles.previewColDesc].join(' ')}>{item.description || '—'}</span>
                        <span className={[styles.previewCol, styles.previewColRight, styles.previewMono].join(' ')}>{item.weight_actual_kg ?? '—'}</span>
                        <span className={[styles.previewCol, styles.previewColRight, styles.previewMono].join(' ')}>
                          {item.length_cm != null ? `${item.length_cm}×${item.width_cm}×${item.height_cm}` : '—'}
                        </span>
                        <span className={[styles.previewCol, styles.previewColRight, styles.previewMono, styles.previewCbm].join(' ')}>
                          {cbm != null ? cbm.toFixed(3) : '—'}
                        </span>
                        <span className={[styles.previewCol, styles.previewColRight, styles.previewMono].join(' ')}>
                          {item.declared_value_usd != null ? `$${item.declared_value_usd}` : '—'}
                        </span>
                      </div>
                    )
                  })}
                  {/* Totals */}
                  <div className={styles.previewTotals}>
                    <span>{totals.cartons} carton(s)</span>
                    <span>·</span>
                    <span>{totals.weight.toFixed(1)} kg</span>
                    <span>·</span>
                    <span className={styles.previewCbm}>{totals.cbm.toFixed(3)} CBM</span>
                  </div>
                </div>
              </div>
            </Card>
          </div>
          <div className={styles.reviewSidebar}>
            <Card>
              <SectionHead title="Summary" />
              <Kvp label="Customer" value={selectedCustomer?.name ?? '—'} />
              <Kvp label="Container" value={<Mono>{selectedContainer?.container_number ?? '—'}</Mono>} />
              <Kvp label="Cartons" value={<Mono>{totals.cartons}</Mono>} />
              <Kvp label="Total weight" value={<Mono>{totals.weight.toFixed(1)} kg</Mono>} />
              <Kvp label="Total CBM" value={<Mono color="var(--color-success)">{totals.cbm.toFixed(3)}</Mono>} />
              <Kvp label="Declared value" value={<Mono>${totals.declaredUsd.toFixed(0)} USD</Mono>} divider={false} />
            </Card>
          </div>

          <div className={styles.actionsRowFull}>
            <Button variant="ghost" icon="arrowleft" onClick={() => setStep(2)}>
              Back: Items
            </Button>
            <div className={styles.actionsGroup}>
              <Button variant="secondary" loading={submitting} onClick={() => void handleSave(false)}>
                Save as draft
              </Button>
              <Button variant="accent" icon="check" loading={submitting} onClick={() => void handleSave(true)}>
                Submit for approval
              </Button>
            </div>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  )
}
