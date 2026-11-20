/**
 * 3.6 — Customer Profile (audit gap A2, prototype tenant-admin CustomerProfile).
 *
 * Hero (avatar, status badge, contact line) + tab strip:
 *   Profile        — contact card, consent/GDPR card, lifetime stat cards
 *   Shipments      — packing lists filtered by customer (GET /v1/packing-lists?customer_id=)
 *   Billing        — stats + records (GET /v1/billing/{customer-id})
 *   Claims         — damage claims filtered by customer (GET /v1/claims?customer_id=)
 *   Data & privacy — the GDPR flows (export + ANONYMISE erasure), previously header buttons
 *
 * GDPR anonymise still requires typing the literal "ANONYMISE" (case-sensitive)
 * — deliberate friction per the design brief, NOT a generic confirm.
 *
 * Prototype's "Recent activity" table is deliberately skipped: no tenant-scoped
 * audit endpoint exists (AUDIT_GAPS.md B-pattern, same as B3/B6).
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { billingApi, type Billing } from '../../api/billing'
import { claimsApi, type Claim } from '../../api/claims'
import { packingListApi, type PackingList } from '../../api/packingList'
import { customersApi, type Customer } from '../../api/tenantManagement'
import { billingKeys, claimKeys, customerKeys, packingListKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Action, Avatar, Badge, Banner, Button, Card, DialogGuard, Field, Kvp, Mono, StatCard, StatusBadge, Table, ViewLink, Select, PageSkeleton, EmptyState } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { Tabs } from '../../shell/Tabs'
import styles from './admin.module.css'
import { formatDate, formatDateTime, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// GDPR Anonymise Modal — MUST use exact "ANONYMISE" text confirmation
// ---------------------------------------------------------------------------

interface AnonymiseModalProps {
  customer: Customer
  onCancel: () => void
  onSuccess: () => void
}

function AnonymiseModal({ customer, onCancel, onSuccess }: AnonymiseModalProps): JSX.Element {
  const [confirmText, setConfirmText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Case-sensitive exact match — deliberate friction per design brief
  const isConfirmed = confirmText === 'ANONYMISE'

  async function handleConfirm(): Promise<void> {
    if (!isConfirmed) return
    setSubmitting(true)
    setError(null)
    try {
      await customersApi.anonymise(customer.id)
      toast.success('Customer anonymised')
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not anonymise customer.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Erase customer data (GDPR Art. 17)</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error">{error}</Banner></div>}

        <Banner variant="error" title="This action is irreversible">
          All personal data for <strong>{customer.name ?? customer.id}</strong> will be permanently erased —
          name, email, phone, address, and contract details will be nulled. The customer's UUID and
          financial records are retained for legal and accounting purposes.
        </Banner>

        <p className={styles.confirmHint}>
          Type <strong>ANONYMISE</strong> (in capitals) to confirm:
        </p>
        <Field
          label=""
          name="confirm"
          required
          placeholder="ANONYMISE"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          className={styles.confirmInput}
        />

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Action
            variant="danger"
            loading={submitting}
            disabled={!isConfirmed}
            onClick={() => void handleConfirm()}
          >
            Erase data permanently
          </Action>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab content
// ---------------------------------------------------------------------------

const CONSENT_LABEL: Record<string, string> = { sms: 'SMS', whatsapp: 'WhatsApp', email: 'Email' }

function fmtNgn(value: number): string {
  return formatNgn(value)
}

interface ProfileTabProps {
  customer: Customer
  shipments: PackingList[] | null
  billing: Billing[] | null
  claims: Claim[] | null
  onSaved: (c: Customer) => void
}

function ProfileTab({ customer, shipments, billing, claims, onSaved }: ProfileTabProps): JSX.Element {
  const totalBilled = billing?.reduce((s, b) => s + Number(b.total_due_ngn), 0) ?? null
  const outstanding = billing?.reduce((s, b) => s + Number(b.outstanding_ngn), 0) ?? null
  const openClaims = claims?.filter((c) => c.status === 'filed' || c.status === 'under_inspection').length ?? null
  const consent = customer.notification_consent ?? []
  const [savingLocale, setSavingLocale] = useState(false)

  // P2-1 — notification language: read by the tracking→notification flow to
  // pick the EN/ZH template set. Saved immediately on change.
  async function handleLocaleChange(locale: 'en' | 'zh'): Promise<void> {
    if (locale === (customer.locale ?? 'en')) return
    setSavingLocale(true)
    try {
      onSaved(await customersApi.update(customer.id, { locale }))
      toast.success('Message language updated', customer.name ?? undefined)
    } catch {
      // Non-fatal — the select snaps back to the stored value on re-render.
    } finally {
      setSavingLocale(false)
    }
  }

  return (
    <>
      <div className={styles.profileGrid}>
        <Card padding="default">
          <SectionHead title="Contact" />
          <div className={styles.spacer8} />
          <Kvp label="Full name" value={customer.name ?? <em>Erased</em>} />
          <Kvp label="Email" value={customer.email ? customer.email : <em>Erased</em>} />
          <Kvp label="Phone" value={customer.phone ? <Mono>{customer.phone}</Mono> : <em>Erased</em>} />
          <Kvp label="WhatsApp" value={customer.whatsapp ? <Mono>{customer.whatsapp}</Mono> : '—'} />
          <Kvp label="Address" value={customer.address ?? <em>Erased</em>} />
          <Kvp
            label="Customer ID"
            value={<span className={styles.monoValue}>{customer.id}</span>}
            divider={false}
          />
        </Card>

        <Card padding="default">
          <SectionHead title="Consent & GDPR" sub="Lawful-processing record (NDPR / GDPR Art. 6)" />
          <div className={styles.spacer8} />
          <Kvp
            label="Consent given"
            value={formatDate(customer.consent_given_at)}
          />
          <div className={styles.prefRow}>
            <div className={styles.prefLabel}>
              Notification channels
            </div>
            <div className={styles.chipRow}>
              {consent.length === 0 && <Badge variant="neutral">None granted</Badge>}
              {consent.map((c) => (
                <Badge key={c} variant="success">{CONSENT_LABEL[c] ?? c}</Badge>
              ))}
            </div>
          </div>
          <div className={styles.prefRowInline}>
            <div className={styles.prefLabelInline}>
              Message language
            </div>
            <Select label="Message language" hideLabel className={styles.compactSelectField}
              value={customer.locale ?? 'en'}
              disabled={savingLocale || customer.anonymised_at !== null}
              onChange={(e) => void handleLocaleChange(e.target.value as 'en' | 'zh')}
              >
              <option value="en">English</option>
              <option value="zh">中文 (简体)</option>
            </Select>
          </div>
          <Kvp
            label="Anonymised at"
            value={formatDate(customer.anonymised_at)}
            divider={false}
          />
        </Card>
      </div>

      <div className={styles.statsRow}>
        <StatCard label="Total shipments" value={shipments?.length ?? customer.shipment_count ?? '—'} icon="package" sublabel="all time" />
        <StatCard label="Total billed" value={totalBilled != null ? fmtNgn(totalBilled) : '—'} icon="coin" sublabel="all time" />
        <StatCard label="Outstanding" value={outstanding != null ? fmtNgn(outstanding) : '—'} icon="warn" sublabel={outstanding ? 'across unpaid records' : 'nothing due'} />
        <StatCard label="Open claims" value={openClaims ?? '—'} icon="check" sublabel={openClaims ? 'needs attention' : 'no active disputes'} />
      </div>
    </>
  )
}

function ShipmentsTab({ customer, shipments, onOpen }: { customer: Customer; shipments: PackingList[] | null; onOpen: (id: string) => void }): JSX.Element {
  return (
    <Card padding="none">
      <div className={styles.cardPad}>
        <SectionHead
          title={`Shipments${customer.name ? ` · ${customer.name}` : ''}`}
          sub={shipments ? `${shipments.length} total` : undefined}
        />
      </div>
      <Table
        columns={[
          { title: 'Tracking code' },
          { title: 'Container' },
          { title: 'Status' },
          { title: 'Cartons', align: 'right' },
          { title: 'CBM', align: 'right' },
          { title: 'Created' },
          { title: '', width: '60px' },
        ]}
        rows={(shipments ?? []).map((pl) => ({
          cells: [
            <Mono key="code">{pl.reference ?? pl.id.slice(0, 8)}</Mono>,
            <Mono key="cont">{pl.container_number ?? '—'}</Mono>,
            <StatusBadge key="status" kind="packingList" status={pl.status} />,
            <Mono key="cartons">{pl.carton_count}</Mono>,
            <Mono key="cbm">{Number(pl.total_cbm).toFixed(3)}</Mono>,
            <span key="created" className={styles.smallMuted}>{formatDate(pl.created_at)}</span>,
            <ViewLink key="view" onClick={() => onOpen(pl.id)} />,
          ],
        }))}
        loading={shipments === null}
        emptyState={shipments?.length === 0 ? <EmptyState compact title="No shipments for this customer yet" /> : undefined}
      />
    </Card>
  )
}

function BillingTab({ billing, onOpen }: { billing: Billing[] | null; onOpen: (b: Billing) => void }): JSX.Element {
  const totalBilled = billing?.reduce((s, b) => s + Number(b.total_due_ngn), 0) ?? null
  const totalPaid = billing?.reduce((s, b) => s + Number(b.total_paid_ngn), 0) ?? null
  const outstanding = billing?.reduce((s, b) => s + Number(b.outstanding_ngn), 0) ?? null

  return (
    <>
      <div className={styles.statsRow}>
        <StatCard label="Total billed" value={totalBilled != null ? fmtNgn(totalBilled) : '—'} icon="coin" sublabel={billing ? `across ${billing.length} record(s)` : undefined} />
        <StatCard label="Total paid" value={totalPaid != null ? fmtNgn(totalPaid) : '—'} icon="check" />
        <StatCard label="Outstanding" value={outstanding != null ? fmtNgn(outstanding) : '—'} icon="warn" />
      </div>

      <Card padding="none">
        <div className={styles.cardPad}>
          <SectionHead title="Billing records" />
        </div>
        <Table
          columns={[
            { title: 'Invoice' },
            { title: 'Container' },
            { title: 'Total NGN', align: 'right' },
            { title: 'Paid', align: 'right' },
            { title: 'Outstanding', align: 'right' },
            { title: 'Status' },
            { title: '', width: '60px' },
          ]}
          rows={(billing ?? []).map((b) => ({
            cells: [
              <Mono key="ref">{b.invoice_number ?? b.id.slice(0, 8)}</Mono>,
              <Mono key="cont">{b.container_number ?? '—'}</Mono>,
              <Mono key="total">{fmtNgn(Number(b.total_due_ngn))}</Mono>,
              <Mono key="paid" color="var(--color-success)">{fmtNgn(Number(b.total_paid_ngn))}</Mono>,
              <Mono key="out" color={Number(b.outstanding_ngn) > 0 ? 'var(--color-warning)' : 'var(--color-ink-3)'}>
                {Number(b.outstanding_ngn) > 0 ? fmtNgn(Number(b.outstanding_ngn)) : '—'}
              </Mono>,
              <StatusBadge key="status" kind="invoice" status={b.payment_status} />,
              <ViewLink key="view" onClick={() => onOpen(b)} />,
            ],
          }))}
          loading={billing === null}
          emptyState={billing?.length === 0 ? <EmptyState compact title="No billing records for this customer yet" /> : undefined}
        />
      </Card>
    </>
  )
}

function ClaimsTab({ claims, onOpen }: { claims: Claim[] | null; onOpen: (c: Claim) => void }): JSX.Element {
  return (
    <Card padding="none">
      <div className={styles.cardPad}>
        <SectionHead title="Damage claims" sub={claims ? `${claims.length} total` : undefined} />
      </div>
      <Table
        columns={[
          { title: 'Reference' },
          { title: 'Container' },
          { title: 'Status' },
          { title: 'Cartons', align: 'right' },
          { title: 'Filed' },
          { title: '', width: '60px' },
        ]}
        rows={(claims ?? []).map((c) => ({
          cells: [
            <Mono key="ref">{c.reference ?? c.id.slice(0, 8)}</Mono>,
            <Mono key="cont">{c.container_number ?? '—'}</Mono>,
            <StatusBadge key="status" kind="claim" status={c.status} />,
            <Mono key="cartons">{c.cartons_affected?.length ?? 0}</Mono>,
            <span key="filed" className={styles.smallMuted}>{formatDate(c.created_at)}</span>,
            <ViewLink key="view" onClick={() => onOpen(c)} />,
          ],
        }))}
        loading={claims === null}
        emptyState={claims?.length === 0 ? <EmptyState compact title="No claims filed by this customer" /> : undefined}
      />
    </Card>
  )
}

interface PrivacyTabProps {
  customer: Customer
  exporting: boolean
  readOnly: boolean
  onExport: () => void
  onAnonymise: () => void
}

function PrivacyTab({ customer, exporting, readOnly, onExport, onAnonymise }: PrivacyTabProps): JSX.Element {
  const isAnonymised = !!customer.anonymised_at
  return (
    <div className={styles.profileGrid}>
      <Card padding="default">
        <SectionHead title="Data export" sub="GDPR Art. 20 / NDPR — data portability" />
        <p className={styles.bodyText}>
          Downloads everything held about this customer — profile, shipments, billing, and claims —
          as a JSON bundle. Available even after anonymisation (financial records are retained).
        </p>
        <Button variant="secondary" icon="download" loading={exporting} onClick={onExport}>
          Export data (GDPR)
        </Button>
      </Card>

      <Card padding="default">
        <SectionHead title="Right to erasure" sub="GDPR Art. 17 / NDPR — anonymisation" />
        {isAnonymised ? (
          <p className={styles.bodyTextLast}>
            This record was anonymised on <strong>{formatDate(customer.anonymised_at)}</strong>. Personal
            data has been erased; the UUID and financial records are retained for legal compliance.
          </p>
        ) : (
          <>
            <p className={styles.bodyText}>
              Permanently erases the customer's personal data (name, email, phone, address, contract
              details). Irreversible — requires typed confirmation.
            </p>
            <Action variant="danger-ghost" disabled={readOnly} onClick={onAnonymise}>
              Erase data (GDPR)
            </Action>
          </>
        )}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TABS = [
  { key: 'profile', label: 'Profile' },
  { key: 'shipments', label: 'Shipments' },
  { key: 'billing', label: 'Billing' },
  { key: 'claims', label: 'Claims' },
  { key: 'privacy', label: 'Data & privacy' },
]

export function AdminCustomerDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { session } = useSession()
  const stateCustomer = (location.state as { customer?: Customer } | null)?.customer ?? null

  const qc = useQueryClient()

  const { data: customer = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: customerKeys.detail(id ?? ''),
    queryFn: () => customersApi.get(id!),
    enabled: !!id,
    ...(stateCustomer ? { initialData: stateCustomer } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(customer?.name)
  const [actionError, setActionError] = useState<string | null>(null)
  const [tab, setTab] = useState('profile')
  const [showAnonymise, setShowAnonymise] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [invitingAccount, setInvitingAccount] = useState(false)
  const [inviteMessage, setInviteMessage] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load customer.'
      : null)

  // Related records for the Profile tab's lifetime stats. Each is non-fatal:
  // `null` while loading, `[]` once settled, so a failed sub-fetch shows an
  // empty tab rather than breaking the page — the query errors are therefore
  // deliberately not surfaced.
  //
  // Note listForCustomer is correct here (unlike the customer-facing
  // MyShipments, where it was handed a user id): `id` is the customer id from
  // the route, and this page is staff-only.
  const shipmentParams = { customer_id: id ?? '', limit: 100 }
  const claimParams = { customer_id: id ?? '', limit: 100 }

  const shipmentsQ = useQuery({
    queryKey: packingListKeys.lookup(shipmentParams),
    queryFn: () => packingListApi.list(shipmentParams),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  const billingQ = useQuery({
    queryKey: billingKeys.forCustomer(id ?? ''),
    queryFn: () => billingApi.listForCustomer(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  const claimsQ = useQuery({
    queryKey: claimKeys.lookup(claimParams),
    queryFn: () => claimsApi.list(claimParams),
    enabled: !!id,
    staleTime: STALE_30S,
  })

  const shipments: PackingList[] | null = shipmentsQ.isPending ? null : (shipmentsQ.data?.data ?? [])
  const billing: Billing[] | null = billingQ.isPending ? null : (billingQ.data ?? [])
  const claims: Claim[] | null = claimsQ.isPending ? null : (claimsQ.data?.data ?? [])

  async function handleExport(): Promise<void> {
    if (!customer) return
    setExporting(true)
    setActionError(null)
    try {
      const data = await customersApi.export(customer.id)
      // Download as JSON file — never log PII to console
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `customer-export-${customer.id}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Export failed.')
    } finally {
      setExporting(false)
    }
  }

  async function handleSendInvite(): Promise<void> {
    if (!customer) return
    setInvitingAccount(true)
    setInviteMessage(null)
    try {
      const invite = await customersApi.invite(customer.id)
      toast.success('Invite created', customer.name ?? undefined)
      setInviteMessage(
        `Invite sent via ${invite.sent_channel.toUpperCase()} to ${invite.sent_to_masked ?? 'the customer'}. ` +
          `Expires ${formatDateTime(invite.expires_at)}.`
      )
    } catch (err) {
      setInviteMessage(err instanceof ApiError ? err.message : 'Could not send the account invite.')
    } finally {
      setInvitingAccount(false)
    }
  }

  if (loading && !customer) return <PageSkeleton kind="detail" label="Loading the page" />
  if (error && !customer) return <div className={styles.banner}><Banner variant="error">{error}</Banner></div>
  if (!customer) return <></>

  const isAnonymised = !!customer.anonymised_at
  const hasLogin = !!customer.user_id

  const heroMeta: ReactNode[] = []
  if (customer.phone) heroMeta.push(<Mono key="phone">{customer.phone}</Mono>)
  if (customer.email) heroMeta.push(<span key="email">{customer.email}</span>)
  if (customer.created_at) heroMeta.push(<span key="since">Customer since {formatDate(customer.created_at)}</span>)

  return (
    <div>
      {session?.readOnly && (
        <div className={styles.bannerGap}>
          <Banner variant="warning" icon="eye" title="Read-only session">
            You're viewing this tenant as their Tenant Admin for support. Data is fully visible, but every create, edit, approve, and delete action is disabled. The session ends automatically after 30 minutes or when you exit.
          </Banner>
        </div>
      )}

      {/* Hero — prototype 3.6 */}
      <div className={styles.customerHero}>
        <div className={styles.customerHeroId}>
          <Avatar size={64} name={customer.name ?? '?'} />
          <div>
            <div className={styles.customerHeroTitleRow}>
              <h1 className={styles.customerHeroName}>{customer.name ?? 'Anonymised customer'}</h1>
              <Badge variant={isAnonymised ? 'error' : 'success'}>{isAnonymised ? 'Anonymised' : 'Active'}</Badge>
              {!isAnonymised && hasLogin && <Badge variant="info">Has portal login</Badge>}
              {!isAnonymised && !hasLogin && customer.pending_invite_expires_at && (
                <Badge variant="warning">
                  Invited · expires {formatDate(customer.pending_invite_expires_at)}
                </Badge>
              )}
              {!isAnonymised && !hasLogin && !customer.pending_invite_expires_at && (
                <Badge variant="warning">No login</Badge>
              )}
            </div>
            {heroMeta.length > 0 && (
              <div className={styles.customerHeroMeta}>
                {heroMeta.map((node, i) => (
                  <span key={i} className={styles.customerHeroMetaItem}>
                    {i > 0 && <span className={styles.customerHeroDot}>·</span>}
                    {node}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className={styles.actionsRow}>
          {!isAnonymised && (
            <Action
              variant="secondary"
              disabled={!!session?.readOnly}
              loading={invitingAccount}
              onClick={() => void handleSendInvite()}
            >
              {hasLogin ? 'Resend account invite' : 'Send account invite'}
            </Action>
          )}
        </div>
      </div>

      {inviteMessage && (
        <div className={styles.banner}>
          <Banner variant="info" title="Account invite" dismissible onDismiss={() => setInviteMessage(null)}>
            {inviteMessage}
          </Banner>
        </div>
      )}

      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}

      {/* GDPR anonymised banner — persistent, per spec */}
      {isAnonymised && (
        <div className={styles.gdprBanner}>
          <p className={styles.gdprBannerTitle}>This record has been anonymised (GDPR Art. 17)</p>
          <p className={styles.gdprBannerBody}>
            All personal data was erased on {formatDate(customer.anonymised_at)}. The customer
            UUID and financial records are retained for legal compliance.
          </p>
        </div>
      )}

      <Tabs items={TABS} active={tab} onChange={setTab} />
      <div className={styles.spacer16} />

      {tab === 'profile' && <ProfileTab customer={customer} shipments={shipments} billing={billing} claims={claims} onSaved={(updated) => qc.setQueryData(customerKeys.detail(id ?? ''), updated)} />}
      {tab === 'shipments' && (
        <ShipmentsTab customer={customer} shipments={shipments} onOpen={(plId) => navigate(`/packing-lists/${plId}`)} />
      )}
      {tab === 'billing' && (
        <BillingTab billing={billing} onOpen={(b) => navigate(`/billing/${b.id}`, { state: { billing: b } })} />
      )}
      {tab === 'claims' && (
        <ClaimsTab claims={claims} onOpen={(c) => navigate(`/claims/${c.id}`, { state: { claim: c } })} />
      )}
      {tab === 'privacy' && (
        <PrivacyTab
          customer={customer}
          exporting={exporting}
          readOnly={!!session?.readOnly}
          onExport={() => void handleExport()}
          onAnonymise={() => setShowAnonymise(true)}
        />
      )}

      {showAnonymise && (
        <AnonymiseModal
          customer={customer}
          onCancel={() => setShowAnonymise(false)}
          onSuccess={() => {
            setShowAnonymise(false)
          }}
        />
      )}
    </div>
  )
}
