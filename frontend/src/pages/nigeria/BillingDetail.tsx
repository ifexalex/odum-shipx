import { useCallback, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { billingApi, carryoverApi, type Billing, type Carryover, type CBMDispute } from '../../api/billing'
import { canApplyCarryover, canCancelBilling, canRecordPayment } from '../../api/billingRules'
import { useSession } from '../../auth/useSession'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { billingKeys, releaseNoteKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { Action, Banner, ExportButton, Icon, Mono, StatCard, StatusBadge, PageSkeleton, ErrorState } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './BillingDetail.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { StorageFeeBanner, StorageFeeLog } from './billingDetail/StorageFees'
import { DisputeCard } from './billingDetail/DisputeCard'
import { RecordPaymentModal } from './billingDetail/RecordPaymentModal'
import { AddChargeModal, CancelBillingModal, ApplyCarryoverModal } from './billingDetail/ChargeModals'
import { GenerateReleaseNoteModal } from './billingDetail/GenerateReleaseNoteModal'
import { BillingBreakdown, PaymentsTable } from './billingDetail/Breakdown'
import { MiscChargesSection } from './billingDetail/MiscCharges'
import { PaymentClaimsSection } from './billingDetail/PaymentClaims'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'


// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function BillingDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'
  const qc = useQueryClient()

  // Ground-truth gap found live, reported by the user: "i approved a payment,
  // but it did not record the payment as paid, until i refreshed the page."
  // Every mutation on this page used to refresh only this component's own local
  // `billing` state, never react-query's cache, so `BillingList.tsx`'s
  // `billingKeys.list(...)` query kept serving the pre-mutation row on every
  // other screen until a hard refresh.
  //
  // Since 7.150 the record itself is a query at `billingKeys.detail(id)`, which
  // is a *child* of `billingKeys.all` — so this one invalidation now refreshes
  // this page as well as every list. That is why the six `await load()` calls
  // that used to sit beside each of these calls are gone rather than rewritten:
  // the reload they did is what the invalidation already does.
  const invalidateBillingCaches = useCallback(() => {
    void qc.invalidateQueries({ queryKey: billingKeys.all })
  }, [qc])

  // Router state from BillingList seeds the first paint so arriving from the
  // list renders instantly; GET /v1/billing/{id}/detail is the real source and
  // backs direct links plus every refresh after a mutation.
  const stateBilling = (location.state as { billing?: Billing } | null)?.billing ?? null
  const { data: billing = null, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: billingKeys.detail(id ?? ''),
    queryFn: () => billingApi.get(id!),
    enabled: !!id,
    ...(stateBilling ? { initialData: stateBilling } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(billing?.invoice_number)
  const [carryovers, setCarryovers] = useState<Carryover[]>([])
  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError && loadError.status === 404
        ? 'Billing record not found.'
        : loadError instanceof ApiError
          ? loadError.message
          : 'Could not load billing record.'
      : null)

  const applyBilling = (updated: Billing): void => {
    qc.setQueryData(billingKeys.detail(id ?? ''), updated)
  }

  const [showPaymentModal, setShowPaymentModal] = useState(false)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [showCarryoverModal, setShowCarryoverModal] = useState(false)
  const [showReleaseNoteModal, setShowReleaseNoteModal] = useState(false)
  const [showAddChargeModal, setShowAddChargeModal] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [waivingFees, setWaivingFees] = useState(false)

  // Storage fee accrual log — loaded lazily once a billing record is known
  const { data: storageFees = [] } = useQuery({
    queryKey: [...billingKeys.detail(id ?? ''), 'storage-fees'],
    queryFn: () => billingApi.listStorageFees(id!),
    enabled: !!id && !!billing && Number(billing.storage_fees_ngn) > 0,
    staleTime: 5 * 60 * 1000,
  })




  async function loadCarryovers(): Promise<void> {
    if (!billing) return
    try {
      // A carryover can only be applied to a billing for the SAME customer
      // (the backend rejects a mismatch, BR-CARRYOVER-003). Scope the list to
      // this billing's customer so the picker only offers applicable credits
      // instead of every customer's — picking a mismatch always failed.
      const result = await carryoverApi.list({
        status: 'outstanding',
        ...(billing.customer_id ? { customer_id: billing.customer_id } : {}),
      })
      setCarryovers(result.data)
    } catch {
      // non-fatal — user can still see the modal with empty state
    }
  }

  function handleDisputeUpdated(updated: CBMDispute): void {
    if (!billing) return
    applyBilling({
      ...billing,
      _active_disputes: billing._active_disputes.map((d) => (d.id === updated.id ? updated : d)),
    })
    invalidateBillingCaches()
  }

  if (loading) return <PageSkeleton kind="detail" label="Loading billing record" />
  if (error || !billing) {
    return (
      <ErrorState title="Couldn't load this billing record" error={loadError} message="We couldn't find this record. It may have been removed, or the link is out of date." onRetry={() => void refetch()} />
    )
  }

  const outstanding = Number(billing.outstanding_ngn)
  const isActionable = canRecordPayment(billing, role)
  const isCarryoverApplicable = canApplyCarryover(billing, role)
  const isCancellable = canCancelBilling(billing, role)
  const canGenerateRelease = (role === 'nigeria_office_staff' || role === 'tenant_admin') &&
    (billing.payment_status === 'paid' || billing.payment_status === 'overpaid' ||
     billing.payment_status === 'partially_paid')
  const canWaiveFees = (role === 'tenant_admin' || role === 'nigeria_office_staff') &&
    Number(billing.storage_fees_ngn) > 0 &&
    !['cancelled', 'waived'].includes(billing.payment_status)
  const isStaff = role === 'tenant_admin' || role === 'nigeria_office_staff'
  // Backend guard: charges can only be removed while the billing is unpaid,
  // and only by tenant_admin (services/billing/handler.py DELETE route).
  const canRemoveCharge = role === 'tenant_admin' && billing.payment_status === 'unpaid'

  async function handleWaiveStorageFees(): Promise<void> {
    if (!billing) return
    setWaivingFees(true)
    try {
      const updated = await billingApi.waiveStorageFees(billing.id, 'Waived by staff')
      toast.success('Storage fees waived', updated.invoice_number ?? undefined)
      applyBilling(updated)
      invalidateBillingCaches()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not waive storage fees.')
    } finally {
      setWaivingFees(false)
    }
  }



  return (
    <div>
      <PageHeader
        title={billing.invoice_number ? `Invoice ${billing.invoice_number}` : 'Invoice'}
        status={<StatusBadge kind="invoice" status={billing.payment_status} />}
        meta={[
          billing.customer_name,
          <>
            Container <Mono>{billing.container_number ?? billing.container_id}</Mono>
          </>,
          billing.billed_at && `Billed ${formatDate(billing.billed_at)}`,
          billing.customer_phone && (
            <span className={styles.contact}>
              <Icon name="phone" size={12} color="var(--color-ink-4)" />
              {billing.customer_phone}
            </span>
          ),
          billing.customer_email && (
            <span className={styles.contact}>
              <Icon name="mail" size={12} color="var(--color-ink-4)" />
              {billing.customer_email}
            </span>
          ),
        ]}
        primary={
          isActionable && (
            <Action variant="primary" icon="coin" onClick={() => setShowPaymentModal(true)}>
              Record payment
            </Action>
          )
        }
        actions={
          <>
            <ExportButton formats={['xlsx', 'csv']} onExport={(fmt) => billingApi.export(billing.id, fmt)} />
            {canGenerateRelease && (
              <Action variant="secondary" icon="file" onClick={() => setShowReleaseNoteModal(true)}>
                Generate release note
              </Action>
            )}
          </>
        }
        more={[
          ...(isStaff && billing.payment_status !== 'cancelled' && billing.payment_status !== 'waived'
            ? [{ label: 'Add charge', icon: 'plus' as const, mutates: true, onSelect: () => setShowAddChargeModal(true) }]
            : []),
          ...(isCarryoverApplicable
            ? [
                {
                  label: 'Apply carryover',
                  mutates: true,
                  onSelect: () => {
                    void loadCarryovers()
                    setShowCarryoverModal(true)
                  },
                },
              ]
            : []),
          ...(isCancellable
            ? [
                {
                  label: 'Cancel billing',
                  tone: 'danger' as const,
                  onSelect: () => {
                    setCancelError(null)
                    setShowCancelModal(true)
                  },
                },
              ]
            : []),
        ]}
        moreLabel="More invoice actions"
      />
      {session?.readOnly && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner variant="warning" icon="eye" title="Read-only session">
            You're viewing this tenant as their Tenant Admin for support. Data is fully visible, but every create, edit, approve, and delete action is disabled. The session ends automatically after 30 minutes or when you exit.
          </Banner>
        </div>
      )}

      {/* Stat cards */}
      <div className={styles.stats}>
        <StatCard label="Total CBM" value={Number(billing.total_cbm).toFixed(3)} />
        <StatCard label="Total due" value={formatNgn(billing.total_due_ngn)} />
        <StatCard label="Total paid" value={formatNgn(billing.total_paid_ngn)} />
        <StatCard
          label="Outstanding"
          value={formatNgn(outstanding)}
        />
      </div>

      {/* Storage fee banner + accrual log */}
      {(Number(billing.storage_fees_ngn) > 0 || billing.release_note_issued_at) && (
        <div className={styles.section}>
          <StorageFeeBanner
            billing={billing}
            storageFees={storageFees}
            canWaive={canWaiveFees}
            onWaive={() => void handleWaiveStorageFees()}
            waiving={waivingFees}
          />
          {storageFees.length > 0 && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <SectionHead title="Storage fee accrual log" />
              <div style={{ marginTop: 'var(--space-2)' }}>
                <StorageFeeLog fees={storageFees} />
              </div>
            </div>
          )}
        </div>
      )}

      <BillingBreakdown billing={billing} />

      <PaymentsTable payments={billing.payments} />

      <PaymentClaimsSection billingId={billing.id} isStaff={isStaff} onChanged={invalidateBillingCaches} />

      <MiscChargesSection
        billing={billing}
        canRemove={canRemoveCharge}
        onChanged={invalidateBillingCaches}
        onError={setActionError}
      />

      {/* Active disputes */}
      {billing._active_disputes.length > 0 && (
        <div className={styles.section}>
          <SectionHead title="CBM disputes" />
          {billing._active_disputes.map((d) => (
            <DisputeCard key={d.id} dispute={d} role={role} onUpdated={handleDisputeUpdated} />
          ))}
        </div>
      )}

      {/* Back link */}

      {/* Modals */}
      {showAddChargeModal && (
        <AddChargeModal
          billing={billing}
          onCancel={() => setShowAddChargeModal(false)}
          onSuccess={() => {
            setShowAddChargeModal(false)
            // Refreshes the charges list too: MiscChargesSection's query sits under billingKeys.all.
            invalidateBillingCaches()
          }}
        />
      )}
      {showPaymentModal && (
        <RecordPaymentModal
          billing={billing}
          onCancel={() => setShowPaymentModal(false)}
          onSuccess={() => {
            setShowPaymentModal(false)
            invalidateBillingCaches()
          }}
        />
      )}

      {showCancelModal && (
        <CancelBillingModal
          billingId={billing.id}
          error={cancelError}
          creditsNgn={-Number(billing.adjustments_ngn ?? 0)}
          carryoverNgn={billing.carryover_ngn}
          onCancel={() => setShowCancelModal(false)}
          onSuccess={(updated) => {
            setShowCancelModal(false)
            applyBilling(updated)
            invalidateBillingCaches()
          }}
        />
      )}

      {showCarryoverModal && (
        <ApplyCarryoverModal
          billing={billing}
          carryovers={carryovers}
          onCancel={() => setShowCarryoverModal(false)}
          onSuccess={() => {
            setShowCarryoverModal(false)
            invalidateBillingCaches()
          }}
        />
      )}

      {showReleaseNoteModal && (
        <GenerateReleaseNoteModal
          billing={billing}
          onCancel={() => setShowReleaseNoteModal(false)}
          onSuccess={() => {
            setShowReleaseNoteModal(false)
            invalidateBillingCaches()
            // Ground-truth gap found live: this navigates straight to the
            // release-notes list, but nothing invalidated its query cache —
            // with the 3-minute default staleTime (lib/queryClient.ts), a
            // list already fetched once this session kept showing
            // pre-generation data, hiding the note just created.
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
            navigate('/release-notes')
          }}
        />
      )}
    </div>
  )
}
