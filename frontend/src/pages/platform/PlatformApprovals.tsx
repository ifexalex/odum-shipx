/**
 * Approvals (platform audit Phase 1, C-30, decision D4): the two-person requests for offboarding a tenant, a new
 * provider gateway key and turning maintenance mode on.
 *
 * Open requests come first. A request can be approved or rejected by any owner or admin except the person who made
 * it; the requester (or an owner) can cancel it, including a sole admin's offboarding while it waits out its 24 hours.
 * Approving and rejecting ask for re-authentication (the API answers STEP_UP_REQUIRED and the client prompts).
 */
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { platformSecurityApi, type PlatformApproval } from '../../api/platformSecurity'
import { Banner, Button, Chip, EmptyState, Field, Modal, StatusBadge, Table } from '../../design/components'
import { toast } from '../../design/toast'
import { useCanPlatform, usePlatformApprovals, usePlatformMe } from '../../hooks/usePlatformSecurity'
import { formatDateTime } from '../../lib/format'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'
import styles from './admin.module.css'

type View = 'open' | 'all'
type Decision = 'approve' | 'reject' | 'cancel'

const ACTION_LABEL: Record<PlatformApproval['action'], string> = {
  offboard_tenant: 'Offboard tenant',
  gateway_secret_change: 'New gateway key',
  maintenance_on: 'Maintenance on',
  plan_price_change: 'Plan price change',
  data_cleanup_rerun: 'Re-run data cleanup',
  admin_transfer: 'Transfer tenant admin',
}

function summaryOf(a: PlatformApproval): string {
  return a.payload.summary ?? `${ACTION_LABEL[a.action]}: ${a.target_tenant_name ?? a.target_label}`
}

function whenLine(a: PlatformApproval): string {
  if (a.status === 'scheduled' && a.execute_after) return `Runs ${formatDateTime(a.execute_after)} unless cancelled`
  if (a.status === 'pending') return `Expires ${formatDateTime(a.expires_at)}`
  if (a.status === 'executed' && a.executed_at) return `Done ${formatDateTime(a.executed_at)}`
  if (a.decided_at) return `${a.decided_by_name ?? 'Decided'} · ${formatDateTime(a.decided_at)}`
  return ''
}

interface DecisionModalProps {
  approval: PlatformApproval
  decision: Decision
  onClose: () => void
}

function DecisionModal({ approval, decision, onClose }: DecisionModalProps): JSX.Element {
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const copy = {
    approve: { title: 'Approve this request?', button: 'Approve and run', variant: 'danger' as const },
    reject: { title: 'Reject this request?', button: 'Reject', variant: 'danger' as const },
    cancel: { title: 'Cancel this request?', button: 'Cancel request', variant: 'secondary' as const },
  }[decision]

  async function submit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const trimmed = note.trim() || undefined
      if (decision === 'approve') await platformSecurityApi.approve(approval.id, trimmed)
      else if (decision === 'reject') await platformSecurityApi.reject(approval.id, trimmed)
      else await platformSecurityApi.cancel(approval.id, trimmed)
      toast.success(
        decision === 'approve' ? 'Approved and done' : decision === 'reject' ? 'Request rejected' : 'Request cancelled',
        summaryOf(approval),
      )
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That did not go through.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={copy.title} size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        <div>
          <div style={{ fontWeight: 600 }}>{summaryOf(approval)}</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>
            Requested by {approval.requested_by_name} · {formatDateTime(approval.requested_at)}
          </div>
          {approval.reason && (
            <div style={{ fontSize: 'var(--text-sm)', marginTop: 'var(--space-2)' }}>Reason: {approval.reason}</div>
          )}
        </div>
        {decision === 'approve' && (
          <Banner variant="warning">It runs as soon as you approve. Offboarding cannot be undone from here.</Banner>
        )}
        <Field
          label="Note"
          name="decision_note"
          optional
          multiline
          value={note}
          onChange={(e) => setNote(e.target.value)}
          helper="Kept with the request and the audit log."
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Back
          </Button>
          <Button variant={copy.variant} loading={submitting} onClick={() => void submit()}>
            {copy.button}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function PlatformApprovals(): JSX.Element {
  const [view, setView] = useState<View>('open')
  const [deciding, setDeciding] = useState<{ approval: PlatformApproval; decision: Decision } | null>(null)
  const { data, isLoading, error } = usePlatformApprovals(view === 'open' ? 'open' : undefined)
  const { data: me } = usePlatformMe()
  const canApprove = useCanPlatform('approve')
  const isOwner = useCanPlatform('admins')
  const approvals = data ?? []

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Approvals"
            meta="Offboarding, new gateway keys and maintenance mode need a second platform admin."
          />
        }
        notices={<>{error && <Banner variant="error">{error.message}</Banner>}</>}
        filters={
          <FilterBar
            label="Filter approvals"
            status={
              <>
                <Chip active={view === 'open'} onClick={() => setView('open')}>
                  Open
                </Chip>
                <Chip active={view === 'all'} onClick={() => setView('all')}>
                  All
                </Chip>
              </>
            }
          />
        }
      >
        <Table
          columns={[
            { title: 'Request' },
            { title: 'Requested by' },
            { title: 'Status', type: 'status' },
            { title: 'When' },
            { title: '', type: 'action', width: '240px' },
          ]}
          rows={approvals.map((a) => {
            const mine = me?.id === a.requested_by
            const open = a.status === 'pending' || a.status === 'scheduled'
            return {
              cells: [
                <div key="request" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>{summaryOf(a)}</div>
                  {a.reason && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }} title={a.reason}>
                      {a.reason.length > 80 ? `${a.reason.slice(0, 80)}…` : a.reason}
                    </div>
                  )}
                  {a.error && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-error)' }}>{a.error}</div>
                  )}
                </div>,
                <div key="by" style={{ fontSize: 'var(--text-xs)' }}>
                  <div style={{ color: 'var(--color-ink-2)' }}>{a.requested_by_name}</div>
                  <div style={{ color: 'var(--color-ink-4)' }}>{formatDateTime(a.requested_at)}</div>
                </div>,
                <StatusBadge key="status" kind="platformApproval" status={a.status} />,
                <span key="when" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {whenLine(a)}
                </span>,
                <div key="actions" style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                  {open && a.status === 'pending' && canApprove && !mine && (
                    <>
                      <Button variant="danger-ghost" size="sm" onClick={() => setDeciding({ approval: a, decision: 'reject' })}>
                        Reject
                      </Button>
                      <Button variant="primary" size="sm" onClick={() => setDeciding({ approval: a, decision: 'approve' })}>
                        Approve
                      </Button>
                    </>
                  )}
                  {open && (mine || isOwner) && (
                    <Button variant="ghost" size="sm" onClick={() => setDeciding({ approval: a, decision: 'cancel' })}>
                      Cancel
                    </Button>
                  )}
                  {open && a.status === 'pending' && mine && (
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', alignSelf: 'center' }}>
                      Waiting for another admin
                    </span>
                  )}
                </div>,
              ],
            }
          })}
          loading={isLoading}
          emptyState={
            !isLoading && approvals.length === 0 ? (
              <EmptyState compact title={view === 'open' ? 'Nothing is waiting for approval' : 'No approval requests yet'} />
            ) : undefined
          }
        />
      </ListPage>
      {deciding && (
        <DecisionModal approval={deciding.approval} decision={deciding.decision} onClose={() => setDeciding(null)} />
      )}
    </>
  )
}
