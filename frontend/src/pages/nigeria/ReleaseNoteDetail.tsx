import { useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { releaseNoteKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { releaseNotesApi, type DelegateIdType, type PickupResult, type ReleaseNote, type RecordPickupInput } from '../../api/releaseNotes'
import {
  canRecordPickup,
  canSendPickupCode,
  canSplitNote,
  isTerminalReleaseStatus,
  releaseTypeLabel,
  sentViaLabel,
} from '../../api/releaseNotesRules'
import { useSession } from '../../auth/useSession'
import { useStaffList } from '../../hooks/useStaff'
import { useWarehouses } from '../../hooks/useWarehouses'
import { Action, Badge, Banner, Button, ExportButton, Field, Kvp, Modal, Mono, PhoneField, StatusBadge, ToggleSwitch, Select, PageSkeleton, ErrorState } from '../../design/components'
import styles from './ReleaseNoteDetail.module.css'
import { formatDate, formatNgn, plural } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { DetailPage } from '../../shell/DetailPage'
import { PageHeader } from '../../shell/PageHeader'
import { RecordLink } from '../../shell/RecordLink'
import { Section } from '../../shell/Section'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

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
  const maxCartons =
    note.packages_balance != null && note.packages_balance > 0 ? note.packages_balance : note.carton_count
  const [cartons, setCartons] = useState(String(maxCartons))
  const [isDelegate, setIsDelegate] = useState(false)
  // Required by the backend when the customer collects in person (not via a
  // delegate) — RecordPickupRequest's _require_collector_name_for_non_delegate.
  // Defaults to the note's own customer, since that's who collects in the
  // common case; staff can overtype it (an employee, a family member, etc.
  // showing up without going through the delegate ID-verification flow).
  const [collectedByName, setCollectedByName] = useState(note.customer_name ?? '')
  const [pickupCode, setPickupCode] = useState('')
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

  const cartonsNum = Number(cartons)
  const cartonsValid = Number.isInteger(cartonsNum) && cartonsNum >= 1 && cartonsNum <= maxCartons
  const cartonsError =
    cartons.trim() !== '' && !cartonsValid
      ? `Enter a whole number between 1 and ${maxCartons}.`
      : undefined
  const delegateFilled = !isDelegate || (
    delegateName.trim().length > 0 &&
    delegatePhone.trim().length > 0 &&
    delegateIdNumber.trim().length > 0
  )
  const collectorNamed = isDelegate || collectedByName.trim().length > 0
  const codeRequired = note.pickup_code_required === true
  const codeLocked = note.pickup_code_locked === true
  const codeGiven = !codeRequired || pickupCode.trim().length > 0
  const canSubmit = cartonsValid && delegateFilled && collectorNamed && codeGiven && !codeLocked && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: RecordPickupInput = { cartons_released: cartonsNum }
      if (isDelegate) {
        body.is_delegate = true
        body.delegate_name = delegateName
        body.delegate_phone = delegatePhone
        body.delegate_id_type = delegateIdType
        body.delegate_id_number = delegateIdNumber
      } else {
        body.collected_by_name = collectedByName.trim()
      }
      if (codeRequired) body.pickup_code = pickupCode.trim()
      if (warehouseId) body.warehouse_id = warehouseId
      if (csoId) body.customer_service_officer_id = csoId
      if (accountingOfficerId) body.accounting_officer_id = accountingOfficerId
      if (notes.trim()) body.notes = notes
      const result = await releaseNotesApi.recordPickup(note.id, body)
      toast.success('Pickup recorded', note.reference_number)
      onSuccess(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not record pickup.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      onClose={onCancel}
      title={`Record pickup — ${note.reference_number}`}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Confirm pickup
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error" title="Action failed">{error}</Banner>}

        <Field
          label="Cartons collected"
          name="cartons_released"
          required
          type="number"
          min="1"
          max={String(maxCartons)}
          error={cartonsError}
          helper={`Up to ${plural(maxCartons, 'carton')} available for pickup on this note.`}
          value={cartons}
          onChange={(e) => setCartons(e.target.value)}
        />

        {codeLocked && (
          <Banner variant="error" title="Pickup code locked">
            Too many wrong codes were entered. Send the customer a new code before these goods can be released.
          </Banner>
        )}
        {codeRequired && !codeLocked && (
          <Field
            label="Pickup code"
            name="pickup_code"
            required
            inputMode="numeric"
            autoComplete="off"
            value={pickupCode}
            onChange={(e) => setPickupCode(e.target.value)}
            placeholder="6-digit code"
            helper="Ask the collector for the code that was sent to the customer."
          />
        )}

        <label className={styles.delegateToggle}>
          <ToggleSwitch label="Collected by a delegate" checked={isDelegate} onChange={setIsDelegate} />
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
              <Select label="ID type"
                value={delegateIdType}
                onChange={(e) => setDelegateIdType(e.target.value as DelegateIdType)}
              >
                {ID_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </Select>
            </div>
            <Field label="ID number" name="delegate_id_number" required value={delegateIdNumber} onChange={(e) => setDelegateIdNumber(e.target.value)} />
          </>
        )}

        {warehouses.length > 0 && (
          <div>
            <Select label="Warehouse / branch" optional
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              <option value="">Use the note's own warehouse…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
              ))}
            </Select>
          </div>
        )}
        {staff.length > 0 && (
          <>
            <div>
              <Select label="Customer Service Officer" optional
                value={csoId}
                onChange={(e) => setCsoId(e.target.value)}
              >
                <option value="">None</option>
                {staff.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </Select>
            </div>
            <div>
              <Select label="Accounting Officer" optional
                value={accountingOfficerId}
                onChange={(e) => setAccountingOfficerId(e.target.value)}
              >
                <option value="">None</option>
                {staff.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </Select>
            </div>
          </>
        )}

        <Field label="Notes" name="notes" multiline optional placeholder="Any observations about the pickup…" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
    </Modal>
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
      toast.success('Release note re-issued', newNote.reference_number)
      onSuccess(newNote)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not re-issue this release note.')
    } finally {
      setSubmitting(false)
    }
  }

  const storageFees = Number(note.storage_fees_ngn ?? 0)
  const expiredDate = formatDate(note.expired_at)

  return (
    <Modal
      open
      onClose={onCancel}
      title="Re-issue release note"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} onClick={() => void handleReissue()}>
            Re-issue release note
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error" title="Action failed">{error}</Banner>}
        <Banner variant="warning" title="Outstanding storage fees">
          {storageFees > 0
            ? `This release note has ${formatNgn(storageFees)} in outstanding storage fees. The new note will carry this balance forward.`
            : 'No outstanding storage fees on this release note.'}
        </Banner>
        <p className={styles.mutedNote}>
          A new release note will be created with the same carton tags and a fresh 14-day window.
          The expired note ({note.reference_number}, expired {expiredDate}) will be preserved for audit purposes.
        </p>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// SendPickupCodeModal — a fresh pickup code for the customer (audit UX-09)
// ---------------------------------------------------------------------------

interface SendPickupCodeModalProps {
  note: ReleaseNote
  onCancel: () => void
  onSent: (sentVia: string[]) => void
}

function SendPickupCodeModal({ note, onCancel, onSent }: SendPickupCodeModalProps): JSX.Element {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const result = await releaseNotesApi.sendPickupCode(note.id)
      onSent(result.sent_via)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send a new pickup code.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      title="Send a new pickup code"
      size="sm"
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} onClick={() => void handleSend()}>Send new code</Button>
        </>
      }
    >
      {error && <div className={styles.modalBanner}><Banner variant="error" title="Not sent">{error}</Banner></div>}
      <p className={styles.flushParagraph}>
        {note.customer_name ?? 'The customer'} will be sent a new code for <Mono>{note.reference_number}</Mono> by SMS and email.
        {note.pickup_code_required ? ' The code they have now will stop working.' : ''}
        {note.pickup_code_locked ? ' This also unlocks the release note.' : ''}
      </p>
      <p className={styles.pickupHint}>
        Nobody at the company sees the code: it goes only to the customer, who gives it to whoever collects.
      </p>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// SendPickupCodeModal — a fresh pickup code for the customer (audit UX-09)
// ---------------------------------------------------------------------------

interface SendPickupCodeModalProps {
  note: ReleaseNote
  onCancel: () => void
  onSent: (sentVia: string[]) => void
}

function SendPickupCodeModal({ note, onCancel, onSent }: SendPickupCodeModalProps): JSX.Element {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSend(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const result = await releaseNotesApi.sendPickupCode(note.id)
      onSent(result.sent_via)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send a new pickup code.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      title="Send a new pickup code"
      width={480}
      onClose={onCancel}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} onClick={() => void handleSend()}>Send new code</Button>
        </>
      }
    >
      {error && <div className={styles.modalBanner}><Banner variant="error" title="Not sent">{error}</Banner></div>}
      <p className={styles.flushParagraph}>
        {note.customer_name ?? 'The customer'} will be sent a new code for <Mono>{note.reference_number}</Mono> by SMS and email.
        {note.pickup_code_required ? ' The code they have now will stop working.' : ''}
        {note.pickup_code_locked ? ' This also unlocks the release note.' : ''}
      </p>
      <p className={styles.pickupHint}>
        Nobody at the company sees the code: it goes only to the customer, who gives it to whoever collects.
      </p>
    </Modal>
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
      toast.success('Release note split', child.reference_number)
      onSuccess(child)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not split release note.')
    } finally {
      setSubmitting(false)
    }
  }

  const allSelected = note.carton_tags.length > 0 && selected.size >= note.carton_tags.length
  const canSplitSubmit = selected.size > 0 && selected.size < note.carton_tags.length && !submitting

  return (
    <Modal
      open
      onClose={onCancel}
      title="Split release note"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSplitSubmit} onClick={() => void handleSubmit()}>
            Create child note
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error" title="Action failed">{error}</Banner>}
        <p className={styles.splitInstruction}>
          Select the carton tags to move into a new child release note. At least one tag must stay on this note.
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
        {allSelected ? (
          <Banner variant="warning">
            Leave at least one carton tag on the original release note so both notes remain valid.
          </Banner>
        ) : selected.size > 0 ? (
          <p className={styles.splitCount}>{plural(selected.size, 'carton')} selected for the new note</p>
        ) : null}
        <Field label="Notes" name="split_notes" multiline optional placeholder="Reason for splitting…" value={splitNotes} onChange={(e) => setSplitNotes(e.target.value)} />
      </div>
    </Modal>
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
  const { data: note = null, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: releaseNoteKeys.detail(id ?? ''),
    queryFn: () => releaseNotesApi.get(id!),
    enabled: !!id,
    ...(stateNote ? { placeholderData: stateNote } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(note?.reference_number)

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load this release note.'
    : null

  const [showPickup, setShowPickup] = useState(false)
  const [showSplit, setShowSplit] = useState(false)
  const [showReissue, setShowReissue] = useState(false)
  const [showSendCode, setShowSendCode] = useState(false)
  const [pickupResult, setPickupResult] = useState<PickupResult | null>(null)
  const [splitChild, setSplitChild] = useState<ReleaseNote | null>(null)


  if (loading && !note) return <PageSkeleton kind="detail" label="Loading release note" />
  if (error && !note) {
    return (
      <>
        <PageHeader title="Release note" />
        <ErrorState title="Couldn't load this release note" error={loadError} message="We couldn't find this record. It may have been removed, or the link is out of date." onRetry={() => void refetch()} />
      </>
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
    <>
      <DetailPage
        header={
          <PageHeader
            title={`Release note ${note.reference_number}`}
            status={
              <>
                <StatusBadge kind="releaseNote" status={note.status} />
                {note.is_partial_release && <Badge variant="warning">Partial</Badge>}
              </>
            }
            meta={[
              note.customer_name,
              note.container_number && <Mono>{note.container_number}</Mono>,
              `Issued ${formatDate(note.authorized_at)}`,
              note.valid_until && !isExpired && `Valid until ${formatDate(note.valid_until)}`,
            ]}
            primary={
              isExpired ? (
                <Action variant="primary" icon="refresh" onClick={() => setShowReissue(true)}>
                  Re-issue release note
                </Action>
              ) : !isTerminal && showPickupBtn ? (
                <Action variant="primary" icon="check" onClick={() => setShowPickup(true)}>
                  Record pickup
                </Action>
              ) : null
            }
            actions={
              <>
                {canSendPickupCode(note, r) && (
                  <Action variant="secondary" icon="refresh" onClick={() => setShowSendCode(true)}>
                    {note.pickup_code_required ? 'Send new pickup code' : 'Send pickup code'}
                  </Action>
                )}
                <ExportButton formats={['pdf']} onExport={() => releaseNotesApi.pdf(note.id)} />
              </>
            }
            more={
              !isTerminal && !isExpired && showSplitBtn && note.carton_tags.length > 1
                ? [{ label: 'Split note', mutates: true, onSelect: () => setShowSplit(true) }]
                : []
            }
            moreLabel="More release note actions"
          />
        }
        notices={
          <>
            {isExpired && (
              <Banner variant="error" title={`Release note expired on ${formatDate(note.expired_at)}`}>
                The customer cannot collect their goods until a new release note is issued.
                {storageFees > 0
                  ? ` ${formatNgn(storageFees)} in outstanding storage fees will carry forward to the re-issued note.`
                  : ' Goods remaining past the release window may accrue storage fees — re-issue and notify the customer.'}
              </Banner>
            )}
            {note.pickup_code_locked && note.status === 'active' && (
              <Banner variant="error" title="Pickup code locked">
                Too many wrong pickup codes were entered at the warehouse, so these goods cannot be
                released. Check with the customer, then send them a new code.
              </Banner>
            )}
            {splitChild && (
              <Banner variant="success" title="Child release note created" dismissible onDismiss={() => setSplitChild(null)}>
                Moved selected cartons to{' '}
                <RecordLink to={`/release-notes/${splitChild.id}`}>
                  <Mono>{splitChild.reference_number}</Mono>
                </RecordLink>
                .
              </Banner>
            )}
            {pickupResult && (
              <Banner variant="success" title="Pickup recorded">
                {pickupResult.remaining_cartons > 0
                  ? `${plural(pickupResult.remaining_cartons, 'carton')} still to collect on this note.`
                  : 'All cartons on this note have been collected.'}
                {pickupResult.shipment_status === 'picked_up' &&
                  ' All customer cartons are now picked up — shipment tracking updated.'}
              </Banner>
            )}
          </>
        }
        // The figures looked for first; customer, container, reference and issue date are in the header (FD-19).
        aside={
          <Section title="Summary">
            <Kvp
              label="Cartons on this note"
              value={
                note.package_unit ? (
                  <Mono>
                    {note.packages_released} of {note.total_cartons_for_customer}{' '}
                    {note.package_unit}
                  </Mono>
                ) : (
                  <Mono>
                    {note.carton_count} of {note.total_cartons_for_customer}
                  </Mono>
                )
              }
            />
            {note.packages_balance != null && note.packages_balance > 0 && (
              <Kvp label="Still to release" value={<Mono>{note.packages_balance}</Mono>} />
            )}
            <Kvp
              label="Payment"
              value={<StatusBadge kind="invoice" status={note.payment_status} />}
            />
            {(Number(note.amount_paid_ngn) > 0 || Number(note.balance_ngn) > 0) && (
              <Kvp
                label="Paid"
                value={`${formatNgn(note.amount_paid_ngn)} of ${formatNgn(note.total_ngn)}, ${formatNgn(note.balance_ngn)} outstanding`}
              />
            )}
            {isExpired && storageFees > 0 && (
              <Kvp label="Storage fees" value={formatNgn(storageFees)} />
            )}
            {note.debt_due_date && (
              <Kvp
                label="Debt payment due"
                value={formatDate(note.debt_due_date)}
                divider={false}
              />
            )}
          </Section>
        }
      >
        <Section title="Release details">
          <Kvp label="Type" value={releaseTypeLabel(note)} />
          <Kvp
            optional
            label="Physical document no."
            value={note.physical_document_number && <Mono>{note.physical_document_number}</Mono>}
          />
          {note.packing_list_invoice_numbers.length > 0 && (
            <Kvp
              label={
                note.packing_list_invoice_numbers.length === 1
                  ? 'Packing list invoice'
                  : 'Packing list invoices'
              }
              value={note.packing_list_invoice_numbers.join(', ')}
            />
          )}
          <Kvp
            optional
            label="Warehouse"
            value={
              note.warehouse_name &&
              `${note.warehouse_name}${note.warehouse_address ? `, ${note.warehouse_address}` : ''}`
            }
          />
          {note.is_on_credit && (
            <Kvp
              label="On credit"
              value={`Yes${note.credit_granted_by_name ? `, granted by ${note.credit_granted_by_name}` : ''}`}
            />
          )}
          <Kvp
            optional
            label="Receipt no."
            value={note.receipt_number && <Mono>{note.receipt_number}</Mono>}
            divider={Boolean(note.parent_release_note_id)}
          />
          {note.parent_release_note_id && (
            <Kvp
              label="Parent release note"
              divider={false}
              value={
                <RecordLink to={`/release-notes/${note.parent_release_note_id}`}>
                  View original note
                </RecordLink>
              }
            />
          )}
        </Section>
        <Section
          title="Carton tags"
          sub={`${plural(note.carton_tags.length, 'tag')} on this release note`}
        >
          {note.carton_tags.length > 0 ? (
            <div className={styles.tagGrid}>
              {note.carton_tags.map((tag) => (
                <span key={tag} className={styles.tag}>
                  {tag}
                </span>
              ))}
            </div>
          ) : (
            <span className={styles.mutedText}>No carton tags recorded.</span>
          )}
        </Section>
      </DetailPage>
      {/* Modals */}
      {showPickup && (
        <RecordPickupModal
          note={note}
          onCancel={() => setShowPickup(false)}
          onSuccess={(result) => {
            setShowPickup(false)
            setPickupResult(result)
            if (result.release_note_status !== note.status) {
              qc.setQueryData(releaseNoteKeys.detail(id ?? ''), {
                ...note,
                status: result.release_note_status,
              })
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
          onSuccess={(child) => {
            setShowSplit(false)
            setSplitChild(child)
            // releaseNoteKeys.detail(id) is a child of releaseNoteKeys.all, so
            // this one invalidation now refreshes this page as well as the list
            // — the explicit reload it replaced is redundant.
            void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
          }}
        />
      )}
      {showSendCode && (
        <SendPickupCodeModal
          note={note}
          onCancel={() => setShowSendCode(false)}
          onSent={(sentVia) => {
            setShowSendCode(false)
            toast.success(
              'New pickup code sent',
              `Sent to the customer by ${sentViaLabel(sentVia)}. Any earlier code no longer works.`,
            )
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
    </>
  )
}
