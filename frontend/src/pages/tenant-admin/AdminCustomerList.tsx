import { useEffect, useMemo, useState, type JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { customerKeys } from '../../api/keys'
import { customersApi, type Customer } from '../../api/tenantManagement'
import { useCustomerList } from '../../hooks/useCustomers'
import { Badge, Banner, Button, Chip, Field, Mono, PhoneField, Table, ListFooter, DialogGuard, SearchField, CheckboxField, EmptyState } from '../../design/components'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'
import { toast } from '../../design/toast'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

// ---------------------------------------------------------------------------
// Add customer modal (audit gap B5a — prototype 3.5's "Add customer" action).
// Staff-side onboarding for customers who don't self-register: POST
// /v1/customers creates the record; the customer can later be linked to a
// login via self-registration with the same email.
// ---------------------------------------------------------------------------

const CONSENT_CHANNELS = [
  { key: 'sms', label: 'SMS' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'email', label: 'Email' },
]

interface AddCustomerModalProps {
  onCancel: () => void
  onSuccess: (customer: Customer) => void
}

function AddCustomerModal({ onCancel, onSuccess }: AddCustomerModalProps): JSX.Element {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [whatsapp, setWhatsapp] = useState('')
  const [consent, setConsent] = useState<string[]>(['sms'])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleConsent(key: string): void {
    setConsent((prev) => (prev.includes(key) ? prev.filter((c) => c !== key) : [...prev, key]))
  }

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const customer = await customersApi.create({
        name: name.trim(),
        ...(phone.trim() ? { phone: phone.trim() } : {}),
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(whatsapp.trim() ? { whatsapp: whatsapp.trim() } : {}),
        notification_consent: consent,
      })
      toast.success('Customer added', customer.name ?? undefined)
      onSuccess(customer)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the customer.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Add customer</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}
        <Field
          label="Full name"
          name="name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <PhoneField
          label="Phone"
          name="phone"
          optional
          value={phone}
          onChange={setPhone}
        />
        <Field
          label="Email"
          name="email"
          optional
          type="email"
          icon="mail"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="WhatsApp"
          name="whatsapp"
          optional
          icon="phone"
          placeholder="If different from phone"
          value={whatsapp}
          onChange={(e) => setWhatsapp(e.target.value)}
        />
        <div>
          <label
            style={{
              fontWeight: 600,
              fontSize: 'var(--text-md)',
              display: 'block',
              marginBottom: 'var(--space-2)',
            }}
          >
            Notification consent
          </label>
          <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
            {CONSENT_CHANNELS.map((c) => (
              <CheckboxField key={c.key} label={c.label} checked={consent.includes(c.key)} onChange={() => toggleConsent(c.key)} />
            ))}
          </div>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-2)' }}>
            Only tick channels the customer has agreed to — this is their NDPR/GDPR consent record.
          </p>
        </div>
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon="plus"
            loading={submitting}
            disabled={!name.trim()}
            onClick={() => void handleSubmit()}
          >
            Add customer
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Consent channel chips (audit gap B5b — prototype 3.5 ConsentBlock). Compact
// SMS / WA / EM pills; granted = filled, withheld = muted.
// ---------------------------------------------------------------------------

const CONSENT_PILLS: { key: string; short: string }[] = [
  { key: 'sms', short: 'SMS' },
  { key: 'whatsapp', short: 'WA' },
  { key: 'email', short: 'EM' },
]

function ConsentChips({ consent }: { consent: string[] | null }): JSX.Element {
  const granted = new Set(consent ?? [])
  return (
    <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
      {CONSENT_PILLS.map(({ key, short }) => {
        const on = granted.has(key)
        return (
          <span
            key={key}
            title={key}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: 'var(--space-0-5) var(--space-2)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--text-xs)',
              fontWeight: 700,
              letterSpacing: 'var(--tracking-label)',
              background: on ? 'var(--color-primary-soft)' : 'var(--color-line-soft)',
              color: on ? 'var(--color-primary-on-soft)' : 'var(--color-ink-4)',
            }}
          >
            {short}
          </span>
        )
      })}
    </div>
  )
}

// Account-status indicator — so staff can see who still cannot log in
// (imported customers only ever get name + phone until an invite is
// claimed). Anonymised takes priority; otherwise: has a login (user_id) >
// invite pending (unexpired, unconsumed) > no login at all.
function AccountStatusBadge({ customer }: { customer: Customer }): JSX.Element {
  if (customer.anonymised_at) {
    return <Badge variant="error">Anonymised</Badge>
  }
  if (customer.user_id) {
    return <Badge variant="success">Active</Badge>
  }
  if (customer.pending_invite_expires_at) {
    return <Badge variant="warning">Invited · expires {formatDate(customer.pending_invite_expires_at)}</Badge>
  }
  return <Badge variant="neutral">No login</Badge>
}

type CustomerFilter = 'all' | 'active' | 'anonymised'

export function AdminCustomerList(): JSX.Element {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const location = useLocation()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [filter, setFilter] = useState<CustomerFilter>('all')
  // Dashboard "Add customer" quick action deep-links here with openAdd state (§3.1).
  const [showAdd, setShowAdd] = useState(
    (location.state as { openAdd?: boolean } | null)?.openAdd === true,
  )

  // Debounce the search term; the query hook refetches when it changes.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300)
    return () => clearTimeout(timer)
  }, [query])

  const {
    items: customers,
    isLoading: loading,
    error,
    hasMore,
    loadMore,
    isFetchingMore,
    totalCount,
  } = useCustomerList(debouncedQuery ? { q: debouncedQuery } : {})

  // Stat cards aggregate server-side so they stay correct across the whole
  // tenant, not just the rows currently loaded into the list.
  const { data: stats } = useQuery({
    queryKey: customerKeys.stats(),
    queryFn: customersApi.stats,
  })

  const visible = useMemo(() => {
    if (filter === 'active') return customers.filter((c) => !c.anonymised_at)
    if (filter === 'anonymised') return customers.filter((c) => c.anonymised_at)
    return customers
  }, [customers, filter])

  function handleCreated(customer: Customer): void {
    setShowAdd(false)
    void queryClient.invalidateQueries({ queryKey: customerKeys.all })
    navigate(`/admin/customers/${customer.id}`, { state: { customer } })
  }

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Customers"
            meta={'Manage customer profiles and GDPR requests.'}
            primary={
              <Button variant="primary" icon="plus" onClick={() => setShowAdd(true)}>
                Add customer
              </Button>
            }
          />
        }
        notices={<>{error && <Banner variant="error">{error.message}</Banner>}</>}
        filters={
          <FilterBar
            label="Filter customers"
            status={
              <>
                <Chip active={filter === 'all'} onClick={() => setFilter('all')}>
                  All <span style={{ opacity: 0.6 }}>{stats?.total ?? 0}</span>
                </Chip>
                <Chip active={filter === 'active'} onClick={() => setFilter('active')}>
                  Active <span style={{ opacity: 0.6 }}>{stats?.active ?? 0}</span>
                </Chip>
                <Chip active={filter === 'anonymised'} onClick={() => setFilter('anonymised')}>
                  Anonymised <span style={{ opacity: 0.6 }}>{stats?.anonymised ?? 0}</span>
                </Chip>
              </>
            }
            search={
              <>
                <SearchField
                  label="Search customers"
                  placeholder="Search by name, phone, or email…"
                  value={query}
                  onChange={setQuery}
                />
              </>
            }
          />
        }
        footer={
          <ListFooter
            shown={customers.length}
            total={totalCount}
            hasMore={hasMore}
            loading={isFetchingMore}
            onLoadMore={loadMore}
            noun="customers"
            nounOne="customer"
          />
        }
      >
        <Table
          columns={[
            { title: 'Name' },
            { title: 'Phone' },
            { title: 'Consent' },
            { title: 'Shipments', type: 'number' },
            { title: 'Status', type: 'status' },
          ]}
          rows={visible.map((c) => ({
            onOpen: () => navigate(`/admin/customers/${c.id}`, { state: { customer: c } }),
            cells: [
              <div key="name">
                <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                  {c.name ?? <em style={{ color: 'var(--color-ink-4)' }}>Anonymised</em>}
                </div>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>
                  {c.email ?? '—'}
                </div>
              </div>,
              <Mono key="phone">{c.phone ?? '—'}</Mono>,
              c.anonymised_at ? (
                <span
                  key="consent"
                  style={{
                    fontSize: 'var(--text-xs)',
                    color: 'var(--color-ink-4)',
                    fontStyle: 'italic',
                  }}
                >
                  Withdrawn
                </span>
              ) : (
                <ConsentChips key="consent" consent={c.notification_consent} />
              ),
              <Mono key="ships">{c.shipment_count ?? 0}</Mono>,
              <AccountStatusBadge key="status" customer={c} />,
            ],
          }))}
          loading={loading}
          emptyState={
            !loading && visible.length === 0 ? (
              <EmptyState
                compact
                title={
                  customers.length === 0 ? 'No customers found' : 'No customers match this filter'
                }
              />
            ) : undefined
          }
        />
      </ListPage>
      {showAdd && <AddCustomerModal onCancel={() => setShowAdd(false)} onSuccess={handleCreated} />}
    </>
  )
}
