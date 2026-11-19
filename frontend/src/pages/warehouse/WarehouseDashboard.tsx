/**
 * Warehouse attendant dashboard — speed-optimised for high-frequency pickup
 * recording on the warehouse floor (tablet / mobile use case).
 *
 * Design rules (from 07_domain_modules.md cross-domain UX conventions):
 *  - Minimum touch target 44×44px
 *  - Input font-size ≥ 16px (prevents iOS auto-zoom)
 *  - Card layout, not table (collapses better on narrow screens)
 *  - Modal goes to full-screen on narrow viewports
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, type ListResponse } from '../../api/client'
import { releaseNotesApi, type DelegateIdType, type PickupResult, type ReleaseNote, type RecordPickupInput } from '../../api/releaseNotes'
import { releaseNoteKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { Banner, Button, Field, Icon, Mono, PhoneField, StatCard, ToggleSwitch, DialogGuard } from '../../design/components'
import styles from './WarehouseDashboard.module.css'
import { todayIso } from '../../lib/format'

// ---------------------------------------------------------------------------
// Urgency helpers (P2-2) — prototype §9.3 sorts the queue by age and flags
// notes older than 24h. Derived from authorized_at; no backend field needed.
// ---------------------------------------------------------------------------

const URGENT_AGE_MS = 24 * 60 * 60 * 1000

type Urgency = 'urgent' | 'normal' | 'new'

function noteAgeMs(note: ReleaseNote): number {
  return Date.now() - new Date(note.authorized_at).getTime()
}

function urgencyOf(note: ReleaseNote): Urgency {
  const age = noteAgeMs(note)
  if (age > URGENT_AGE_MS) return 'urgent'
  if (age > 4 * 60 * 60 * 1000) return 'normal'
  return 'new'
}

function ageLabel(note: ReleaseNote): string {
  const mins = Math.round(noteAgeMs(note) / 60000)
  if (mins < 60) return `${Math.max(mins, 1)}min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 48) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

function isToday(iso: string | null | undefined): boolean {
  return !!iso && todayIso(new Date(iso)) === todayIso()
}

// ---------------------------------------------------------------------------
// Inline pickup modal — same logic as ReleaseNoteDetail but full-screen sheet
// ---------------------------------------------------------------------------

interface PickupSheetProps {
  note: ReleaseNote
  onCancel: () => void
  onSuccess: (result: PickupResult) => void
}

const ID_TYPES: { value: DelegateIdType; label: string }[] = [
  { value: 'national_id', label: 'National ID' },
  { value: 'drivers_license', label: "Driver's licence" },
  { value: 'passport', label: 'Passport' },
]

function PickupSheet({ note, onCancel, onSuccess }: PickupSheetProps): JSX.Element {
  const [cartons, setCartons] = useState(String(note.carton_count))
  const [isDelegate, setIsDelegate] = useState(false)
  // The backend requires a collector's name when it is not a delegate; this sheet never sent one, so every
  // in-person pickup recorded here was refused with a validation error. Defaults to the customer, who usually collects.
  const [collectedByName, setCollectedByName] = useState(note.customer_name ?? '')
  const [pickupCode, setPickupCode] = useState('')
  const [delegateName, setDelegateName] = useState('')
  const [delegatePhone, setDelegatePhone] = useState('')
  const [delegateIdType, setDelegateIdType] = useState<DelegateIdType>('national_id')
  const [delegateIdNumber, setDelegateIdNumber] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const delegateFilled = !isDelegate || (
    delegateName.trim() && delegatePhone.trim() && delegateIdNumber.trim()
  )
  const collectorNamed = isDelegate || collectedByName.trim().length > 0
  const codeRequired = note.pickup_code_required === true
  const codeLocked = note.pickup_code_locked === true
  const codeGiven = !codeRequired || pickupCode.trim().length > 0
  const canSubmit = Number(cartons) > 0 && delegateFilled && collectorNamed && codeGiven && !codeLocked && !submitting

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
      if (codeRequired) body.pickup_code = pickupCode.trim()
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
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div>
          <h3 className={styles.modalTitle}>{note.customer_name ?? 'Pickup'}</h3>
          <span className={styles.modalRef}>{note.reference_number}</span>
        </div>

        {error && <div className={styles.modalBanner}><Banner variant="error">{error}</Banner></div>}
        {codeLocked && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Pickup code locked">
              Too many wrong codes were entered. The office must send the customer a new code before these goods can be released.
            </Banner>
          </div>
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
          <span>Delegate pickup</span>
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
              <label style={{ fontSize: 'var(--text-lg)', fontWeight: 600, display: 'block', marginBottom: 'var(--space-2)' }}>
                ID type <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <select
                style={{ width: '100%', padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-line-soft)', background: 'var(--color-surface)', fontSize: 'var(--text-lg)' }}
                value={delegateIdType}
                onChange={(e) => setDelegateIdType(e.target.value as DelegateIdType)}
              >
                {ID_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <Field label="ID number" name="delegate_id_number" required value={delegateIdNumber} onChange={(e) => setDelegateIdNumber(e.target.value)} />
          </>
        )}

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
// Release note card — one card per active note in the queue
// ---------------------------------------------------------------------------

interface NoteCardProps {
  note: ReleaseNote
  onPickup: (note: ReleaseNote) => void
  lastPickup: PickupResult | null
}

const URGENCY_STYLE: Record<Urgency, { label: string; bg: string; fg: string }> = {
  urgent: { label: 'Urgent', bg: 'var(--color-error-soft)', fg: 'var(--color-error)' },
  normal: { label: 'Normal', bg: 'var(--color-warning-soft)', fg: 'var(--color-warning)' },
  new: { label: 'New', bg: 'var(--color-success-soft)', fg: 'var(--color-success)' },
}

function NoteCard({ note, onPickup, lastPickup }: NoteCardProps): JSX.Element {
  const justDone = lastPickup?.release_note_id === note.id && lastPickup.release_note_status === 'picked_up'
  const urgency = URGENCY_STYLE[urgencyOf(note)]
  return (
    <div className={styles.card} style={justDone ? { opacity: 0.5 } : undefined}>
      <div className={styles.cardLeft}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <span
            style={{
              fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)',
              padding: 'var(--space-0-5) var(--space-2)', borderRadius: 'var(--radius-full)', background: urgency.bg, color: urgency.fg,
            }}
          >
            {urgency.label}
          </span>
          <div className={styles.cardRef}>{note.reference_number}</div>
        </div>
        <div className={styles.cardCustomer}>{note.customer_name ?? '—'}</div>
        <div className={styles.cardMeta}>
          {note.container_number && <Mono>{note.container_number}</Mono>}
          <span>{note.carton_count} carton(s)</span>
          {note.is_partial_release && <span>· Partial</span>}
          <span style={{ fontStyle: 'italic', color: 'var(--color-ink-4)' }}>{ageLabel(note)}</span>
        </div>
        {note.carton_tags.length > 0 && (
          <div className={styles.cardTags}>
            {note.carton_tags.slice(0, 6).map((tag) => (
              <span key={tag} className={styles.tag}>{tag}</span>
            ))}
            {note.carton_tags.length > 6 && (
              <span className={styles.tag}>+{note.carton_tags.length - 6}</span>
            )}
          </div>
        )}
      </div>
      <div className={styles.cardRight}>
        {justDone ? (
          <span style={{ color: 'var(--color-success)', fontWeight: 700 }}>✓ Done</span>
        ) : (
          <Button
            variant="success"
            className={styles.pickupBtn}
            onClick={() => onPickup(note)}
          >
            Record pickup
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function WarehouseDashboard(): JSX.Element {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [pickingNote, setPickingNote] = useState<ReleaseNote | null>(null)
  const [lastPickup, setLastPickup] = useState<PickupResult | null>(null)
  const [lookupRef, setLookupRef] = useState('')
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [lookupBusy, setLookupBusy] = useState(false)

  // Queue + real completed-today count + expired backlog, still in parallel
  // (P2-2) but as three cached queries rather than one Promise.all in an
  // effect, so each status list shares a cache slot with the release-note list
  // screens and a pickup elsewhere refreshes this dashboard.
  const ACTIVE_PARAMS = { status: 'active' as const }
  const PICKED_UP_PARAMS = { status: 'picked_up' as const, limit: 50 }
  const EXPIRED_PARAMS = { status: 'expired' as const, limit: 50 }

  const activeQ = useQuery({
    queryKey: releaseNoteKeys.lookup(ACTIVE_PARAMS),
    queryFn: () => releaseNotesApi.list(ACTIVE_PARAMS),
    staleTime: STALE_30S,
  })
  const pickedUpQ = useQuery({
    queryKey: releaseNoteKeys.lookup(PICKED_UP_PARAMS),
    queryFn: () => releaseNotesApi.list(PICKED_UP_PARAMS),
    staleTime: STALE_30S,
  })
  const expiredQ = useQuery({
    queryKey: releaseNoteKeys.lookup(EXPIRED_PARAMS),
    queryFn: () => releaseNotesApi.list(EXPIRED_PARAMS),
    staleTime: STALE_30S,
  })

  const loading = activeQ.isLoading || pickedUpQ.isLoading || expiredQ.isLoading
  const firstError = activeQ.error ?? pickedUpQ.error ?? expiredQ.error
  const error = firstError
    ? firstError instanceof ApiError
      ? firstError.message
      : 'Could not load release notes.'
    : null

  // Oldest first — urgency order, matching the prototype queue.
  const activeNotes = useMemo(
    () => [...(activeQ.data?.data ?? [])].sort((a, b) => a.authorized_at.localeCompare(b.authorized_at)),
    [activeQ.data],
  )
  const doneToday = pickedUpQ.data ? pickedUpQ.data.data.filter((n) => isToday(n.picked_up_at)).length : null
  const expiredCount = expiredQ.data
    ? expiredQ.data.meta.pagination.has_more
      ? `${expiredQ.data.data.length}+`
      : String(expiredQ.data.data.length)
    : null

  function handlePickupSuccess(result: PickupResult): void {
    setPickingNote(null)
    setLastPickup(result)
    if (result.release_note_status === 'picked_up') {
      // Drop the fully-collected note from the queue after a short delay so
      // staff sees the ✓ first. Written into the cache rather than local state;
      // the pickup POST has already triggered an invalidation of
      // releaseNoteKeys.all, so the server's own view lands shortly after and
      // reconciles either way.
      setTimeout(() => {
        qc.setQueryData<ListResponse<ReleaseNote>>(releaseNoteKeys.list(ACTIVE_PARAMS), (prev) =>
          prev
            ? { ...prev, data: prev.data.filter((n) => n.id !== result.release_note_id) }
            : prev,
        )
        setLastPickup(null)
      }, 2000)
    }
  }

  // Scan-or-type lookup (P2-2): handheld scanners act as keyboards, so a text
  // input covers both. Active notes open the pickup sheet directly; anything
  // else (picked_up / expired) opens the detail page for context.
  async function handleLookup(): Promise<void> {
    const ref = lookupRef.trim().toUpperCase()
    if (!ref) return
    setLookupError(null)
    const local = activeNotes.find((n) => n.reference_number.toUpperCase() === ref)
    if (local) {
      setLookupRef('')
      setPickingNote(local)
      return
    }
    setLookupBusy(true)
    try {
      const result = await releaseNotesApi.list({ reference: ref })
      const found = result.data[0]
      if (found) {
        navigate(`/release-notes/${found.id}`)
      } else {
        setLookupError(`No release note found for "${ref}".`)
      }
    } catch (err) {
      setLookupError(err instanceof ApiError ? err.message : 'Lookup failed — try again.')
    } finally {
      setLookupBusy(false)
    }
  }

  const urgentCount = activeNotes.filter((n) => urgencyOf(n) === 'urgent').length

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Warehouse</h1>
        <p className={styles.subtitle}>Active release notes to process today</p>
      </div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {/* Scan-or-type lookup block (P2-2, prototype §9.3 centrepiece) */}
      <div className={styles.scanBlock}>
        <div className={styles.scanIcon}>
          <Icon name="qr" size={40} stroke={2} />
        </div>
        <div className={styles.scanBody}>
          <h3 className={styles.scanTitle}>Scan or type a release note reference</h3>
          <p className={styles.scanSub}>
            Use the handheld scanner or type the RN-XXXX reference on the customer&apos;s release note.
          </p>
          <div className={styles.scanRow}>
            <input
              className={styles.scanInput}
              placeholder="RN-20260716-ABC123"
              aria-label="Release note reference"
              value={lookupRef}
              onChange={(e) => { setLookupRef(e.target.value); setLookupError(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleLookup() }}
            />
            <Button variant="primary" icon="arrowright" loading={lookupBusy} disabled={!lookupRef.trim()} onClick={() => void handleLookup()}>
              Look up
            </Button>
          </div>
          {lookupError && <div className={styles.scanError}>{lookupError}</div>}
        </div>
      </div>

      <div className={styles.statsRow}>
        <StatCard
          label="Awaiting pickup"
          value={activeNotes.length}
          sublabel={urgentCount > 0 ? `${urgentCount} urgent · 24h+ old` : 'none urgent'}
        />
        <StatCard label="Completed today" value={doneToday ?? '—'} />
        <StatCard
          label="Expired · not collected"
          value={expiredCount ?? '—'}
          sublabel={expiredCount && expiredCount !== '0' ? 'contact the customer' : 'all clear'}
        />
      </div>

      {lastPickup && lastPickup.release_note_status !== 'picked_up' && (
        <div className={styles.banner}>
          <Banner variant="info">
            {lastPickup.remaining_cartons} carton(s) still pending on this note.
          </Banner>
        </div>
      )}

      <div className={styles.queueHead}>
        <span className={styles.queueLabel}>Queue</span>
        <span className={styles.queueCount}>{activeNotes.length} note(s)</span>
      </div>

      {loading && <div style={{ padding: 'var(--space-8)', textAlign: 'center', color: 'var(--color-ink-4)' }}>Loading…</div>}

      {!loading && activeNotes.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>✓</div>
          <p className={styles.emptyTitle}>All clear!</p>
          <p>No active release notes to process.</p>
        </div>
      )}

      {activeNotes.map((note) => (
        <NoteCard
          key={note.id}
          note={note}
          onPickup={setPickingNote}
          lastPickup={lastPickup}
        />
      ))}

      {pickingNote && (
        <PickupSheet
          note={pickingNote}
          onCancel={() => setPickingNote(null)}
          onSuccess={handlePickupSuccess}
        />
      )}
    </div>
  )
}
