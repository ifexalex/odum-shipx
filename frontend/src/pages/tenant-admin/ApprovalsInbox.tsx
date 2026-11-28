/**
 * Tenant Admin — Approvals Inbox (/admin/approvals, Phase 1, TC-02, D5).
 *
 * One queue for every decision waiting on a tenant admin:
 *   - Credit release requests (staff requests to release goods with unpaid balance)
 *   - Refunds above the staff approval threshold (or CBM correction / high compensation)
 *   - Damage claims above the staff approval threshold
 *   - Staff announcement requests targeting customers
 *
 * Approving or rejecting calls each domain's own audited endpoint so there is
 * a single source of truth and a complete before/after audit trail.
 */
import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { announcementsApi } from '../../api/announcements'
import { ApiError } from '../../api/client'
import { tenantApprovalKeys } from '../../api/keys'
import { refundsApi } from '../../api/refunds'
import { releaseNotesApi } from '../../api/releaseNotes'
import {
  configApi,
  type TenantApprovalItem,
  type TenantApprovalType,
} from '../../api/tenantManagement'
import {
  Action,
  Badge,
  Banner,
  Button,
  Chip,
  EmptyState,
  Field,
  Kvp,
  Modal,
  Table,
} from '../../design/components'
import { toast } from '../../design/toast'
import { formatDateTime, formatNgn } from '../../lib/format'
import { STALE_30S } from '../../lib/queryClient'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'
import styles from './admin.module.css'

type TypeFilter = 'all' | TenantApprovalType

const TYPE_LABELS: Record<TenantApprovalType, string> = {
  credit_release: 'Credit release',
  refund: 'Refund',
  claim: 'Damage claim',
  announcement: 'Announcement',
}

interface DecisionDialogProps {
  item: TenantApprovalItem
  mode: 'approve' | 'reject'
  onClose: () => void
  onDone: () => void
}

function DecisionDialog({ item, mode, onClose, onDone }: DecisionDialogProps): JSX.Element {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const requiresNotes = mode === 'reject'
  const canSubmit = (!requiresNotes || notes.trim().length > 0) && !submitting

  async function handleSubmit(): Promise<void> {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const trimmed = notes.trim()
      if (item.type === 'credit_release') {
        if (mode === 'approve') {
          const res = await releaseNotesApi.approveCreditRequest(item.entity_id, trimmed || undefined)
          toast.success('Credit release approved', res.release_note.reference_number)
        } else {
          await releaseNotesApi.rejectCreditRequest(item.entity_id, trimmed)
          toast.success('Credit release rejected', item.customer_name ?? undefined)
        }
      } else if (item.type === 'refund') {
        if (mode === 'approve') {
          await refundsApi.approve(item.entity_id, {
            amount_approved_ngn: item.amount_ngn ?? '0',
            approval_notes: trimmed || undefined,
          })
          toast.success('Refund approved', item.customer_name ?? undefined)
        } else {
          await refundsApi.reject(item.entity_id, trimmed)
          toast.success('Refund rejected', item.customer_name ?? undefined)
        }
      } else if (item.type === 'announcement') {
        if (mode === 'approve') {
          await announcementsApi.approve(item.entity_id)
          toast.success('Announcement approved and sent')
        } else {
          await announcementsApi.reject(item.entity_id, trimmed)
          toast.success('Announcement request rejected')
        }
      }
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={mode === 'approve' ? `Approve ${TYPE_LABELS[item.type].toLowerCase()}` : `Reject ${TYPE_LABELS[item.type].toLowerCase()}`}
      size="sm"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        <div>
          <div style={{ fontWeight: 600 }}>{item.title}</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>{item.summary}</div>
        </div>

        {item.exceeds_credit_limit && (
          <Banner variant="warning" title="Exceeds customer credit limit">
            Exposure {formatNgn(Number(item.customer_outstanding_ngn ?? 0))} exceeds credit limit{' '}
            {formatNgn(Number(item.customer_credit_limit_ngn ?? 0))}. Approving will be audited as an over-limit override.
          </Banner>
        )}

        {item.self_requested && mode === 'approve' && (
          <Banner variant="info" title="Self-approval">
            You submitted this request. Approving it will be marked as self-approved in the audit log.
          </Banner>
        )}

        <Kvp label="Requested by" value={item.requested_by_name ?? 'Staff'} />
        {item.amount_ngn && <Kvp label="Amount" value={formatNgn(Number(item.amount_ngn))} />}
        {item.reason && <Kvp label="Reason" value={item.reason} divider={false} />}

        <Field
          label={mode === 'reject' ? 'Rejection reason' : 'Approval notes'}
          name="decision_notes"
          required={requiresNotes}
          optional={!requiresNotes}
          multiline
          placeholder={
            mode === 'reject'
              ? 'Explain why this request is rejected…'
              : 'Optional notes stored with the audit record…'
          }
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Action
            variant={mode === 'reject' ? 'danger' : 'primary'}
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {mode === 'approve' ? 'Approve' : 'Reject'}
          </Action>
        </div>
      </div>
    </Modal>
  )
}

export function ApprovalsInbox(): JSX.Element {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<TypeFilter>('all')
  const [deciding, setDeciding] = useState<{ item: TenantApprovalItem; mode: 'approve' | 'reject' } | null>(null)
  const [inspecting, setInspecting] = useState<TenantApprovalItem | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: tenantApprovalKeys.list(filter),
    queryFn: () => configApi.getApprovals(filter === 'all' ? {} : { type: filter }),
    staleTime: STALE_30S,
  })

  const counts = data?.counts ?? { total: 0, credit_release: 0, refund: 0, claim: 0, announcement: 0 }
  const items = data?.items ?? []

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Approvals"
            meta={
              data
                ? `Pending items waiting on a tenant admin. Staff limit: $${data.staff_limit_usd} USD (${formatNgn(data.staff_limit_ngn)}).`
                : 'Credit releases, high-value refunds and claims, and customer announcements waiting for approval.'
            }
          />
        }
        notices={<>{error && <Banner variant="error">{error instanceof ApiError ? error.message : 'Could not load approvals.'}</Banner>}</>}
        filters={
          <FilterBar
            label="Filter approvals by type"
            status={
              <>
                <Chip active={filter === 'all'} onClick={() => setFilter('all')}>
                  All ({counts.total})
                </Chip>
                <Chip active={filter === 'credit_release'} onClick={() => setFilter('credit_release')}>
                  Credit releases ({counts.credit_release})
                </Chip>
                <Chip active={filter === 'refund'} onClick={() => setFilter('refund')}>
                  Refunds ({counts.refund})
                </Chip>
                <Chip active={filter === 'claim'} onClick={() => setFilter('claim')}>
                  Claims ({counts.claim})
                </Chip>
                <Chip active={filter === 'announcement'} onClick={() => setFilter('announcement')}>
                  Announcements ({counts.announcement})
                </Chip>
              </>
            }
          />
        }
      >
        <Table
          columns={[
            { title: 'Type', width: '140px' },
            { title: 'Request' },
            { title: 'Amount', width: '140px' },
            { title: 'Requested by', width: '180px' },
            { title: '', type: 'action', width: '260px' },
          ]}
          rows={items.map((item) => ({
            cells: [
              <div key="type" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
                <Badge variant={item.exceeds_credit_limit ? 'warning' : 'info'}>
                  {TYPE_LABELS[item.type]}
                </Badge>
                {item.exceeds_credit_limit && (
                  <Badge variant="error">Over credit limit</Badge>
                )}
                {item.self_requested && (
                  <Badge variant="neutral">Self-requested</Badge>
                )}
              </div>,
              <div key="req" style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>{item.title}</div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>{item.summary}</div>
                {item.reason && (
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-1)' }}>
                    {item.reason.length > 100 ? `${item.reason.slice(0, 100)}…` : item.reason}
                  </div>
                )}
              </div>,
              <span key="amt" style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                {item.amount_ngn ? formatNgn(Number(item.amount_ngn)) : '—'}
              </span>,
              <div key="by" style={{ fontSize: 'var(--text-xs)' }}>
                <div>{item.requested_by_name ?? 'Staff'}</div>
                <div style={{ color: 'var(--color-ink-4)' }}>{formatDateTime(item.created_at)}</div>
              </div>,
              <div key="actions" style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                <Button variant="ghost" size="sm" onClick={() => setInspecting(item)}>
                  Context
                </Button>
                {item.type === 'claim' ? (
                  <Button variant="primary" size="sm" onClick={() => navigate(item.detail_path)}>
                    Review claim
                  </Button>
                ) : (
                  <>
                    <Button variant="danger-ghost" size="sm" onClick={() => setDeciding({ item, mode: 'reject' })}>
                      Reject
                    </Button>
                    <Button variant="primary" size="sm" onClick={() => setDeciding({ item, mode: 'approve' })}>
                      Approve
                    </Button>
                  </>
                )}
              </div>,
            ],
          }))}
          loading={isLoading}
          emptyState={
            !isLoading && items.length === 0 ? (
              <EmptyState
                compact
                title="Nothing waiting for approval"
                description="High-value refunds, claims above the staff limit, credit release requests, and staff announcements will appear here."
              />
            ) : undefined
          }
        />
      </ListPage>

      {inspecting && (
        <Modal open onClose={() => setInspecting(null)} title={inspecting.title} size="md">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <Kvp label="Type" value={TYPE_LABELS[inspecting.type]} />
            <Kvp label="Summary" value={inspecting.summary} />
            {inspecting.customer_name && <Kvp label="Customer" value={inspecting.customer_name} />}
            {inspecting.amount_ngn && <Kvp label="Amount" value={formatNgn(Number(inspecting.amount_ngn))} />}
            {inspecting.customer_outstanding_ngn && (
              <Kvp label="Customer exposure" value={formatNgn(Number(inspecting.customer_outstanding_ngn))} />
            )}
            {inspecting.customer_credit_limit_ngn && (
              <Kvp label="Effective credit limit" value={formatNgn(Number(inspecting.customer_credit_limit_ngn))} />
            )}
            <Kvp label="Requested by" value={`${inspecting.requested_by_name ?? 'Staff'} · ${formatDateTime(inspecting.created_at)}`} />
            <Kvp label="Reason / details" value={inspecting.reason || '—'} divider={false} />
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setInspecting(null)}>
                Close
              </Button>
              {inspecting.customer_id && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    const cid = inspecting.customer_id
                    setInspecting(null)
                    if (cid) navigate(`/admin/customers/${cid}`)
                  }}
                >
                  Open customer
                </Button>
              )}
              <Button
                variant="primary"
                onClick={() => {
                  const target = inspecting.detail_path
                  setInspecting(null)
                  navigate(target)
                }}
              >
                Open source record
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {deciding && (
        <DecisionDialog
          item={deciding.item}
          mode={deciding.mode}
          onClose={() => setDeciding(null)}
          onDone={() => {
            setDeciding(null)
            void refetch()
          }}
        />
      )}
    </>
  )
}
