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
import { Banner, Button, Chip, Field, Kvp, Modal, SearchField, StatusBadge, Table, EmptyState } from '../../design/components'
import { formatDate, formatDateTime } from '../../lib/format'
import { statusLabel, statusesOf } from '../../design/status'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

// Leads still worth acting on — a terminal lead (rejected/provisioned) shows no
// row actions.
const OPEN_STATUSES: OnboardingRequestStatus[] = ['new', 'contacted', 'approved']

export function OnboardingRequests(): JSX.Element {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<OnboardingRequestStatus | null>(null)
  const [query, setQuery] = useState('')
  const [viewing, setViewing] = useState<OnboardingRequest | null>(null)
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

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return requests.filter((r) => {
      if (statusFilter && r.status !== statusFilter) return false
      if (!q) return true
      return (
        r.company_name.toLowerCase().includes(q) ||
        r.contact_name.toLowerCase().includes(q) ||
        r.contact_email.toLowerCase().includes(q) ||
        r.origin_country.toLowerCase().includes(q) ||
        r.destination_country.toLowerCase().includes(q) ||
        (r.notes ?? '').toLowerCase().includes(q)
      )
    })
  }, [requests, statusFilter, query])

  const pendingCount = counts.new + counts.contacted + counts.approved

  // Reject flow — capture a reason before patching.
  const [rejecting, setRejecting] = useState<OnboardingRequest | null>(null)
  const [rejectReason, setRejectReason] = useState('')

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
    <>
      <ListPage
        header={
          <PageHeader
            title="Onboarding requests"
            meta={[
              'Shipping companies requesting to onboard onto ShipX.',
              pendingCount > 0 && `${pendingCount} awaiting action`,
            ]}
          />
        }
        notices={
          <>
            {error && <Banner variant="error">{error.message}</Banner>}
            {updateRequest.isError && (
              <Banner variant="error" title="Could not update the request">
                {updateRequest.error.message}
              </Banner>
            )}
          </>
        }
        filters={
          <FilterBar
            label="Filter onboarding requests"
            status={
              <>
                <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                  All{' '}
                  {requests.length > 0 && <span style={{ opacity: 0.6 }}>{requests.length}</span>}
                </Chip>
                {statusesOf('onboardingRequest').map((status) => (
                  <Chip
                    key={status}
                    active={statusFilter === status}
                    onClick={() => setStatusFilter(statusFilter === status ? null : status)}
                  >
                    {statusLabel('onboardingRequest', status)}{' '}
                    <span style={{ opacity: 0.6 }}>{counts[status]}</span>
                  </Chip>
                ))}
              </>
            }
            search={
              <SearchField
                label="Search onboarding requests"
                placeholder="Company, contact, route, or notes…"
                value={query}
                onChange={setQuery}
              />
            }
          />
        }
      >
        <Table
          columns={[
            { title: 'Company' },
            { title: 'Contact' },
            { title: 'Route' },
            { title: 'Volume (CBM)', type: 'number' },
            { title: 'Status', type: 'status' },
            { title: 'Received', type: 'date' },
            { title: '', type: 'action', width: '280px' },
          ]}
          rows={visible.map((r) => ({
            onOpen: () => setViewing(r),
            openLabel: `Inspect ${r.company_name}`,
            cells: [
              <div key="company" style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>{r.company_name}</div>
                {r.notes && (
                  <div
                    style={{
                      fontSize: 'var(--text-xs)',
                      color: 'var(--color-ink-4)',
                      maxWidth: 260,
                    }}
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
              <span
                key="volume"
                style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}
              >
                {r.monthly_volume ?? '—'}
              </span>,
              <StatusBadge key="status" kind="onboardingRequest" status={r.status} />,
              <span key="date" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                {formatDate(r.created_at)}
              </span>,
              OPEN_STATUSES.includes(r.status) ? (
                <div
                  key="actions"
                  style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}
                >
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
                    variant="danger-ghost"
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
              ) : r.status === 'provisioned' && r.tenant_id ? (
                <div key="actions" style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Button
                    variant="secondary"
                    size="sm"
                    trailingIcon="arrowright"
                    onClick={() => navigate(`/platform/tenants/${r.tenant_id}`)}
                  >
                    Open tenant
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
              <EmptyState
                compact
                title={
                  requests.length === 0
                    ? 'No onboarding requests yet'
                    : 'No requests match the current filter'
                }
              />
            ) : undefined
          }
        />
      </ListPage>
      <Modal
        open={viewing !== null}
        onClose={() => setViewing(null)}
        title={viewing?.company_name ?? 'Onboarding request'}
        size="md"
        footer={
          viewing && (
            <>
              <Button variant="ghost" onClick={() => setViewing(null)}>Close</Button>
              {viewing.status === 'provisioned' && viewing.tenant_id && (
                <Button
                  variant="primary"
                  trailingIcon="arrowright"
                  onClick={() => {
                    const tid = viewing.tenant_id
                    setViewing(null)
                    navigate(`/platform/tenants/${tid}`)
                  }}
                >
                  Open tenant
                </Button>
              )}
              {OPEN_STATUSES.includes(viewing.status) && (
                <Button
                  variant="primary"
                  icon="plus"
                  onClick={() => {
                    const lead = viewing
                    setViewing(null)
                    provision(lead)
                  }}
                >
                  Provision tenant
                </Button>
              )}
            </>
          )
        }
      >
        {viewing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <Kvp label="Status" value={<StatusBadge kind="onboardingRequest" status={viewing.status} />} />
            <Kvp label="Contact" value={`${viewing.contact_name} · ${viewing.contact_email}${viewing.contact_phone ? ` · ${viewing.contact_phone}` : ''}`} />
            <Kvp label="Corridor" value={`${viewing.origin_country} → ${viewing.destination_country}`} />
            <Kvp label="Monthly volume" value={viewing.monthly_volume ?? 'Not provided'} />
            <Kvp label="Received" value={formatDateTime(viewing.created_at)} divider={Boolean(viewing.notes || viewing.rejection_reason)} />
            {viewing.notes && (
              <div
                style={{
                  padding: 'var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--color-surface-muted)',
                  border: '1px solid var(--color-line-soft)',
                  fontSize: 'var(--text-sm)',
                  whiteSpace: 'pre-wrap',
                }}
              >
                <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', marginBottom: 'var(--space-1)' }}>
                  Notes
                </div>
                {viewing.notes}
              </div>
            )}
            {viewing.status === 'rejected' && viewing.rejection_reason && (
              <Banner variant="error" title="Rejection reason">{viewing.rejection_reason}</Banner>
            )}
          </div>
        )}
      </Modal>
      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="Reject onboarding request"
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setRejecting(null)}
              disabled={updateRequest.isPending}
            >
              Cancel
            </Button>
            <Button variant="danger" loading={updateRequest.isPending} onClick={confirmReject}>
              Reject request
            </Button>
          </>
        }
      >
        <p
          style={{
            fontSize: 'var(--text-sm)',
            color: 'var(--color-ink-3)',
            margin: '0 0 var(--space-4)',
          }}
        >
          Rejecting <strong>{rejecting?.company_name}</strong>&apos;s request. The reason is
          recorded for the audit trail; it is not emailed to the company.
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
    </>
  )
}
