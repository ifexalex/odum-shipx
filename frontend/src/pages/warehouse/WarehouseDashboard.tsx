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
import { useEffect, useMemo, useRef, useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, type ListResponse } from '../../api/client'
import { releaseNotesApi, type DelegateIdType, type PickupResult, type ReleaseNote, type RecordPickupInput } from '../../api/releaseNotes'
import { releaseNoteKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { Banner, Button, EmptyState, Field, Icon, Mono, PhoneField, StatCard, ToggleSwitch, DialogGuard, Badge, Select, LinesSkeleton } from '../../design/components'
import styles from './WarehouseDashboard.module.css'
import { plural, todayIso } from '../../lib/format'
import { toast } from '../../design/toast'
import { PageHeader } from '../../shell/PageHeader'

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
  const maxCartons = note.packages_balance != null && note.packages_balance > 0
    ? note.packages_balance
    : note.carton_count
  const [cartons, setCartons] = useState(String(maxCartons))
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
  const pickupCodeRef = useRef<HTMLInputElement>(null)
  const cartonsRef = useRef<HTMLInputElement>(null)

  const cartonsNum = Number(cartons)
  const cartonsValid = cartons.trim().length > 0 && Number.isInteger(cartonsNum) && cartonsNum >= 1 && cartonsNum <= maxCartons
  const cartonsError = cartons.trim().length === 0 || cartonsValid
    ? undefined
    : cartonsNum > maxCartons
      ? `Cannot exceed ${plural(maxCartons, 'remaining carton')}.`
      : 'Enter a whole number of at least 1.'

  const delegateFilled = !isDelegate || (
    delegateName.trim() && delegatePhone.trim() && delegateIdNumber.trim()
  )
  const collectorNamed = isDelegate || collectedByName.trim().length > 0
  const codeRequired = note.pickup_code_required === true
  const codeLocked = note.pickup_code_locked === true
  const codeGiven = !codeRequired || pickupCode.trim().length > 0
  const canSubmit = cartonsValid && delegateFilled && collectorNamed && codeGiven && !codeLocked && !submitting

  // Focus the primary input after DialogGuard mounts (and after React StrictMode effect replays),
  // so pressing Enter submits the pickup form rather than activating the header "View full note" link.
  useEffect(() => {
    if (codeRequired && !codeLocked) {
      pickupCodeRef.current?.focus()
    } else {
      cartonsRef.current?.focus()
    }
  }, [codeRequired, codeLocked])

  async function handleSubmit(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault()
    // Enter submits the form (FD-26: a keyboard-only pickup), so the same checks as the button apply.
    if (!canSubmit) return
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
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <form
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => void handleSubmit(e)}
        role="dialog"
        aria-modal="true"
      >
        <div className={styles.modalHeaderRow}>
          <div>
            <h3 className={styles.modalTitle}>{note.customer_name ?? 'Pickup'}</h3>
            <div className={styles.modalMeta}>
              <span className={styles.modalRef}>{note.reference_number}</span>
              {note.container_number && (
                <>
                  <span>·</span>
                  <Mono>{note.container_number}</Mono>
                </>
              )}
            </div>
          </div>
          <Link to={`/release-notes/${note.id}`} className={styles.modalDetailLink} onClick={onCancel}>
            View full note
          </Link>
        </div>

        {note.carton_tags.length > 0 && (
          <div className={styles.modalTagsBox}>
            <div className={styles.modalTagsLabel}>Carton tags to verify ({note.carton_tags.length})</div>
            <div className={styles.cardTags}>
              {note.carton_tags.slice(0, 12).map((tag) => (
                <span key={tag} className={styles.tag}>{tag}</span>
              ))}
              {note.carton_tags.length > 12 && (
                <span className={styles.tag}>+{note.carton_tags.length - 12} more</span>
              )}
            </div>
          </div>
        )}

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
            // The first thing to ask the collector, so the sheet opens on it.
            ref={pickupCodeRef}
            autoFocus
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

        <div>
          <Field
            ref={cartonsRef}
            autoFocus={!codeRequired || codeLocked}
            label="Cartons collected"
            name="cartons_released"
            required
            type="number"
            min="1"
            max={String(maxCartons)}
            step="1"
            value={cartons}
            onChange={(e) => setCartons(e.target.value)}
            error={cartonsError}
            helper={maxCartons > 1 ? `Up to ${plural(maxCartons, 'carton')} remaining on this note.` : undefined}
          />
          {maxCartons > 1 && (
            <div className={styles.quickSetRow}>
              <Button
                type="button"
                variant={cartonsNum === maxCartons ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setCartons(String(maxCartons))}
              >
                Full release ({maxCartons})
              </Button>
              <Button
                type="button"
                variant={cartonsValid && cartonsNum < maxCartons ? 'secondary' : 'ghost'}
                size="sm"
                onClick={() => setCartons(String(Math.max(1, maxCartons - 1)))}
              >
                Partial
              </Button>
            </div>
          )}
        </div>

        <label className={styles.delegateToggle}>
          <ToggleSwitch label="Delegate pickup" checked={isDelegate} onChange={setIsDelegate} />
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

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button type="submit" variant="primary" loading={submitting} disabled={!canSubmit}>
            Confirm pickup
          </Button>
        </div>
      </form>
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

// A chip only on a note waiting more than a day (FD-08, FD-26): a chip on every card, "Normal" or "New", is noise
// and hides the ones that matter.

function NoteCard({ note, onPickup, lastPickup }: NoteCardProps): JSX.Element {
  const justDone = lastPickup?.release_note_id === note.id && lastPickup.release_note_status === 'picked_up'
  const urgent = urgencyOf(note) === 'urgent'
  return (
    <div className={styles.card} style={justDone ? { opacity: 0.5 } : undefined}>
      <div className={styles.cardLeft}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {urgent && (
            <Badge variant="error" size="sm">
              Waiting 24h+
            </Badge>
          )}
          <div className={styles.cardRef}>{note.reference_number}</div>
        </div>
        <div className={styles.cardCustomer}>{note.customer_name ?? '—'}</div>
        <div className={styles.cardMeta}>
          {note.container_number && <Mono>{note.container_number}</Mono>}
          <span>{plural(note.carton_count, 'carton')}</span>
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
          // Secondary: the page's one primary is the lookup, which a scanner drives (FD-26).
          <Button variant="secondary" size="lg" className={styles.pickupBtn} onClick={() => onPickup(note)}>
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
  const [urgentOnly, setUrgentOnly] = useState(false)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [lookupBusy, setLookupBusy] = useState(false)
  // The counter works from a scanner (FD-26): the reference field has focus on arrival and after every pickup, so
  // the next customer's note is scanned with no click.
  const lookupField = useRef<HTMLInputElement>(null)
  const [refocusLookup, setRefocusLookup] = useState(0)
  useEffect(() => {
    lookupField.current?.focus()
  }, [refocusLookup])

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

  // The queue waits only on its own list; the counts fill in as theirs arrive.
  const loading = activeQ.isLoading
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
  const trimmedQuery = lookupRef.trim().toLowerCase()
  const visibleNotes = useMemo(
    () =>
      activeNotes.filter((n) => {
        if (urgentOnly && urgencyOf(n) !== 'urgent') return false
        if (!trimmedQuery) return true
        return (
          n.reference_number.toLowerCase().includes(trimmedQuery) ||
          (n.customer_name?.toLowerCase().includes(trimmedQuery) ?? false) ||
          (n.container_number?.toLowerCase().includes(trimmedQuery) ?? false)
        )
      }),
    [activeNotes, urgentOnly, trimmedQuery],
  )
  const isFiltered = urgentOnly || trimmedQuery.length > 0
  const doneToday = pickedUpQ.data ? pickedUpQ.data.data.filter((n) => isToday(n.picked_up_at)).length : null
  const expiredCount = expiredQ.data
    ? expiredQ.data.meta.pagination.has_more
      ? `${expiredQ.data.data.length}+`
      : String(expiredQ.data.data.length)
    : null

  function handlePickupSuccess(result: PickupResult): void {
    setPickingNote(null)
    setLastPickup(result)
    // After the sheet has closed and handed focus back, take it to the field for the next customer.
    setRefocusLookup((n) => n + 1)
    void qc.invalidateQueries({ queryKey: releaseNoteKeys.all })
    if (result.release_note_status === 'picked_up') {
      // Drop the fully-collected note from the queue after a short delay so
      // staff sees the ✓ first. Written into the lookup cache slot used by
      // activeQ while the invalidation above reconciles with the server.
      setTimeout(() => {
        qc.setQueryData<ListResponse<ReleaseNote>>(releaseNoteKeys.lookup(ACTIVE_PARAMS), (prev) =>
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
    if (!ref) {
      // Never a disabled button (it was unreadable on the panel): an empty lookup says what is needed instead.
      setLookupError('Scan or type a release note reference first.')
      lookupField.current?.focus()
      return
    }
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
      {/* Not "Warehouse" again: the role badge and the nav item already say where this is (FD-26). */}
      <PageHeader title="Pickups" meta="Scan a customer's release note to record what they collect." />

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
          <div className={styles.scanRow}>
            <Field
              ref={lookupField}
              label="Release note reference"
              name="release_note_reference"
              className={styles.scanField}
              placeholder="RN-20260716-ABC123 or customer name"
              value={lookupRef}
              onChange={(e) => { setLookupRef(e.target.value); setLookupError(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleLookup() }}
            />
            <Button variant="primary" size="lg" trailingIcon="arrowright" loading={lookupBusy} onClick={() => void handleLookup()}>
              Look up
            </Button>
          </div>
          <p className={styles.scanSub}>Scan a release note or type a reference, customer name, or container to filter; press Enter to look up.</p>
          {lookupError && (
            <div className={styles.scanError} role="alert">
              {lookupError}
            </div>
          )}
        </div>
      </div>

      <div className={styles.statsRow}>
        <StatCard
          label="Awaiting pickup"
          value={activeQ.data ? activeNotes.length : '—'}
          sublabel={activeQ.data ? (urgentCount > 0 ? `${urgentCount} urgent · 24h+ old` : 'none urgent') : undefined}
          selected={urgentOnly}
          onSelect={urgentCount > 0 || urgentOnly ? () => setUrgentOnly((v) => !v) : undefined}
        />
        <StatCard
          label="Completed today"
          value={doneToday ?? '—'}
          sublabel={doneToday !== null ? 'picked up today' : undefined}
          onSelect={() => navigate('/release-notes?status=picked_up')}
        />
        <StatCard
          label="Expired · not collected"
          value={expiredCount ?? '—'}
          sublabel={expiredCount === null ? undefined : expiredCount !== '0' ? 'contact the customer' : 'all clear'}
          onSelect={() => navigate('/release-notes?status=expired')}
        />
      </div>

      {lastPickup && lastPickup.release_note_status !== 'picked_up' && (
        <div className={styles.banner}>
          <Banner variant="info">
            {plural(lastPickup.remaining_cartons, 'carton')} still to collect on this note.
          </Banner>
        </div>
      )}

      <div className={styles.queueHead}>
        <span className={styles.queueLabel}>{urgentOnly ? 'Urgent queue (24h+)' : 'Queue'}</span>
        <div className={styles.queueMeta}>
          <span className={styles.queueCount}>
            {activeQ.data && (
              isFiltered
                ? `${visibleNotes.length} of ${plural(activeNotes.length, 'note')}`
                : plural(activeNotes.length, 'note')
            )}
          </span>
          {isFiltered && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setUrgentOnly(false)
                setLookupRef('')
                setLookupError(null)
              }}
            >
              Clear filter
            </Button>
          )}
        </div>
      </div>

      {loading && <LinesSkeleton label="Loading" />}

      {!loading && activeNotes.length === 0 && (
        <EmptyState
          title="All clear!"
          body="No active release notes to process."
        />
      )}

      {!loading && activeNotes.length > 0 && visibleNotes.length === 0 && (
        <EmptyState
          compact
          title="No matching release notes"
          body="No active notes match the current filter."
          action={{
            label: 'Clear filter',
            onClick: () => {
              setUrgentOnly(false)
              setLookupRef('')
              setLookupError(null)
            },
          }}
        />
      )}

      {visibleNotes.map((note) => (
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
