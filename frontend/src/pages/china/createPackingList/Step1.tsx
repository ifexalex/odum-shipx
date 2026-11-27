import { Link } from 'react-router-dom'
import { type JSX } from 'react'
import { Banner, Button, Card, Combobox, DateField, Field } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import { useCanOpen } from '../../../shell/useCanOpen'
import styles from '../CreatePackingList.module.css'
import type { PackingListForm } from './useCreatePackingListForm'

/** Where the wizard sends someone to create the container it needs, and returns them from. */
export const CREATE_CONTAINER_FOR_PACKING_LIST = `/containers/new?return=${encodeURIComponent('/packing-lists/new')}`
const WAREHOUSES_PATH = '/admin/config/warehouses'

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
    deliveryDateMode,
    setDeliveryDateMode,
    loadingDate,
    setLoadingDate,
    deliveryDate,
    setDeliveryDate,
    remarks,
    setRemarks,
    warehouses,
    warehouseError,
    customers,
    containers,
    today,
    deliveryDateError,
    loadingDateError,
    canProceedFrom1,
    containerLookup,
    warehouseQuery,
  } = form
  const canCreateContainer = useCanOpen('/containers/new')
  const canAddWarehouse = useCanOpen(WAREHOUSES_PATH)
  // A missing prerequisite is named at the top of the step with the way to fix it (FD-25), not left as a disabled
  // box. Only once the list has loaded and is truly empty: a failed load says so in the error banner instead.
  const noContainer = !isEdit && containerLookup.isSuccess && containers.length === 0
  const noWarehouse = warehouseQuery.isSuccess && warehouses.length === 0
  return (
    <Card padding="large">
      <SectionHead
        title="Customer & container"
        sub="Who is this cargo for, and which container is it loading into?"
      />
      <div className={styles.spacerLg} />
      {(noContainer || noWarehouse) && (
        <div className={styles.prerequisites}>
          {noContainer && (
            <Banner variant="warning" title="No container is loading">
              A packing list goes into a container in Loading status, and there is none yet.{' '}
              {canCreateContainer ? (
                <>
                  <Link to={CREATE_CONTAINER_FOR_PACKING_LIST}>Create a container</Link> and you will come back here
                  with this form as you left it.
                </>
              ) : (
                'Ask the China office to create one.'
              )}
            </Banner>
          )}
          {noWarehouse && (
            <Banner variant="info" title="No arrival warehouse is set up">
              {canAddWarehouse ? (
                <>
                  <Link to={WAREHOUSES_PATH}>Add a warehouse</Link> so cargo records where it is bound.
                </>
              ) : (
                'Ask your admin to add a warehouse under Settings › Warehouses.'
              )}{' '}
              You can still save this packing list without one.
            </Banner>
          )}
        </div>
      )}
      <div className={styles.grid2}>
        <div className={styles.selectField}>
          <label className={styles.selectLabel} htmlFor="customerSelect">
            Customer
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
            placeholder={customers.length === 0 ? 'No customers yet' : 'Search or select a customer…'}
            searchPlaceholder="Search by name or phone…"
            emptyText="No customer matches"
          />
          {isEdit ? (
            <span className={styles.fieldHelper}>Fixed for this draft</span>
          ) : (
            customers.length === 0 && (
              <span className={styles.fieldHelper}>Ask the Nigeria office or your admin to add the customer first.</span>
            )
          )}
        </div>
        <div className={styles.selectField}>
          <label className={styles.selectLabel} htmlFor="containerSelect">
            Container
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
            placeholder={containers.length === 0 ? 'No container is loading' : 'Search or select a container…'}
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
                  ? 'No warehouses yet'
                  : 'Search or select a warehouse…'
            }
            searchPlaceholder="Search by name or city…"
            emptyText="No warehouse matches"
          />
          <span className={styles.fieldHelper}>
            {warehouseError
              ? `${warehouseError} The list could not be loaded, so this is left unset — ` +
                'your default warehouse is still applied automatically when you save.'
              : warehouses.length === 0
                ? 'None set up yet.'
                : 'Defaults to your default warehouse — change it per shipment if needed.'}
          </span>
        </div>
      </div>

      <div className={styles.spacerLg} />
      <SectionHead
        title="Goods dates"
        sub="Choose whether all items were delivered on the same day or across multiple days. All items on this packing list still share one tracking code."
      />
      <div className={styles.spacerSm} />
      <div className={styles.modeToggle} role="radiogroup" aria-label="Delivery date mode">
        <label
          className={[
            styles.modeOption,
            deliveryDateMode === 'same_day' ? styles.modeOptionActive : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <input
            type="radio"
            name="deliveryDateMode"
            value="same_day"
            checked={deliveryDateMode === 'same_day'}
            onChange={() => setDeliveryDateMode('same_day')}
            className={styles.srOnly}
          />
          <span className={styles.modeOptionTitle}>Same-day delivery items</span>
          <span className={styles.modeOptionSub}>One delivery date applies to all items</span>
        </label>
        <label
          className={[
            styles.modeOption,
            deliveryDateMode === 'multiple_days' ? styles.modeOptionActive : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <input
            type="radio"
            name="deliveryDateMode"
            value="multiple_days"
            checked={deliveryDateMode === 'multiple_days'}
            onChange={() => setDeliveryDateMode('multiple_days')}
            className={styles.srOnly}
          />
          <span className={styles.modeOptionTitle}>Multiple-day delivery items</span>
          <span className={styles.modeOptionSub}>
            Enter a delivery date per item in Step 2 (shared loading date)
          </span>
        </label>
      </div>
      <div className={styles.spacerSm} />
      <div className={styles.grid2}>
        {deliveryDateMode === 'same_day' && (
          <DateField
            label="Delivery date"
            name="deliveryDate"
            optional
            value={deliveryDate}
            onChange={(e) => setDeliveryDate(e.target.value)}
            max={today}
            error={deliveryDateError}
            helper={
              deliveryDateError ? undefined : 'Received in the China warehouse. Not a future date.'
            }
          />
        )}
        <DateField
          label={deliveryDateMode === 'multiple_days' ? 'Loading date (shared default)' : 'Loading date'}
          name="loadingDate"
          optional
          value={loadingDate}
          onChange={(e) => setLoadingDate(e.target.value)}
          min={deliveryDateMode === 'same_day' ? deliveryDate || undefined : undefined}
          error={loadingDateError}
          helper={
            loadingDateError
              ? undefined
              : deliveryDateMode === 'multiple_days'
                ? 'Default loading date for the consolidated load — individual items can override it in Step 2.'
                : 'Loaded into the container. Same day as delivery or later (items can override in Step 2).'
          }
        />
      </div>

      <div className={styles.spacerLg} />
      <Field
        label="Remarks / packing instructions"
        name="remarks"
        optional
        multiline
        placeholder="e.g. Compression instructions, fragile handling notes…"
        value={remarks}
        onChange={(e) => setRemarks(e.target.value)}
        helper="Printed on the Loading Receipt and Packing List."
      />

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
