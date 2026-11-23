import { type JSX } from 'react'
import { Banner, Button, Card, Combobox, Field } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../CreatePackingList.module.css'
import type { PackingListForm } from './useCreatePackingListForm'

/** Step 1: the customer, the container, the arrival warehouse and the dates. */
export function Step1({ form }: { form: PackingListForm }): JSX.Element {
  const {
    navigate,
    isEdit,
    setStep,
    customerId,
    setCustomerId,
    containerId,
    setContainerId,
    arrivalWarehouseId,
    setArrivalWarehouseId,
    loadingDate,
    setLoadingDate,
    deliveryDate,
    setDeliveryDate,
    warehouses,
    warehouseError,
    customers,
    containers,
    today,
    deliveryDateError,
    loadingDateError,
    canProceedFrom1,
  } = form
  return (
    <Card padding={32}>
      <SectionHead
        title="Customer & container"
        sub="Who is this cargo for, and which container is it loading into?"
      />
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
              meta:
                [container.container_type, container.vessel_name].filter(Boolean).join(' · ') ||
                undefined,
            }))}
            value={containerId}
            onChange={setContainerId}
            disabled={containers.length === 0 || isEdit}
            placeholder={
              containers.length === 0
                ? 'No open containers available'
                : 'Search or select a container…'
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
      <SectionHead
        title="Arrival warehouse"
        sub="Which destination warehouse this customer's goods are bound for."
      />
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
            loadingDateError
              ? undefined
              : 'Loaded into the container. Same day as delivery or later.'
          }
        />
      </div>

      <div className={styles.spacerLg} />
      <Banner variant="info" title="What happens next">
        Carton tags and a tracking code are assigned automatically once you save — they aren't
        predicted here.
      </Banner>

      <div className={styles.actionsRow}>
        <Button variant="ghost" onClick={() => navigate('/packing-lists')}>
          Cancel
        </Button>
        <Button
          variant="primary"
          trailingIcon="arrowright"
          disabled={!canProceedFrom1}
          onClick={() => setStep(2)}
        >
          Next: Add items
        </Button>
      </div>
    </Card>
  )
}
