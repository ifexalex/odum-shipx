/**
 * Shipping-company onboarding queue (platform admin).
 *
 * These are LEADS from logistics companies that submitted the public
 * `/get-started` form (POST /v1/onboarding-requests) — not customers, and not
 * tenants yet: no account exists until an admin provisions one. The admin can
 * mark a lead contacted, reject it (with a reason), or **Provision**, which
 * hands the lead to CreateTenantPage pre-filled; creating the tenant there links
 * it back and flips the lead to `provisioned`.
 */
import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type OnboardingRequest,
  type OnboardingRequestStatus,
} from '../../api/tenantManagement'
import {
  useOnboardingRequests,
  useUpdateOnboardingRequest,
} from '../../hooks/useOnboardingRequests'
import { Banner, Button, Card, Chip, Field, Modal, StatusBadge, Table, EmptyState } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel, statusesOf } from '../../design/status'

// Leads still worth acting on — a terminal lead (rejected/provisioned) shows no
// row actions.
const OPEN_STATUSES: OnboardingRequestStatus[] = ['new', 'contacted', 'approved']

export function OnboardingRequests(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<OnboardingRequestStatus | null>(null)
  const { data, isLoading: loading, error } = useOnboardingRequests()
  const updateRequest = useUpdateOnboardingRequest()

  const requests = useMemo(() => data ?? [], [data])

  const counts = useMemo(() => {
    const map: Record<OnboardingRequestStatus, number> = {
      new: 0,
      contacted: 0,
      approved: 0,
      rejected: 0,
      provisioned: 0,
    }
    for (const r of requests) map[r.status] += 1
    return map
  }, [requests])

  const visible = useMemo(
    () => (statusFilter ? requests.filter((r) => r.status === statusFilter) : requests),
    [requests, statusFilter],
  )

  const pendingCount = counts.new + counts.contacted + counts.approved

  // Reject flow — capture a reason before patching.
  const [rejecting, setRejecting] = useState<OnboardingRequest | null>(null)
  const [rejectReason, setRejectReason] = useState('')

  useTopBarSlot({
    subtitle: 'Shipping companies requesting to onboard onto ShipX.',
  })

  function markContacted(req: OnboardingRequest): void {
    updateRequest.mutate({ id: req.id, status: 'contacted' })
  }

  function provision(req: OnboardingRequest): void {
    navigate('/platform/tenants/new', { state: { lead: req } })
  }

  function confirmReject(): void {
    if (!rejecting) return
    updateRequest.mutate(
      { id: rejecting.id, status: 'rejected', rejectionReason: rejectReason.trim() || undefined },
      {
        onSuccess: () => {
          setRejecting(null)
          setRejectReason('')
        },
      },
    )
  }

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error.message}</Banner>
        </div>
      )}
      {updateRequest.isError && (
        <div className={styles.banner}>
          <Banner variant="error" title="Could not update the request">
            {updateRequest.error.message}
          </Banner>
        </div>
      )}

      <Card padding="default">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All {requests.length > 0 && <span style={{ opacity: 0.6 }}>{requests.length}</span>}
            </Chip>
            {statusesOf('onboardingRequest').map((status) => (
              <Chip
                key={status}
                active={statusFilter === status}
                onClick={() => setStatusFilter(statusFilter === status ? null : status)}
              >
                {statusLabel('onboardingRequest', status)} <span style={{ opacity: 0.6 }}>{counts[status]}</span>
              </Chip>
            ))}
          </div>
          {pendingCount > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>
              {pendingCount} awaiting action
            </span>
          )}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Company' },
              { title: 'Contact' },
              { title: 'Route' },
              { title: 'Volume' },
              { title: 'Status' },
              { title: 'Received' },
              { title: '', width: '280px' },
            ]}
            rows={visible.map((r) => ({
              cells: [
                <div key="company" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>{r.company_name}</div>
                  {r.notes && (
                    <div
                      style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', maxWidth: 260 }}
                      title={r.notes}
                    >
                      {r.notes.length > 60 ? `${r.notes.slice(0, 60)}…` : r.notes}
                    </div>
                  )}
                  {r.status === 'rejected' && r.rejection_reason && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-error)' }}>
                      Rejected: {r.rejection_reason}
                    </div>
                  )}
                </div>,
                <div key="contact" style={{ fontSize: 'var(--text-xs)' }}>
                  <div style={{ color: 'var(--color-ink-2)' }}>{r.contact_name}</div>
                  <div style={{ color: 'var(--color-ink-4)' }}>{r.contact_email}</div>
                  {r.contact_phone && (
                    <div style={{ color: 'var(--color-ink-4)' }}>{r.contact_phone}</div>
                  )}
                </div>,
                <span key="route" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {r.origin_country} → {r.destination_country}
                </span>,
                <span key="volume" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {r.monthly_volume ?? '—'}
                </span>,
                <StatusBadge key="status" kind="onboardingRequest" status={r.status} />,
                <span key="date" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {formatDate(r.created_at)}
                </span>,
                OPEN_STATUSES.includes(r.status) ? (
                  <div key="actions" style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                    {r.status === 'new' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={updateRequest.isPending}
                        onClick={() => markContacted(r)}
                      >
                        Mark contacted
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={updateRequest.isPending}
                      onClick={() => {
                        setRejectReason('')
                        setRejecting(r)
                      }}
                    >
                      Reject
                    </Button>
                    <Button variant="primary" size="sm" icon="plus" onClick={() => provision(r)}>
                      Provision
                    </Button>
                  </div>
                ) : (
                  <span key="actions" />
                ),
              ],
            }))}
            loading={loading}
            emptyState={
              !loading && visible.length === 0 ? (
                <EmptyState compact title={requests.length === 0 ? 'No onboarding requests yet' : 'No requests match the current filter'} />
              ) : undefined
            }
          />
        </Card>
      </div>

      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="Reject onboarding request"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRejecting(null)} disabled={updateRequest.isPending}>
              Cancel
            </Button>
            <Button variant="danger" loading={updateRequest.isPending} onClick={confirmReject}>
              Reject request
            </Button>
          </>
        }
      >
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)', margin: '0 0 var(--space-4)' }}>
          Rejecting <strong>{rejecting?.company_name}</strong>&apos;s request. The reason is recorded for the
          audit trail; it is not emailed to the company.
        </p>
        <Field
          label="Reason"
          name="rejection_reason"
          placeholder="e.g. Out of serviced corridors"
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          optional
        />
      </Modal>
    </div>
  )
}
