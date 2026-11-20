import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useParams } from 'react-router-dom'
import { disputeApi, type DisputeDetail as DisputeDetailData, type ResolveCBMDisputeInput } from '../../api/billing'
import { isTerminalDisputeStatus } from '../../api/billingRules'
import { ApiError } from '../../api/client'
import { disputeKeys } from '../../api/keys'
import { Banner, Button, Card, Field, Mono, Table, StatusBadge, PageSkeleton, EmptyState } from '../../design/components'
import { STALE_30S } from '../../lib/queryClient'
import { SectionHead } from '../../shell/SectionHead'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './DisputeDetail.module.css'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { toast } from '../../design/toast'

function ResolvePanel({ dispute, onResolved }: { dispute: DisputeDetailData; onResolved: () => void }): JSX.Element {
  const [outcome, setOutcome] = useState<'resolved_adjusted' | 'resolved_no_change'>('resolved_no_change')
  const [correctedCbm, setCorrectedCbm] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit =
    notes.trim().length > 0 && (outcome === 'resolved_no_change' || Number(correctedCbm) > 0)

  async function submit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: ResolveCBMDisputeInput = { status: outcome, resolution_notes: notes.trim() }
      if (outcome === 'resolved_adjusted') body.corrected_cbm = correctedCbm
      await disputeApi.resolve(dispute.id, body)
      toast.success('Dispute resolved')
      onResolved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve the dispute. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card padding="large">
      <SectionHead title="Resolve" sub="Decide whether the billed CBM stands or needs correcting." />
      <div style={{ height: 12 }} />
      {error && (
        <div style={{ marginBottom: 'var(--space-3)' }}>
          <Banner variant="error" title="Could not resolve">{error}</Banner>
        </div>
      )}
      <div className={styles.outcome}>
        <Button variant={outcome === 'resolved_no_change' ? 'primary' : 'secondary'} onClick={() => setOutcome('resolved_no_change')}>
          No change: CBM stands
        </Button>
        <Button variant={outcome === 'resolved_adjusted' ? 'primary' : 'secondary'} onClick={() => setOutcome('resolved_adjusted')}>
          Adjust CBM
        </Button>
      </div>
      {outcome === 'resolved_adjusted' && (
        <Field
          label="Corrected CBM"
          name="corrected_cbm"
          type="number"
          required
          placeholder={`Billed: ${dispute.billed_cbm ?? '—'}`}
          value={correctedCbm}
          onChange={(e) => setCorrectedCbm(e.target.value)}
        />
      )}
      <Field
        label="Resolution notes"
        name="resolution_notes"
        multiline
        required
        placeholder="Explain the decision…"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      <div className={styles.actions}>
        <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void submit()}>
          Resolve dispute
        </Button>
      </div>
    </Card>
  )
}

/**
 * A CBM dispute as China staff see it (audit UX-01).
 *
 * China staff are asked to resolve escalated disputes but may not open invoices, so the invoice page, where Nigeria
 * staff and admins resolve them inline, was closed to them and no screen let them do it. This shows what they
 * need to judge a measurement (what the customer claims, what was billed, the packing-list lines it was summed
 * from) and the resolve action. It carries no amount or payment.
 */
export function DisputeDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  useTopBarSlot({ subtitle: 'Judge the measurement, then resolve.' })

  const { data: dispute, isLoading, error } = useQuery({
    queryKey: disputeKeys.detail(id ?? ''),
    queryFn: () => disputeApi.get(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(dispute?.container_number)

  if (isLoading) return <PageSkeleton kind="detail" label="Loading dispute" />

  if (error || !dispute) {
    return (
      <div className={styles.page}>
        <Banner variant="error" title="Couldn't open this dispute">
          {error instanceof ApiError && error.status === 404 ? 'Dispute not found.' : 'Please try again.'}
        </Banner>
      </div>
    )
  }

  const terminal = isTerminalDisputeStatus(dispute.status)
  const totalLineCbm = dispute.lines.reduce((sum, line) => sum + Number(line.cbm), 0)

  return (
    <div className={styles.page}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <StatusBadge kind="dispute" status={dispute.status} />
      </div>

      <Card padding="large">
        <SectionHead
          title={`${dispute.customer_name ?? 'Customer'} · ${dispute.container_number ?? 'container'}`}
          sub="What the customer claims against what was billed"
        />
        <div style={{ height: 16 }} />
        <div className={styles.compare}>
          <div className={styles.fact}>
            <span className={styles.factLabel}>Billed CBM</span>
            <span className={styles.factValue}>{dispute.billed_cbm ?? '—'}</span>
          </div>
          <div className={styles.fact}>
            <span className={styles.factLabel}>Customer measured</span>
            <span className={styles.factValue}>{dispute.customer_measured_cbm ?? '—'}</span>
          </div>
          <div className={styles.fact}>
            <span className={styles.factLabel}>Disputed CBM</span>
            <span className={styles.factValue}>{dispute.original_cbm ?? '—'}</span>
          </div>
          {dispute.corrected_cbm && (
            <div className={styles.fact}>
              <span className={styles.factLabel}>Corrected CBM</span>
              <span className={styles.factValue}>{dispute.corrected_cbm}</span>
            </div>
          )}
        </div>
        {dispute.reason && (
          <>
            <div style={{ height: 16 }} />
            <p className={styles.reason}><strong>Customer&apos;s reason:</strong> {dispute.reason}</p>
          </>
        )}
        {dispute.resolution_notes && (
          <p className={styles.reason} style={{ marginTop: 'var(--space-2)' }}><strong>Resolution:</strong> {dispute.resolution_notes}</p>
        )}
      </Card>

      <Card padding="none">
        <div style={{ padding: 'var(--space-5) var(--space-5)' }}>
          <SectionHead
            title="Packing-list lines"
            sub={`${dispute.lines.length} line${dispute.lines.length === 1 ? '' : 's'} · ${totalLineCbm.toFixed(3)} CBM in total`}
          />
        </div>
        <Table
          dense
          cardBreakpoint={640}
          columns={[
            { title: 'List' },
            { title: 'Tag', type: 'reference' },
            { title: 'Description' },
            { title: 'Qty', type: 'number' },
            { title: 'L × W × H (cm)' },
            { title: 'Volume (CBM)', type: 'number' },
          ]}
          rows={dispute.lines.map((line) => ({
            cells: [
              <Mono key="ref">{line.reference ?? '—'}</Mono>,
              <Mono key="tag">{line.carton_tag}</Mono>,
              <span key="desc">{line.description}</span>,
              <span key="qty">{line.quantity}{line.package_unit ? ` ${line.package_unit}` : ''}</span>,
              <Mono key="dims">
                {line.length_cm && line.width_cm && line.height_cm ? `${line.length_cm} × ${line.width_cm} × ${line.height_cm}` : '—'}
              </Mono>,
              <Mono key="cbm">{line.cbm}</Mono>,
            ],
          }))}
          emptyState={<EmptyState compact title="No approved packing-list lines for this customer on this container" />}
        />
      </Card>

      {terminal ? (
        <Banner variant="success" title="This dispute is resolved">
          {dispute.resolution_notes ?? 'No further action is needed.'}
        </Banner>
      ) : (
        <ResolvePanel
          dispute={dispute}
          onResolved={() => {
            // The central rule for PATCH /v1/billing/disputes/ refreshes the lists; this page's own read is
            // keyed separately, so refresh it too.
            void qc.invalidateQueries({ queryKey: disputeKeys.detail(dispute.id) })
          }}
        />
      )}
    </div>
  )
}
