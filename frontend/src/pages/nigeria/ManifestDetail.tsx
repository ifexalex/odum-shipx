import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { formatCbm } from '../../api/decimal'
import {
  manifestApi,
  orderedPackageMix,
  type DiscrepancyInput,
  type Manifest,
  type ManifestMissingItem,
} from '../../api/manifest'
import { manifestKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { canResolveDiscrepancy, canRevokeVerification, canVerifyManifest } from '../../api/manifestRules'
import { useSession } from '../../auth/useSession'
import { EvidenceUploader } from './EvidenceUploader'
import { Action, Banner, Button, Card, Chip, DialogGuard, ExportButton, Field, Icon, Mono, StatCard, StatusBadge, Table, Select, PageSkeleton, EmptyState, ErrorState } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ManifestDetail.module.css'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// Carton diff helpers
// ---------------------------------------------------------------------------

interface CustomerCartonDiff {
  customer_id: string
  customer_name: string | null
  expected: number
  missingTags: string[]
}

function buildCartonDiff(
  customers: Manifest['customers'],
  missingItems: ManifestMissingItem[],
): CustomerCartonDiff[] {
  return customers.map((c) => {
    const customerMissing = missingItems.filter((m) => m.customer_id === c.customer_id)
    const missingTags = customerMissing.flatMap((m) => m.carton_tags)
    return {
      customer_id: c.customer_id,
      customer_name: c.customer_name,
      expected: c.carton_count,
      missingTags,
    }
  })
}

interface DiscrepancyDraft {
  customerId: string
  type: 'missing' | 'damaged'
  cartonTags: string[]
  notes: string
}

function emptyDiscrepancy(): DiscrepancyDraft {
  return { customerId: '', type: 'missing', cartonTags: [], notes: '' }
}

/** Human descriptor stored on the evidence row (customer + type + carton tags). */
function discrepancyLabel(customer: string, draft: DiscrepancyDraft): string {
  const tags = draft.cartonTags.length > 0 ? ` (${draft.cartonTags.join(', ')})` : ''
  return `${draft.type === 'missing' ? 'Missing' : 'Damaged'} — ${customer}${tags}`
}

interface VerifyManifestModalProps {
  manifest: Manifest
  onCancel: () => void
  onVerified: (updated: Manifest) => void
}

function VerifyManifestModal({ manifest, onCancel, onVerified }: VerifyManifestModalProps): JSX.Element {
  const [outcome, setOutcome] = useState<'verified' | 'discrepancies_found'>('verified')
  const [drafts, setDrafts] = useState<DiscrepancyDraft[]>([emptyDiscrepancy()])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function updateDraft(index: number, patch: Partial<DiscrepancyDraft>): void {
    setDrafts((prev) => prev.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)))
  }

  function toggleTag(index: number, tag: string): void {
    setDrafts((prev) =>
      prev.map((draft, i) => {
        if (i !== index) return draft
        const has = draft.cartonTags.includes(tag)
        return { ...draft, cartonTags: has ? draft.cartonTags.filter((t) => t !== tag) : [...draft.cartonTags, tag] }
      }),
    )
  }

  function removeDraft(index: number): void {
    setDrafts((prev) => prev.filter((_, i) => i !== index))
  }

  const validDrafts = drafts.filter((draft) => draft.customerId && draft.cartonTags.length > 0)
  const canSubmit = outcome === 'verified' || validDrafts.length > 0

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const discrepancies: DiscrepancyInput[] | undefined =
        outcome === 'discrepancies_found'
          ? validDrafts.map((draft) => ({
              customer_id: draft.customerId,
              carton_tags: draft.cartonTags,
              type: draft.type,
              notes: draft.notes || undefined,
            }))
          : undefined
      const updated = await manifestApi.verify(manifest.id, { verification_status: outcome, discrepancies })
      toast.success(outcome === 'verified' ? 'Manifest verified' : 'Discrepancies recorded')
      onVerified(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not verify this manifest.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Verify manifest</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}
        <div className={styles.outcomeRow}>
          <Button
            variant={outcome === 'verified' ? 'primary' : 'secondary'}
            icon="check"
            onClick={() => setOutcome('verified')}
          >
            Verified — all items present
          </Button>
          <Button
            variant={outcome === 'discrepancies_found' ? 'danger' : 'secondary'}
            icon="warn"
            onClick={() => setOutcome('discrepancies_found')}
          >
            Discrepancies found
          </Button>
        </div>

        {outcome === 'discrepancies_found' && (
          <div className={styles.discrepancyList}>
            {drafts.map((draft, index) => {
              const customer = manifest.customers.find((c) => c.customer_id === draft.customerId)
              return (
                <div key={index} className={styles.discrepancyCard}>
                  <div className={styles.discrepancyHead}>
                    <div className={styles.selectField}>
                      <Select label="Customer"
                        id={`discrepancyCustomer-${index}`}
                        value={draft.customerId}
                        onChange={(event) => updateDraft(index, { customerId: event.target.value, cartonTags: [] })}
                      >
                        <option value="">Select a customer…</option>
                        {manifest.customers.map((c) => (
                          <option key={c.customer_id} value={c.customer_id}>
                            {c.customer_name ?? c.customer_id}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className={styles.selectField}>
                      <Select label="Type"
                        id={`discrepancyType-${index}`}
                        value={draft.type}
                        onChange={(event) => updateDraft(index, { type: event.target.value as 'missing' | 'damaged' })}
                      >
                        <option value="missing">Missing</option>
                        <option value="damaged">Damaged</option>
                      </Select>
                    </div>
                    {drafts.length > 1 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon="x"
                        aria-label="Remove this discrepancy"
                        onClick={() => removeDraft(index)}
                      />
                    )}
                  </div>
                  {customer && customer.carton_tags.length > 0 && (
                    <div className={styles.tagPicker}>
                      <span className={styles.tagPickerLabel}>Carton tags affected</span>
                      <div className={styles.tagChips}>
                        {customer.carton_tags.map((tag) => (
                          <Chip key={tag} active={draft.cartonTags.includes(tag)} onClick={() => toggleTag(index, tag)}>
                            {tag}
                          </Chip>
                        ))}
                      </div>
                    </div>
                  )}
                  <Field
                    label="Notes"
                    name={`discrepancyNotes-${index}`}
                    optional
                    multiline
                    placeholder="What happened to this carton?"
                    value={draft.notes}
                    onChange={(event) => updateDraft(index, { notes: event.target.value })}
                  />
                  <div className={styles.evidenceField}>
                    <span className={styles.tagPickerLabel}>Photo evidence (optional)</span>
                    <EvidenceUploader
                      getPresignedUrl={(f) =>
                        manifestApi.getEvidenceUploadUrl(
                          manifest.id,
                          f.name,
                          f.type,
                          f.size,
                          discrepancyLabel(customer?.customer_name ?? draft.customerId, draft),
                        )
                      }
                      confirmUpload={(evidenceId) => manifestApi.confirmEvidence(manifest.id, evidenceId)}
                      onUploaded={() => { /* listed on the manifest once confirmed; the confirmUpload POST refreshes it */ }}
                    />
                  </div>
                </div>
              )
            })}
            <Button variant="ghost" size="sm" icon="plus" onClick={() => setDrafts((prev) => [...prev, emptyDiscrepancy()])}>
              Add another
            </Button>
          </div>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon="check"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            Submit verification
          </Button>
        </div>
      </div>
    </div>
  )
}

interface ResolveDiscrepancyModalProps {
  manifest: Manifest
  onCancel: () => void
  onResolved: (updated: Manifest) => void
}

function ResolveDiscrepancyModal({ manifest, onCancel, onResolved }: ResolveDiscrepancyModalProps): JSX.Element {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await manifestApi.resolveDiscrepancy(manifest.id, { resolution_notes: notes })
      toast.success('Discrepancy resolved')
      onResolved(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve this discrepancy.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Resolve discrepancy</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}
        <Field
          label="Resolution notes"
          name="resolutionNotes"
          required
          multiline
          maxLength={1000}
          placeholder="What was found, and how was it resolved?"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon="check"
            loading={submitting}
            disabled={!notes.trim()}
            onClick={() => void handleConfirm()}
          >
            Confirm resolution
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ManifestDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { session } = useSession()
  const qc = useQueryClient()

  const { data: manifest = null, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: manifestKeys.detail(id ?? ''),
    queryFn: () => manifestApi.get(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(manifest?.container_number)

  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load this manifest.'
      : null)

  // Verify/resolve/revoke all return the updated manifest; writing it to the
  // cache keeps this page and the manifest list in step.
  const applyUpdated = (updated: Manifest): void => {
    qc.setQueryData(manifestKeys.detail(id ?? ''), updated)
  }

  const [showVerifyModal, setShowVerifyModal] = useState(false)
  const [showResolveModal, setShowResolveModal] = useState(false)
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)
  const [revoking, setRevoking] = useState(false)


  if (loading && !manifest) return <PageSkeleton kind="detail" label="Loading manifest" />
  if (error && !manifest) {
    return (
      <ErrorState title="Couldn't load this manifest" error={loadError} message="We couldn't find this record. It may have been removed, or the link is out of date." onRetry={() => void refetch()} />
    )
  }
  if (!manifest) return <></>

  const canVerify = session ? canVerifyManifest(manifest, session.role) : false
  const canResolve = session ? canResolveDiscrepancy(manifest, session.role) : false
  const canRevoke = session ? canRevokeVerification(manifest, session.role) : false

  // Package breakdown by unit — a single carton count hides bales/bags/etc.
  const packageMixParts = orderedPackageMix(manifest.package_mix)
  const packageTotal = packageMixParts.reduce((sum, p) => sum + p.qty, 0) || manifest.total_cartons
  const packageMixLabel = packageMixParts.map((p) => `${p.qty} ${p.abbr}`).join(' · ')

  async function handleRevoke(): Promise<void> {
    if (!manifest) return
    setRevoking(true)
    setActionError(null)
    try {
      const updated = await manifestApi.revokeVerification(manifest.id)
      toast.success('Verification revoked')
      applyUpdated(updated)
      setShowRevokeConfirm(false)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not revoke verification.')
      setShowRevokeConfirm(false)
    } finally {
      setRevoking(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={`Manifest ${manifest.container_number ?? ''}`.trim()}
        status={<StatusBadge kind="manifest" status={manifest.verification_status} />}
        meta={[
          `${manifest.total_customers} customers`,
          `${packageTotal} packages${packageMixLabel ? ` (${packageMixLabel})` : ''}`,
          `${formatCbm(manifest.total_cbm)} CBM`,
        ]}
        primary={
          canVerify ? (
            <Action variant="primary" icon="check" onClick={() => setShowVerifyModal(true)}>
              Verify manifest
            </Action>
          ) : canResolve ? (
            <Action variant="primary" icon="check" onClick={() => setShowResolveModal(true)}>
              Resolve discrepancy
            </Action>
          ) : null
        }
        actions={<ExportButton formats={['xlsx', 'csv']} onExport={(fmt) => manifestApi.export(manifest.id, fmt)} />}
        more={
          canRevoke && !revoking
            ? [{ label: 'Revoke verification', tone: 'danger', onSelect: () => setShowRevokeConfirm(true) }]
            : []
        }
        moreLabel="More manifest actions"
      />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Action failed">{error}</Banner>
        </div>
      )}

      {manifest.verification_status === 'pending' && (
        <div className={styles.banner}>
          <Banner variant="warning" title="Verification required before customer billing can be generated">
            Walk the warehouse against this manifest, then mark as Verified — or log discrepancies if anything's
            missing or damaged.
          </Banner>
        </div>
      )}
      {manifest.verification_status === 'discrepancies_found' && (
        <div className={styles.banner}>
          <Banner variant="error" title="Discrepancies logged">
            Missing/damaged item records are tracked separately under Claims. Resolve here once the warehouse
            investigation is complete.
          </Banner>
        </div>
      )}
      {manifest.verification_status === 'resolved' && manifest.notes && (
        <div className={styles.banner}>
          <Banner variant="success" title="Resolved">
            {manifest.notes}
          </Banner>
        </div>
      )}

      <div className={styles.statsRow}>
        <StatCard label="Total customers" value={manifest.total_customers} icon="users" />
        <StatCard label="Packages" value={packageTotal} icon="package" sublabel={packageMixLabel || undefined} />
        <StatCard label="Total CBM" value={formatCbm(manifest.total_cbm)} icon="container" />
        <StatCard label="Total weight" value={`${manifest.total_weight_kg} kg`} icon="package" />
      </div>

      <Card padding="none">
        <div className={styles.itemsHead}>
          <SectionHead
            title="Customers on this manifest"
            sub="Aggregated from approved packing lists for this container"
          />
        </div>
        <Table
          columns={[
            { title: 'Customer' },
            { title: 'Contact' },
            { title: 'Cartons', type: 'number' },
            { title: 'Volume (CBM)', type: 'number' },
            { title: 'Weight (kg)', type: 'number' },
            { title: 'Carton tags', type: 'reference' },
          ]}
          rows={manifest.customers.map((c) => ({
            onOpen: c.packing_list_id ? () => navigate(`/packing-lists/${c.packing_list_id}`) : undefined,
            cells: [
              <span key="name">{c.customer_name ?? c.customer_id}</span>,
              // The paper manifest pairs NAME with CONTACT — staff ring the
              // customer when cargo lands, so keep them adjacent here too.
              c.customer_phone
                ? <Mono key="phone">{c.customer_phone}</Mono>
                : <span key="phone" className={styles.dimText}>—</span>,
              <Mono key="cartons">{c.carton_count}</Mono>,
              <Mono key="cbm">{formatCbm(c.total_cbm)}</Mono>,
              <Mono key="weight">{c.total_weight_kg != null ? `${c.total_weight_kg} kg` : '—'}</Mono>,
              <div key="tags" className={styles.tagChips}>
                {c.carton_tags.slice(0, 3).map((tag) => (
                  <span key={tag} className={styles.tagChip}>
                    {tag}
                  </span>
                ))}
                {c.carton_tags.length > 3 && <span className={styles.tagMore}>+{c.carton_tags.length - 3} more</span>}
              </div>,
            ],
          }))}
          emptyState={<EmptyState compact title="No approved packing lists on this manifest yet" />}
        />
      </Card>

      {/* Carton diff view — expected vs missing per customer */}
      {manifest.missing_items && manifest.missing_items.length > 0 && (
        <div className={styles.discrepancySection}>
          <Card padding="none">
            <div className={styles.itemsHead}>
              <SectionHead
                title="Missing cartons — expected vs. reported"
                sub="Cartons logged as missing during manifest verification"
              />
            </div>
            <Table
              columns={[
                { title: 'Customer' },
                { title: 'Expected', type: 'number' },
                { title: 'Missing', type: 'number' },
                { title: 'Accounted for', type: 'number' },
                { title: 'Missing tags', type: 'reference' },
              ]}
              rows={buildCartonDiff(manifest.customers, manifest.missing_items)
                .filter((d) => d.missingTags.length > 0)
                .map((d) => ({
                  cells: [
                    <span key="name">{d.customer_name ?? d.customer_id}</span>,
                    <Mono key="expected">{d.expected}</Mono>,
                    <Mono key="missing" color="var(--color-error)">{d.missingTags.length}</Mono>,
                    <Mono key="accounted">{d.expected - d.missingTags.length}</Mono>,
                    <div key="tags" className={styles.tagChips}>
                      {d.missingTags.slice(0, 4).map((tag) => (
                        <span key={tag} className={`${styles.tagChip} ${styles.discrepancyRow}`}>
                          {tag}
                        </span>
                      ))}
                      {d.missingTags.length > 4 && (
                        <span className={styles.tagMore}>+{d.missingTags.length - 4} more</span>
                      )}
                    </div>,
                  ],
                }))}
            />
          </Card>
        </div>
      )}

      {manifest.weight_discrepancies && manifest.weight_discrepancies.length > 0 && (
        <div className={styles.discrepancySection}>
          <Card padding="none">
            <div className={styles.itemsHead}>
              <SectionHead
                title="Weight discrepancies"
                sub="Cartons where actual weight differs from dispatch weight by more than 5% or 0.1kg"
              />
            </div>
            <Table
              columns={[
                { title: 'Carton tag', type: 'reference' },
                { title: 'Tracking code', type: 'reference' },
                { title: 'Dispatch (kg)', type: 'number' },
                { title: 'Actual (kg)', type: 'number' },
                { title: 'Difference (kg)', type: 'number' },
              ]}
              rows={manifest.weight_discrepancies.map((wd) => ({
                cells: [
                  <Mono key="tag">{wd.carton_tag ?? '—'}</Mono>,
                  <Mono key="tracking">{wd.tracking_code ?? '—'}</Mono>,
                  <Mono key="dispatch">{wd.weight_dispatch_kg.toFixed(3)}</Mono>,
                  <Mono key="actual">{wd.weight_actual_kg.toFixed(3)}</Mono>,
                  <Mono key="diff" color={wd.difference_kg < 0 ? 'var(--color-error)' : 'var(--color-warning)'}>
                    {wd.difference_kg > 0 ? '+' : ''}
                    {wd.difference_kg.toFixed(3)}
                  </Mono>,
                ],
              }))}
            />
          </Card>
        </div>
      )}

      {manifest.evidence && manifest.evidence.length > 0 && (
        <div className={styles.discrepancySection}>
          <Card padding="none">
            <div className={styles.itemsHead}>
              <SectionHead
                title="Verification evidence"
                sub="Photos and documents attached during manifest verification"
              />
            </div>
            <div className={styles.evidenceGallery}>
              {manifest.evidence.map((ev) => (
                <a
                  key={ev.id}
                  className={styles.evidenceItem}
                  href={ev.download_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Icon name={ev.file_type === 'application/pdf' ? 'file' : 'eye'} />
                  <span className={styles.evidenceName}>{ev.label ?? ev.file_name}</span>
                  <span className={styles.evidenceMeta}>{ev.file_name}</span>
                </a>
              ))}
            </div>
          </Card>
        </div>
      )}

      {showVerifyModal && (
        <VerifyManifestModal
          manifest={manifest}
          onCancel={() => setShowVerifyModal(false)}
          onVerified={(updated) => {
            applyUpdated(updated)
            setShowVerifyModal(false)
          }}
        />
      )}
      {showResolveModal && (
        <ResolveDiscrepancyModal
          manifest={manifest}
          onCancel={() => setShowResolveModal(false)}
          onResolved={(updated) => {
            applyUpdated(updated)
            setShowResolveModal(false)
          }}
        />
      )}

      {showRevokeConfirm && (
        <div className={styles.modalOverlay} onClick={() => setShowRevokeConfirm(false)}>
          <DialogGuard onClose={() => setShowRevokeConfirm(false)} />
          <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <h3 className={styles.modalTitle}>Revoke verification?</h3>
            <p className={styles.modalBody}>
              This will reset the manifest to <strong>Pending</strong> so it can be re-verified. Any downstream processes
              that have already consumed this verification (release notes, billing) are not affected by this action.
            </p>
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setShowRevokeConfirm(false)} disabled={revoking}>
                Cancel
              </Button>
              <Button variant="danger" loading={revoking} onClick={() => void handleRevoke()}>
                Revoke verification
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
