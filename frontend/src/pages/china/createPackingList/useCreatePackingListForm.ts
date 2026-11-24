import { useContext, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../../api/client'
import { SessionContext } from '../../../auth/SessionContext'
import {
  packingListApi,
  type PackageUnit,
  type PackingList,
  type PackingListItemInput,
} from '../../../api/packingList'
import { type Container } from '../../../api/tracking'
import { type Customer } from '../../../api/tenantManagement'
import { useIdempotencyKey } from '../../../api/useIdempotencyKey'
import { useContainerLookup } from '../../../hooks/useContainers'
import { useCustomerLookup } from '../../../hooks/useCustomers'
import { usePackingListForEdit } from '../../../hooks/usePackingLists'
import { useSeedOnce } from '../../../hooks/useSeedOnce'
import { useWarehouses } from '../../../hooks/useWarehouses'
import { collapseBatches, emptyItem } from './items'
import { usePackingListPricing } from './usePackingListPricing'
import { useBreadcrumbLabel } from '../../../shell/breadcrumbs'
import { readTabDraft, useTabDraft } from '../../../hooks/useTabDraft'
import { toast } from '../../../design/toast'

/** The wizard's input as kept in the tab (FD-25). */
interface WizardDraft {
  step: 1 | 2 | 3
  customerId: string
  containerId: string
  arrivalWarehouseId: string
  loadingDate: string
  deliveryDate: string
  items: PackingListItemInput[]
}

const DRAFT_FORM = 'packing-list'

/** The wizard's fields as one comparable string; which step it is on is not input. */
function fieldsSnapshot(draft: WizardDraft): string {
  return JSON.stringify({ ...draft, step: null })
}

/**
 * Everything the create/edit packing-list wizard holds: the chosen customer, container and dates, the item rows, the
 * draft being edited, the save. ``CreatePackingList`` renders the wizard; each step reads what it needs from here.
 */
export function useCreatePackingListForm() {
  const navigate = useNavigate()
  const { id: editId } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const prefilledContainerId = !editId ? (searchParams.get('container_id') ?? '') : ''
  const session = useContext(SessionContext)?.session

  // The list THIS page created, if it already saved once.
  //
  // Without it, every save took the create branch: a second "Save draft" made
  // a second packing list holding the same cargo, which is what "it keeps
  // saving a new copy" meant. The page normally navigates away after saving,
  // so it needs a returning user, a failed navigation, or a save that errors
  // after the create succeeded — but all three happen, and duplicated cargo is
  // expensive to notice later.
  //
  // Once a list exists, this page edits it. That is also what makes the save
  // button safe to press twice.
  const [createdId, setCreatedId] = useState<string | null>(null)
  const targetListId = editId ?? createdId
  const isEdit = Boolean(targetListId)
  // `regenerate` is intentionally unused: this page creates at most one
  // packing list, then edits it. Regenerating after a successful create
  // would discard the only thing protecting a double-submit.
  const { key } = useIdempotencyKey()
  // A new list's input is kept in the tab as it is typed (FD-25): leaving to create the container it needs, a reload
  // or the back button brings the user back to the form as they left it. A server draft being edited is not.
  const keepsTabDraft = !editId
  const [seed] = useState(() => (keepsTabDraft ? readTabDraft<WizardDraft>(DRAFT_FORM, session) : null))
  const [step, setStep] = useState<1 | 2 | 3>(seed?.step ?? 1)
  const [customerId, setCustomerId] = useState(seed?.customerId ?? '')
  const [containerId, setContainerId] = useState(prefilledContainerId || (seed?.containerId ?? ''))
  const [arrivalWarehouseId, setArrivalWarehouseId] = useState(seed?.arrivalWarehouseId ?? '')
  const [loadingDate, setLoadingDate] = useState(seed?.loadingDate ?? '')
  const [deliveryDate, setDeliveryDate] = useState(seed?.deliveryDate ?? '')
  const [items, setItems] = useState<PackingListItemInput[]>(seed?.items ?? [emptyItem()])
  // CBM and dollar rates, totals and the live shipping estimate (usePackingListPricing).
  const {
    cbmRateQuery,
    dollarRateQuery,
    cbmRate,
    cbmCurrency,
    fxRate,
    tenantMinCbm,
    minCbm,
    rawCbm,
    qtyOf,
    totals,
    bulkLines,
    cbmCharge,
    shippingUsd,
    shippingNgn,
  } = usePackingListPricing(items)
  // Set when a save is held back pending confirmation of a bulk line.
  const [pendingSave, setPendingSave] = useState<{ submitForApproval: boolean } | null>(null)
  // When editing a draft, the customer/container are fixed (the update API
  // keeps them) — show them read-only once loaded.
  const [draftSeeded, setDraftSeeded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setError] = useState<string | null>(null)

  // ---- Server data (React Query; audit FE-05). Nothing here is fetched in an effect. ----

  // Pickers. Only 'loading' containers can receive new packing lists — sealed/in-transit containers are closed to
  // additions (enforced by the backend too).
  const customerLookup = useCustomerLookup()
  const containerLookup = useContainerLookup({ status: 'loading' })
  // The warehouse list is tolerated failing — it is one optional field on a long form, and a tenant that has
  // configured none is a legitimate state. But the failure must NOT read as an empty list: that rendered
  // "No warehouses configured" for what was actually a 403, so a permission bug looked like a configuration choice
  // for weeks. `warehouseError` says so in the UI instead.
  const warehouseQuery = useWarehouses()
  const warehouses = warehouseQuery.data ?? []
  const warehouseError = warehouseQuery.error
    ? warehouseQuery.error instanceof ApiError
      ? warehouseQuery.error.message
      : 'Could not load warehouses.'
    : null

  // The draft being edited, if any. Always read fresh, then copied into the form once.
  const draftQuery = usePackingListForEdit(editId)
  // On the edit page, name the list in the breadcrumb: Packing lists / PL-… / Edit (FD-46).
  useBreadcrumbLabel(draftQuery.data?.reference, '/packing-lists/:id')
  const draft = draftQuery.isFetchedAfterMount ? draftQuery.data : undefined
  const draftEditable =
    draft !== undefined && (draft.status === 'draft' || draft.status === 'rejected')
  // When editing a draft, the customer/container are fixed (the update API keeps them) — the form shows once the
  // draft has been copied in, or its read has failed.
  const editReady = !editId || draftSeeded || draftQuery.isError

  function fillFromDraft(pl: PackingList): void {
    try {
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
        // collapseBatches folds an expanded bulk line back into the single
        // row that produced it, so the quantity the user typed is what they
        // see when they reopen the draft.
        collapseBatches(
          pl.items.length > 0
            ? pl.items.map((it) => ({
                description: it.description,
                weight_dispatch_kg:
                  it.weight_dispatch_kg != null ? Number(it.weight_dispatch_kg) : undefined,
                weight_actual_kg:
                  it.weight_actual_kg != null ? Number(it.weight_actual_kg) : undefined,
                length_cm: it.length_cm != null ? Number(it.length_cm) : undefined,
                width_cm: it.width_cm != null ? Number(it.width_cm) : undefined,
                height_cm: it.height_cm != null ? Number(it.height_cm) : undefined,
                declared_value_usd:
                  it.declared_value_usd != null ? Number(it.declared_value_usd) : undefined,
                package_unit: (it.package_unit as PackageUnit) ?? 'carton',
                // Carried through because the server falls back to
                // `received_date or date.today()`. Dropping it meant editing a
                // draft silently re-dated every item to today — and the
                // tracking code is derived from customer + received date, so
                // the grouping moved with it. Worst on an imported list, where
                // that date is real rather than the day of entry.
                received_date: it.received_date ?? undefined,
                // Carried through so an edit round trip keeps the grouping. The
                // rows arrive already expanded — one per package — so quantity
                // stays 1 here; re-expanding them would duplicate the cargo.
                batch_ref: it.batch_ref ?? null,
              }))
            : [emptyItem()],
        ),
      )
    } finally {
      setDraftSeeded(true)
    }
  }
  useSeedOnce(draftQuery, fillFromDraft)

  // Pre-select the tenant's default warehouse on a fresh create (on edit, the draft's saved value is used instead).
  // A cached warehouse list is fine to pick the default from, so this does not wait for a re-read.
  useSeedOnce(
    { data: editId ? undefined : warehouseQuery.data, isFetchedAfterMount: true },
    (rows) => {
      const def = rows.find((w) => w.is_default)
      if (def) setArrivalWarehouseId((prev) => prev || def.id)
    },
  )

  // The tab keeps the input until it is saved for real. An untouched form (the default warehouse pre-selected and
  // nothing else) stores nothing, so opening the wizard and leaving does not leave a "draft" behind.
  const defaultWarehouseId = warehouseQuery.data?.find((w) => w.is_default)?.id ?? ''
  const current: WizardDraft = { step, customerId, containerId, arrivalWarehouseId, loadingDate, deliveryDate, items }
  const pristine: WizardDraft = {
    step,
    customerId: '',
    containerId: prefilledContainerId,
    arrivalWarehouseId: arrivalWarehouseId === defaultWarehouseId ? arrivalWarehouseId : '',
    loadingDate: '',
    deliveryDate: '',
    items: [emptyItem()],
  }
  const tabDraft = useTabDraft<WizardDraft>(DRAFT_FORM, current, pristine, keepsTabDraft)

  // Unsaved input, for the leave-without-saving guard (FD-54). A new list: anything typed. A server draft being
  // edited: anything changed since it was loaded (its fields as copied in are the baseline, the step aside).
  const snapshot = fieldsSnapshot(current)
  const [editBaseline, setEditBaseline] = useState<string | null>(null)
  if (editId && draftSeeded && editBaseline === null) setEditBaseline(snapshot)
  const hasUnsavedInput = editId
    ? editBaseline !== null && snapshot !== editBaseline
    : snapshot !== fieldsSnapshot(pristine)
  // Whether the form opened from the tab's draft, to say so; dismissed once the user starts over or acknowledges it.
  const [restoredDraft, setRestoredDraft] = useState(seed !== null)

  /** Discard the tab's draft and begin a blank packing list. */
  function startOver(): void {
    tabDraft.clear()
    setRestoredDraft(false)
    setStep(1)
    setCustomerId('')
    setContainerId('')
    setArrivalWarehouseId(defaultWarehouseId)
    setLoadingDate('')
    setDeliveryDate('')
    setItems([emptyItem()])
  }

  // The pickers only list open containers; when editing, make sure the draft's own (fixed) customer and container
  // are in them even if the container has since moved on.
  const customers = useMemo<Customer[]>(() => {
    const rows = customerLookup.data?.data ?? []
    if (!draftEditable || !draft || rows.some((c) => c.id === draft.customer_id)) return rows
    return [{ id: draft.customer_id, name: draft.customer_name ?? '—' } as Customer, ...rows]
  }, [customerLookup.data, draft, draftEditable])
  const containers = useMemo<Container[]>(() => {
    const rows = containerLookup.data?.data ?? []
    if (!draftEditable || !draft || rows.some((c) => c.id === draft.container_id)) return rows
    return [
      {
        id: draft.container_id,
        container_number: draft.container_number ?? '—',
      } as Container,
      ...rows,
    ]
  }, [containerLookup.data, draft, draftEditable])

  const pickerFailure = customerLookup.error ?? containerLookup.error
  const loadError = draftQuery.error
    ? draftQuery.error instanceof ApiError
      ? draftQuery.error.message
      : 'Could not load the packing list.'
    : pickerFailure
      ? pickerFailure instanceof ApiError
        ? pickerFailure.message
        : 'Could not load customers or containers.'
      : null
  const error = actionError ?? loadError

  const selectedCustomer = customers.find((c) => c.id === customerId)
  const selectedContainer = containers.find((c) => c.id === containerId)

  function updateItem(index: number, patch: Partial<PackingListItemInput>): void {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  }

  function removeItem(index: number): void {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  function duplicateItem(index: number): void {
    setItems((prev) => {
      const source = prev[index]
      if (!source) return prev
      const copy: PackingListItemInput = {
        ...source,
        batch_ref: undefined,
        quantity: 1,
        identical_confirmed: false,
      }
      return [...prev.slice(0, index + 1), copy, ...prev.slice(index + 1)]
    })
  }

  /** Drop every row that came from one quantity entry.
   *
   *  The reason batch_ref exists. A quantity typed wrongly creates a hundred
   *  rows, and undoing that one row at a time is bad enough that someone would
   *  reasonably just leave it — which is how wrong cargo data survives. One
   *  action to remove the batch keeps the mistake cheap.
   */
  function removeBatch(batchRef: string): void {
    setItems((prev) => {
      const kept = prev.filter((item) => item.batch_ref !== batchRef)
      return kept.length > 0 ? kept : [emptyItem()]
    })
  }

  /** How many rows share this batch — shown so "remove" states its own cost. */
  function batchSize(batchRef: string | null | undefined): number {
    if (!batchRef) return 0
    return items.filter((item) => item.batch_ref === batchRef).length
  }

  /** Ask before creating a lot of packages from one keystroke.
   *
   *  Only above BULK_CONFIRM_THRESHOLD: prompting on every "2" would train
   *  people to dismiss it, which is worse than not asking. The dialog restates
   *  the figures that actually matter — package count, CBM, weight — because
   *  "500" in a narrow input looks much like "50", while the CBM it implies
   *  does not.
   */
  async function requestSave(submitForApproval: boolean): Promise<void> {
    if (bulkLines.length > 0) {
      setPendingSave({ submitForApproval })
      return
    }
    await handleSave(submitForApproval)
  }

  async function handleSave(submitForApproval: boolean): Promise<void> {
    setPendingSave(null)
    setSubmitting(true)
    setError(null)
    try {
      let targetId: string
      if (targetListId) {
        const updated = await packingListApi.update(targetListId, {
          loading_date: loadingDate || undefined,
          delivery_date: deliveryDate || undefined,
          arrival_warehouse_id: arrivalWarehouseId || undefined,
          items,
        })
        toast.success('Draft saved')
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
        // Remember it, so a second save edits this list instead of making
        // another one. The idempotency key is deliberately NOT regenerated
        // here: it guarded this create, and the next save is an update.
        setCreatedId(created.id)
        targetId = created.id
      }
      // Saved on the server now, which is the draft from here on.
      tabDraft.clear()
      if (submitForApproval) {
        await packingListApi.submit(targetId)
        toast.success('Packing list submitted for approval')
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

  // A restored draft can name a container that has since been sealed; it is no longer offered, so it cannot be used.
  const canProceedFrom1 =
    Boolean(customerId && selectedContainer) && !deliveryDateError && !loadingDateError
  const canProceedFrom2 = items.length > 0 && items.every((item) => item.description.trim() !== '')

  return {
    navigate,
    editId,
    createdId,
    setCreatedId,
    targetListId,
    isEdit,
    key,
    step,
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
    items,
    setItems,
    pendingSave,
    setPendingSave,
    draftSeeded,
    setDraftSeeded,
    submitting,
    setSubmitting,
    actionError,
    setError,
    customerLookup,
    containerLookup,
    warehouseQuery,
    warehouses,
    warehouseError,
    cbmRateQuery,
    dollarRateQuery,
    cbmRate,
    cbmCurrency,
    fxRate,
    tenantMinCbm,
    minCbm,
    draftQuery,
    draft,
    draftEditable,
    editReady,
    customers,
    containers,
    pickerFailure,
    loadError,
    error,
    selectedCustomer,
    selectedContainer,
    totals,
    bulkLines,
    cbmCharge,
    shippingUsd,
    shippingNgn,
    now,
    today,
    deliveryDateError,
    loadingDateError,
    canProceedFrom1,
    canProceedFrom2,
    fillFromDraft,
    rawCbm,
    qtyOf,
    updateItem,
    removeItem,
    duplicateItem,
    removeBatch,
    batchSize,
    requestSave,
    handleSave,
    tabDraft,
    hasUnsavedInput,
    restoredDraft,
    setRestoredDraft,
    startOver,
  }
}

export type PackingListForm = ReturnType<typeof useCreatePackingListForm>
