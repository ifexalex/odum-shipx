import { useCallback, useEffect, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { releaseNoteKeys } from '../../api/keys'
import { releaseNotesApi, type DelegateIdType, type PickupResult, type ReleaseNote, type RecordPickupInput } from '../../api/releaseNotes'
import {
  canRecordPickup,
  canSplitNote,
  isTerminalReleaseStatus,
  releaseNoteStatusLabel,
  releaseTypeLabel,
} from '../../api/releaseNotesRules'
import { useSession } from '../../auth/useSession'
import { useStaffList } from '../../hooks/useStaff'
import { useWarehouses } from '../../hooks/useWarehouses'
import {
  Action,
  Badge,
  Banner,
  Button,
  Card,
  ExportButton,
  Field,
  Icon,
  Kvp,
  Mono,
  PhoneField,
  StatCard,
  ToggleSwitch,
  type BadgeVariant,
} from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ReleaseNoteDetail.module.css'

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<ReleaseNote['status'], BadgeVariant> = {
  active: 'success',
  picked_up: 'neutral',
  expired: 'error',
  cancelled: 'neutral',
}

// ---------------------------------------------------------------------------
// RecordPickupModal — mobile-optimised, large touch targets
// ---------------------------------------------------------------------------

interface RecordPickupModalProps {
  note: ReleaseNote
  onCancel: () => void
  onSuccess: (result: PickupResult) => void
}

const ID_TYPES: { value: DelegateIdType; label: string }[] = [
  { value: 'national_id', label: 'National ID' },
  { value: 'drivers_license', label: "Driver's licence" },
  { value: 'passport', label: 'Passport' },
]

function RecordPickupModal({ note, onCancel, onSuccess }: RecordPickupModalProps): JSX.Element {
  const [cartons, setCartons] = useState(String(note.carton_count))
  const [isDelegate, setIsDelegate] = useState(false)
  // Required by the backend when the customer collects in person (not via a
  // delegate) — RecordPickupRequest's _require_collector_name_for_non_delegate.
  // Defaults to the note's own customer, since that's who collects in the
  // common case; staff can overtype it (an employee, a family member, etc.
  // showing up without going through the delegate ID-verification flow).
  const [collectedByName, setCollectedByName] = useState(note.customer_name ?? '')
  const [delegateName, setDelegateName] = useState('')
  const [delegatePhone, setDelegatePhone] = useState('')
  const [delegateIdType, setDelegateIdType] = useState<DelegateIdType>('national_id')
  const [delegateIdNumber, setDelegateIdNumber] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [csoId, setCsoId] = useState('')
  const [accountingOfficerId, setAccountingOfficerId] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: warehouses = [] } = useWarehouses()
  const { data: staffList } = useStaffList()
  const staff = staffList ?? []

  const delegateFilled = !isDelegate || (
    delegateName.trim().length > 0 &&
    delegatePhone.trim().length > 0 &&
    delegateIdNumber.trim().length > 0
  )
  const collectorNamed = isDelegate || collectedByName.trim().length > 0
  const canSubmit = Number(cartons) > 0 && delegateFilled && collectorNamed && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: RecordPickupInput = { cartons_released: Number(cartons) }
      if (isDelegate) {
        body.is_delegate = true
        body.delegate_name = delegateName
        body.delegate_phone = delegatePhone
        body.delegate_id_type = delegateIdType
        body.delegate_id_number = delegateIdNumber
      } else {
        body.collected_by_name = collectedByName.trim()
      }
      if (warehouseId) body.warehouse_id = warehouseId
      if (csoId) body.customer_service_officer_id = csoId
      if (accountingOfficerId) body.accounting_officer_id = accountingOfficerId
      if (notes.trim()) body.notes = notes
      const result = await releaseNotesApi.recordPickup(note.id, body)
      onSuccess(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record pickup.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Record pickup — {note.reference_number}</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}

        <Field
          label="Cartons collected"
          name="cartons_released"
          required
          type="number"
          value={cartons}
          onChange={(e) => setCartons(e.target.value)}
        />

        <label className={styles.delegateToggle}>
          <ToggleSwitch checked={isDelegate} onChange={setIsDelegate} />
          <span>Collected by a delegate (not the customer)</span>
        </label>

        {!isDelegate && (
          <Field
            label="Collected by"
            name="collected_by_name"
            required
            value={collectedByName}
            onChange={(e) => setCollectedByName(e.target.value)}
            placeholder="Name of the person collecting"
          />
        )}

        {isDelegate && (
          <>
            <Field label="Delegate name" name="delegate_name" required value={delegateName} onChange={(e) => setDelegateName(e.target.value)} />
            <PhoneField label="Delegate phone" name="delegate_phone" required value={delegatePhone} onChange={setDelegatePhone} />
            <div>
              <label style={{ fontSize: '0.875rem', fontWeight: 600, display: 'block', marginBottom: 6 }}>
                ID type <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <select
                aria-label="ID type"
                className={styles.rawSelect}
                value={delegateIdType}
                onChange={(e) => setDelegateIdType(e.target.value as DelegateIdType)}
              >
                {ID_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <Field label="ID number" name="delegate_id_number" required value={delegateIdNumber} onChange={(e) => setDelegateIdNumber(e.target.value)} />
          </>
        )}

        {/* Ground-truth gap found live, against a real paper "Goods Release
            Note" reference: two further named sign-off lines exist alongside
            the warehouse attendant (implicitly the acting user) — Customer
            Service Officer and Accounting Officer. Optional: a small
            warehouse doesn't necessarily split these duties out. */}
        {warehouses.length > 0 && (
          <div>
            <label style={{ fontSize: '0.875rem', fontWeight: 600, display: 'block', marginBottom: 6 }}>
              Warehouse / branch <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>Optional</span>
            </label>
            <select
              aria-label="Warehouse / branch"
              className={styles.rawSelect}
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              <option value="">Use the note's own warehouse…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
              ))}
            </select>
          </div>
        )}
        {staff.length > 0 && (
          <>
            <div>
              <label style={{ fontSize: '0.875rem', fontWeight: 600, display: 'block', marginBottom: 6 }}>
                Customer Service Officer <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>Optional</span>
              </label>
              <select
                aria-label="Customer Service Officer"
                className={styles.rawSelect}
                value={csoId}
                onChange={(e) => setCsoId(e.target.value)}
              >
                <option value="">None</option>
                {staff.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '0.875rem', fontWeight: 600, display: 'block', marginBottom: 6 }}>
                Accounting Officer <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>Optional</span>
              </label>
              <select
                aria-label="Accounting Officer"
                className={styles.rawSelect}
                value={accountingOfficerId}
                onChange={(e) => setAccountingOfficerId(e.target.value)}
              >
                <option value="">None</option>
                {staff.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </select>
            </div>
          </>
        )}

        <Field label="Notes" name="notes" multiline optional placeholder="Any observations about the pickup…" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="success" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Confirm pickup
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ReissueConfirmModal
// ---------------------------------------------------------------------------

interface ReissueConfirmModalProps {
  note: ReleaseNote
  onCancel: () => void
  onSuccess: (newNote: ReleaseNote) => void
}

function ReissueConfirmModal({ note, onCancel, onSuccess }: ReissueConfirmModalProps): JSX.Element {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleReissue(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const newNote = await releaseNotesApi.reissue(note.id)
      onSuccess(newNote)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not re-issue this release note.')
    } finally {
      setSubmitting(false)
    }
  }

  const storageFees = Number(note.storage_fees_ngn ?? 0)
  const expiredDate = note.expired_at ? note.expired_at.slice(0, 10) : '—'

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Re-issue release note</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <Banner variant="warning" title="Outstanding storage fees">
          {storageFees > 0
            ? `This release note has ₦${storageFees.toLocaleString()} in outstanding storage fees. The new note will carry this balance forward.`
            : 'No outstanding storage fees on this release note.'}
        </Banner>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-muted)', margin: 0 }}>
          A new release note will be created with the same carton tags and a fresh 14-day window.
          The expired note ({note.reference_number}, expired {expiredDate}) will be preserved for audit purposes.
        </p>
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} onClick={() => void handleReissue()}>
            Re-issue release note
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SplitNoteModal
// ---------------------------------------------------------------------------

interface SplitModalProps {
  note: ReleaseNote
  onCancel: () => void
  onSuccess: (child: ReleaseNote) => void
}

function SplitModal({ note, onCancel, onSuccess }: SplitModalProps): JSX.Element {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [splitNotes, setSplitNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleTag(tag: string): void {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const child = await releaseNotesApi.split(note.id, {
        carton_tags: Array.from(selected),
        notes: splitNotes || undefined,
      })
      onSuccess(child)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not split release note.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Split release note</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <p className={styles.splitInstruction}>
          Select the carton tags to move into a new child release note. The remaining tags stay on this note.
        </p>
        <div className={styles.tagGrid}>
          {note.carton_tags.map((tag) => (
            <span
              key={tag}
              className={[styles.tag, styles.tagClickable, selected.has(tag) ? styles.tagSelected : ''].join(' ')}
              onClick={() => toggleTag(tag)}
              role="checkbox"
              aria-checked={selected.has(tag)}
              tabIndex={0}
              onKeyDown={(e) => e.key === ' ' && toggleTag(tag)}
            >
              {tag}
            </span>
          ))}
        </div>
        {selected.size > 0 && (
          <p className={styles.splitCount}>{selected.size} carton(s) selected for new note</p>
        )}
        <Field label="Notes" name="split_notes" multiline optional placeholder="Reason for splitting…" value={splitNotes} onChange={(e) => setSplitNotes(e.target.value)} />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={selected.size === 0} onClick={() => void handleSubmit()}>
            Create child note
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function ReleaseNoteDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const stateNote = (location.state as { note?: ReleaseNote } | null)?.note ?? null
  const [note, setNote] = useState<ReleaseNote | null>(stateNote)
  const [loading, setLoading] = useState(stateNote === null)
  const [error, setError] = useState<string | null>(null)
  const [showPickup, setShowPickup] = useState(false)
  const [showSplit, setShowSplit] = useState(false)
  const [showReissue, setShowReissue] = useState(false)
  const [pickupResult, setPickupResult] = useState<PickupResult | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const result = await releaseNotesApi.get(id)
      setNote(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load this release note.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (stateNote === null) void load()
  }, [load, stateNote])

  if (loading && !note) return <div className={styles.loadingState}>Loading release note…</div>
  if (error && !note) {
    return (
      <div className={styles.loadingState}>
        <Banner variant="error" title="Couldn't load this release note">{error ?? 'Not found.'}</Banner>
      </div>
    )
  }
  if (!note) return <></>

  const r = role as Parameters<typeof canRecordPickup>[1]
  const showPickupBtn = canRecordPickup(note, r)
  const showSplitBtn = canSplitNote(note, r)
  const isTerminal = isTerminalReleaseStatus(note.status)
  const isExpired = note.status === 'expired'
  const storageFees = Number(note.storage_fees_ngn ?? 0)

  return (
    <div>
      {/* Hero */}
      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroIcon}>
            <Icon name="file" size={28} stroke={2} />
          </div>
          <div>
            <div className={styles.heroTitleRow}>
              <h1 className={styles.heroTitle}>{note.reference_number}</h1>
              <Badge variant={STATUS_VARIANT[note.status]}>{releaseNoteStatusLabel(note.status)}</Badge>
              {note.is_partial_release && (
                <Badge variant="warning">Partial</Badge>
              )}
            </div>
            <div className={styles.heroMeta}>
              {note.customer_name && <span>{note.customer_name}</span>}
              {note.container_number && <span> · {note.container_number}</span>}
              <span> · Issued {note.authorized_at.slice(0, 10)}</span>
              {note.valid_until && !isExpired && (
                <span> · Valid until {note.valid_until}</span>
              )}
            </div>
          </div>
        </div>

        <div className={styles.heroActions}>
          <ExportButton
            formats={['pdf']}
            onExport={() => releaseNotesApi.pdf(note.id)}
          />
          <Button variant="secondary" icon="file" onClick={() => navigate(`/release-notes/${note.id}/print`)}>
            Print view
          </Button>
          {isExpired && (
            <Action variant="primary" icon="refresh" onClick={() => setShowReissue(true)}>
              Re-issue release note
            </Action>
          )}
          {!isTerminal && !isExpired && showPickupBtn && (
            <Action variant="success" icon="check" onClick={() => setShowPickup(true)}>
              Record pickup
            </Action>
          )}
          {!isTerminal && !isExpired && showSplitBtn && note.carton_tags.length > 1 && (
            <Action variant="secondary" onClick={() => setShowSplit(true)}>
              Split note
            </Action>
          )}
        </div>
      </div>

      {/* Expired state banners */}
      {isExpired && (
        <div className={styles.section}>
          <Banner variant="error" title="Release note expired">
            This release note expired on {note.expired_at ? note.expired_at.slice(0, 10) : '—'}.
            The customer cannot collect their goods until a new release note is issued.
          </Banner>
        </div>
      )}
      {isExpired && storageFees > 0 && (
        <div className={styles.section}>
          <Banner variant="warning" title={`Outstanding storage fees: ₦${storageFees.toLocaleString()}`}>
            Storage fees continue to accrue until the goods are collected. The balance will carry forward to the re-issued note.
          </Banner>
        </div>
      )}
      {isExpired && (
        <div className={styles.section}>
          <Banner variant="warning" title="Warehouse notice">
            Goods remaining in the warehouse past the release window may be subject to long-term storage charges.
            Re-issue this note and notify the customer immediately.
          </Banner>
        </div>
      )}

      {/* Pickup success feedback */}
      {pickupResult && (
        <div className={styles.successBanner}>
          <Banner variant="success" title="Pickup recorded">
            {pickupResult.remaining_cartons > 0
              ? `${pickupResult.remaining_cartons} carton(s) still pending collection on this note.`
              : 'All cartons on this note have been collected.'}
            {pickupResult.shipment_status === 'picked_up' && ' All customer cartons are now picked up — shipment tracking updated.'}
          </Banner>
        </div>
      )}

      {/* Stats */}
      <div className={styles.statsRow}>
        <StatCard label="Cartons on note" value={`${note.carton_count} of ${note.total_cartons_for_customer}`} />
        <StatCard label="Type" value={releaseTypeLabel(note)} />
        <StatCard label="Payment status" value={note.payment_status.replace('_', ' ')} />
        {isExpired && storageFees > 0 && (
          <StatCard label="Storage fees" value={`₦${storageFees.toLocaleString()}`} />
        )}
      </div>

      {/* Details */}
      <div className={styles.section}>
        <SectionHead title="Release details" />
        <Card padding={20}>
          <Kvp label="Reference" value={<Mono>{note.reference_number}</Mono>} />
          {note.physical_document_number && (
            <Kvp label="Physical document no." value={<Mono>{note.physical_document_number}</Mono>} />
          )}
          <Kvp label="Customer" value={note.customer_name ?? '—'} />
          <Kvp label="Container" value={note.container_number ? <Mono>{note.container_number}</Mono> : '—'} />
          <Kvp
            label="Carton count"
            value={
              note.package_unit
                ? <Mono>{note.packages_released} of {note.total_cartons_for_customer} {note.package_unit}</Mono>
                : <Mono>{note.carton_count} / {note.total_cartons_for_customer} (customer total)</Mono>
            }
          />
          {note.packages_balance != null && note.packages_balance > 0 && (
            <Kvp label="Balance remaining" value={<Mono>{note.packages_balance}</Mono>} />
          )}
          {note.packing_list_invoice_numbers.length > 0 && (
            <Kvp label="Packing list invoice(s)" value={note.packing_list_invoice_numbers.join(', ')} />
          )}
          <Kvp label="Warehouse" value={note.warehouse_name ? `${note.warehouse_name}${note.warehouse_address ? ` — ${note.warehouse_address}` : ''}` : '—'} />
          <Kvp label="Issued" value={note.authorized_at.slice(0, 10)} divider={!note.is_on_credit && !note.receipt_number} />
          {note.is_on_credit && (
            <Kvp
              label="On credit"
              value={`Yes${note.credit_granted_by_name ? ` — granted by ${note.credit_granted_by_name}` : ''}`}
            />
          )}
          {note.receipt_number && <Kvp label="Receipt no." value={<Mono>{note.receipt_number}</Mono>} />}
          {(Number(note.amount_paid_ngn) > 0 || Number(note.balance_ngn) > 0) && (
            <Kvp
              label="Payment"
              value={`₦${Number(note.amount_paid_ngn).toLocaleString()} paid of ₦${Number(note.total_ngn).toLocaleString()} — ₦${Number(note.balance_ngn).toLocaleString()} outstanding`}
            />
          )}
          {note.debt_due_date && <Kvp label="Debt payment due" value={note.debt_due_date} divider={false} />}
        </Card>
      </div>

      {/* Carton tags */}
      <div className={styles.section}>
        <SectionHead title="Carton tags" sub={`${note.carton_tags.length} tag(s) on this release note`} />
        <Card padding={20}>
          {note.carton_tags.length > 0 ? (
            <div className={styles.tagGrid}>
              {note.carton_tags.map((tag) => (
                <span key={tag} className={styles.tag}>{tag}</span>
              ))}
            </div>
          ) : (
            <span style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>No carton tags recorded.</span>
          )}
        </Card>
      </div>

      <div className={styles.backLink}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/release-notes')}>
          Back to release notes
        </Button>
      </div>

      {/* Modals */}
      {showPickup && (
        <RecordPickupModal
          note={note}
          onCancel={() => setShowPickup(false)}
          onSuccess={(result) => {
            setShowPickup(false)
            setPickupResult(result)
            if (result.release_note_status !== note.status) {
              setNote({ ...note, status: result.release_note_status })
            }
            // Ground-truth gap found live: none of this page's mutations
            // (pickup, split, reissue) ever invalidated the release-notes
            // list query — with the 3-minute default staleTime
            // (lib/queryClient.ts), the list kept showing pre-mutation data
            // for up to 3 minutes after a pickup/split/reissue if it had
            // already been fetched once in the same session.
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
          }}
        />
      )}
      {showSplit && (
        <SplitModal
          note={note}
          onCancel={() => setShowSplit(false)}
          onSuccess={(_child) => {
            setShowSplit(false)
            void load()
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
          }}
        />
      )}
      {showReissue && (
        <ReissueConfirmModal
          note={note}
          onCancel={() => setShowReissue(false)}
          onSuccess={(newNote) => {
            setShowReissue(false)
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
            navigate(`/release-notes/${newNote.id}`, { state: { note: newNote } })
          }}
        />
      )}
    </div>
  )
}
