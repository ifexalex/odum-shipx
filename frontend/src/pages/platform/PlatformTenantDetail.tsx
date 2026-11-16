import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { platformApi, type Tenant, type TenantStatus } from '../../api/tenantManagement'
import { platformTenantKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, Field, Kvp, Mono, Table, UserCell, DialogGuard, type BadgeVariant } from '../../design/components'
import {
  platformApi as platformExtras,
  type PlanLimits,
  type TenantUser,
} from '../../api/tenantManagement'
import { Tabs } from '../../shell/Tabs'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'
import { formatDate, formatDateTime } from '../../lib/format'

const STATUS_VARIANT: Record<TenantStatus, BadgeVariant> = {
  active: 'success',
  suspended: 'error',
  offboarded: 'neutral',
}

interface ActionModalProps {
  action: 'suspend' | 'activate' | 'offboard'
  tenant: Tenant
  onCancel: () => void
  onSuccess: (updated: Tenant) => void
}

function ActionModal({ action, tenant, onCancel, onSuccess }: ActionModalProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const needsReason = action === 'suspend' || action === 'offboard'
  const canSubmit = !needsReason || reason.trim().length > 0

  const LABELS = {
    suspend: { title: 'Suspend tenant', button: 'Suspend', variant: 'danger' as const },
    activate: { title: 'Lift suspension', button: 'Activate', variant: 'success' as const },
    offboard: { title: 'Offboard tenant', button: 'Offboard permanently', variant: 'danger' as const },
  }
  const label = LABELS[action]

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      let updated: Tenant
      if (action === 'suspend') updated = await platformApi.suspendTenant(tenant.id, reason)
      else if (action === 'activate') updated = await platformApi.activateTenant(tenant.id)
      else updated = await platformApi.offboardTenant(tenant.id, reason)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>{label.title} — {tenant.company_name}</h3>
        {error && <div className={styles.modalBanner}><Banner variant="error">{error}</Banner></div>}
        {action === 'offboard' && (
          <div className={styles.modalBanner}>
            <Banner variant="error">
              Offboarding is permanent. The tenant's data will be scheduled for deletion in 90 days.
            </Banner>
          </div>
        )}
        {needsReason && (
          <Field label="Reason" name="reason" required multiline value={reason} onChange={(e) => setReason(e.target.value)} />
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant={label.variant} loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            {label.button}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TenantDetail tabs (prototype 2.4): Users / Usage & quota / Config / Audit
// ---------------------------------------------------------------------------

function UsersTab({ tenantId }: { tenantId: string }): JSX.Element {
  const [users, setUsers] = useState<TenantUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        setUsers(await platformExtras.tenantUsers(tenantId))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load users.')
      } finally {
        setLoading(false)
      }
    })()
  }, [tenantId])

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  return (
    <Card padding={0}>
      <Table
        columns={[{ title: 'User' }, { title: 'Role' }, { title: 'Status' }, { title: 'Locale' }]}
        rows={users.map((u) => ({
          cells: [
            <UserCell key="u" name={u.full_name} email={u.email} />,
            <Badge key="r" variant="info">{u.role.replace(/_/g, ' ')}</Badge>,
            <Badge key="s" variant={u.status === 'active' ? 'success' : 'neutral'}>{u.status}</Badge>,
            <Mono key="l">{u.locale ?? 'en'}</Mono>,
          ],
        }))}
        emptyState={<span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>{loading ? 'Loading users…' : 'No staff users.'}</span>}
      />
    </Card>
  )
}

function QuotaBar({ label, used, max }: { label: string; used: number; max: number }): JSX.Element {
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0
  const color = pct >= 100 ? 'var(--color-error)' : pct >= 80 ? 'var(--color-warning)' : 'var(--color-primary)'
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
        <span style={{ fontWeight: 600, color: 'var(--color-ink-2)' }}>{label}</span>
        <Mono>{used} / {max >= 999999 ? '∞' : max}</Mono>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: 'var(--color-surface-muted)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4 }} />
      </div>
    </div>
  )
}

function UsageTab({ tenantId }: { tenantId: string }): JSX.Element {
  const { data: usage = null, error: loadError } = useQuery({
    queryKey: platformTenantKeys.usage(tenantId),
    queryFn: () => platformExtras.tenantUsage(tenantId),
    enabled: !!tenantId,
    staleTime: STALE_30S,
  })
  const [override, setOverride] = useState<{ users: string; containers: string; storage: string }>({ users: '', containers: '', storage: '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load usage.'
      : null)

  async function handleOverride(): Promise<void> {
    setSaving(true)
    setActionError(null)
    setSaved(false)
    try {
      const body: Partial<PlanLimits> = {}
      if (override.users) body.users = Number(override.users)
      if (override.containers) body.containers_per_month = Number(override.containers)
      if (override.storage) body.storage_gb = Number(override.storage)
      await platformExtras.setQuotaOverride(tenantId, body)
      setSaved(true)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not set override.')
    } finally {
      setSaving(false)
    }
  }

  if (error && !usage) return <Banner variant="error" title="Error">{error}</Banner>
  if (!usage) return <p style={{ color: 'var(--color-ink-3)' }}>Loading usage…</p>

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <Card padding={24}>
        <SectionHead title={`Usage — ${usage.period}`} sub={`Tier: ${usage.subscription_tier}`} />
        <div style={{ height: 12 }} />
        <QuotaBar label="Staff users" used={usage.limits.users.used} max={usage.limits.users.max} />
        <QuotaBar label="Containers this month" used={usage.limits.containers_per_month.used} max={usage.limits.containers_per_month.max} />
        <QuotaBar label="Storage (GB)" used={usage.limits.storage_gb.used} max={usage.limits.storage_gb.max} />
        <div style={{ display: 'flex', gap: 20, fontSize: 12, color: 'var(--color-ink-3)', marginTop: 8 }}>
          <span>API calls: <Mono>{usage.api_calls}</Mono></span>
          <span>SMS: <Mono>{usage.notifications.sms_sent}</Mono></span>
          <span>WhatsApp: <Mono>{usage.notifications.whatsapp_sent}</Mono></span>
          <span>Email: <Mono>{usage.notifications.emails_sent}</Mono></span>
        </div>
      </Card>

      <Card padding={24}>
        <SectionHead title="Quota override" sub="Wins over tier defaults and plan overrides. Leave a field blank to keep the plan value; submit all-blank to clear the override." />
        {error && <div style={{ margin: '8px 0' }}><Banner variant="error" title="Error">{error}</Banner></div>}
        {saved && <div style={{ margin: '8px 0' }}><Banner variant="success" title="Saved">Override applied — bars above show the new effective limits.</Banner></div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginTop: 12 }}>
          <Field label="Users" name="ovr_users" type="number" optional value={override.users} onChange={(e) => setOverride((p) => ({ ...p, users: e.target.value }))} />
          <Field label="Containers / month" name="ovr_containers" type="number" optional value={override.containers} onChange={(e) => setOverride((p) => ({ ...p, containers: e.target.value }))} />
          <Field label="Storage (GB)" name="ovr_storage" type="number" optional value={override.storage} onChange={(e) => setOverride((p) => ({ ...p, storage: e.target.value }))} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button variant="primary" size="sm" icon="check" loading={saving} onClick={() => void handleOverride()}>
            Apply override
          </Button>
        </div>
      </Card>
    </div>
  )
}

function ConfigTab({ tenantId }: { tenantId: string }): JSX.Element {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        setConfig(await platformExtras.tenantConfig(tenantId))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load config.')
      }
    })()
  }, [tenantId])

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  if (!config) return <p style={{ color: 'var(--color-ink-3)' }}>Loading config…</p>

  return (
    <Card padding={20}>
      <SectionHead title="Tenant configuration" sub="Read-only view — secrets are masked server-side" />
      <div style={{ height: 8 }} />
      {Object.entries(config).map(([key, value], i, arr) => (
        <Kvp
          key={key}
          label={key.replace(/_/g, ' ')}
          value={<Mono style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{JSON.stringify(value)}</Mono>}
          divider={i < arr.length - 1}
        />
      ))}
    </Card>
  )
}

function AuditTab({ tenantId }: { tenantId: string }): JSX.Element {
  const [entries, setEntries] = useState<{ id: string; action: string; created_at: string; ip_address: string | null }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const result = await platformExtras.auditLog({ tenant_id: tenantId, limit: 50 })
        setEntries(result.data)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load audit entries.')
      } finally {
        setLoading(false)
      }
    })()
  }, [tenantId])

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  return (
    <Card padding={0}>
      <Table
        columns={[{ title: 'Timestamp' }, { title: 'Action' }, { title: 'IP' }]}
        rows={entries.map((e) => ({
          cells: [
            <Mono key="ts">{formatDateTime(e.created_at, { year: false })}</Mono>,
            <Badge key="a" variant="info">{e.action.replace(/_/g, ' ')}</Badge>,
            <Mono key="ip" color="var(--color-ink-4)">{e.ip_address ?? '—'}</Mono>,
          ],
        }))}
        emptyState={<span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>{loading ? 'Loading…' : 'No platform-level audit entries for this tenant.'}</span>}
      />
    </Card>
  )
}

export function PlatformTenantDetail(): JSX.Element {
  const { startImpersonation } = useSession()
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const stateTenant = (location.state as { tenant?: Tenant } | null)?.tenant ?? null

  const qc = useQueryClient()

  const { data: tenant = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: platformTenantKeys.detail(id ?? ''),
    queryFn: () => platformApi.getTenant(id!),
    enabled: !!id,
    ...(stateTenant ? { initialData: stateTenant } : {}),
    staleTime: STALE_30S,
  })

  const [activeModal, setActiveModal] = useState<'suspend' | 'activate' | 'offboard' | null>(null)
  const [tab, setTab] = useState('overview')
  const [impersonating, setImpersonating] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)

  const error =
    pageError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load tenant.'
      : null)

  async function handleImpersonate(): Promise<void> {
    if (!tenant) return
    setImpersonating(true)
    try {
      const result = await platformApi.impersonate(tenant.id)
      startImpersonation(result.token, tenant.company_name)
      navigate('/dashboard')
    } catch (err) {
      setPageError(err instanceof ApiError ? err.message : 'Could not start impersonation.')
      setImpersonating(false)
    }
  }

  if (loading && !tenant) return <div style={{ padding: 48, color: 'var(--color-text-muted)' }}>Loading…</div>
  if (error && !tenant) return <div className={styles.banner}><Banner variant="error">{error}</Banner></div>
  if (!tenant) return <></>

  return (
    <div>
      <PageHeader
        title={tenant.company_name}
        subtitle={tenant.slug}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            {tenant.status === 'active' && (
              <Button variant="secondary" icon="eye" loading={impersonating} onClick={() => void handleImpersonate()}>
                Impersonate
              </Button>
            )}
            {tenant.status === 'active' && (
              <Button variant="danger-outline" onClick={() => setActiveModal('suspend')}>Suspend</Button>
            )}
            {tenant.status === 'suspended' && (
              <Button variant="success" onClick={() => setActiveModal('activate')}>Lift suspension</Button>
            )}
            {tenant.status !== 'offboarded' && (
              <Button variant="danger" onClick={() => setActiveModal('offboard')}>Offboard</Button>
            )}
          </div>
        }
      />

      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}

      <Tabs
        items={[
          { key: 'overview', label: 'Overview' },
          { key: 'users', label: 'Users' },
          { key: 'usage', label: 'Usage & quota' },
          { key: 'config', label: 'Configuration' },
          { key: 'audit', label: 'Audit log' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'users' && <UsersTab tenantId={tenant.id} />}
      {tab === 'usage' && <UsageTab tenantId={tenant.id} />}
      {tab === 'config' && <ConfigTab tenantId={tenant.id} />}
      {tab === 'audit' && <AuditTab tenantId={tenant.id} />}

      {tab === 'overview' && (
      <>
      <SectionHead title="Tenant details" />
      <Card padding={20}>
        <Kvp label="Status" value={<Badge variant={STATUS_VARIANT[tenant.status]}>{tenant.status}</Badge>} />
        <Kvp label="Subscription" value={<span style={{ textTransform: 'capitalize' }}>{tenant.subscription_tier}</span>} />
        <Kvp label="Contact email" value={tenant.primary_contact_email} />
        {tenant.primary_contact_phone && <Kvp label="Contact phone" value={tenant.primary_contact_phone} />}
        <Kvp label="Created" value={formatDate(tenant.created_at)} />
        {tenant.offboarded_at && <Kvp label="Offboarded" value={formatDate(tenant.offboarded_at)} />}
        {tenant.reactivated_at && <Kvp label="Reactivated" value={formatDate(tenant.reactivated_at)} />}
        <Kvp label="Tenant ID" value={<span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}>{tenant.id}</span>} divider={false} />
      </Card>
      </>
      )}

      <div style={{ marginTop: 24 }}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/platform/tenants')}>Back to tenants</Button>
      </div>

      {activeModal && (
        <ActionModal
          action={activeModal}
          tenant={tenant}
          onCancel={() => setActiveModal(null)}
          onSuccess={(updated) => {
            qc.setQueryData(platformTenantKeys.detail(id ?? ''), updated)
            setActiveModal(null)
          }}
        />
      )}
    </div>
  )
}
