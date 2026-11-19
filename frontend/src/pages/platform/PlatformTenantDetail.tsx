import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { platformApi, type Tenant, type TenantStatus } from '../../api/tenantManagement'
import { platformTenantKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, Field, Kvp, Mono, Table, UserCell, DialogGuard, type BadgeVariant } from '../../design/components'
import {
  platformApi as platformExtras,
  type OffboardingExport,
  type PlanLimits,
} from '../../api/tenantManagement'
import {
  useOffboardingExport,
  usePlatformTenantAudit,
  usePlatformTenantConfig,
  usePlatformTenantUsers,
} from '../../hooks/usePlatformTenants'
import { Tabs } from '../../shell/Tabs'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'
import { formatCount, formatDate, formatDateTime } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

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
              Offboarding is permanent. The tenant's data will be scheduled for deletion in 90 days. A full export of
              it is prepared within the hour; download it from this page and hand it to the tenant before then.
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

function loadErrorMessage(err: unknown, fallback: string): string | null {
  if (!err) return null
  return err instanceof ApiError ? err.message : fallback
}

function UsersTab({ tenantId }: { tenantId: string }): JSX.Element {
  const { data: users = [], isLoading: loading, error: loadError } = usePlatformTenantUsers(tenantId)
  const error = loadErrorMessage(loadError, 'Could not load users.')

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
        emptyState={<span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>{loading ? 'Loading users…' : 'No staff users.'}</span>}
      />
    </Card>
  )
}

function QuotaBar({ label, used, max }: { label: string; used: number; max: number }): JSX.Element {
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0
  const color = pct >= 100 ? 'var(--color-error)' : pct >= 80 ? 'var(--color-warning)' : 'var(--color-primary)'
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)', marginBottom: 4 }}>
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
        <div style={{ display: 'flex', gap: 20, fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginTop: 8 }}>
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
  const { data: config = null, error: loadError } = usePlatformTenantConfig(tenantId)
  const error = loadErrorMessage(loadError, 'Could not load config.')

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
          value={<Mono style={{ fontSize: 'var(--text-xs)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{JSON.stringify(value)}</Mono>}
          divider={i < arr.length - 1}
        />
      ))}
    </Card>
  )
}

function AuditTab({ tenantId }: { tenantId: string }): JSX.Element {
  const { data, isLoading: loading, error: loadError } = usePlatformTenantAudit(tenantId)
  const entries = data?.data ?? []
  const error = loadErrorMessage(loadError, 'Could not load audit entries.')

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
        emptyState={<span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>{loading ? 'Loading…' : 'No platform-level audit entries for this tenant.'}</span>}
      />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Offboarding data export (audit BE-10)
// ---------------------------------------------------------------------------

const EXPORT_STATUS: Record<OffboardingExport['status'], { label: string; variant: BadgeVariant }> = {
  none: { label: 'Not queued', variant: 'warning' },
  pending: { label: 'Queued', variant: 'info' },
  running: { label: 'Being written', variant: 'info' },
  completed: { label: 'Ready', variant: 'success' },
  failed: { label: 'Failed', variant: 'error' },
  cancelled: { label: 'Cancelled', variant: 'neutral' },
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Send the browser to a signed download URL. The server marks it as an attachment, so the page stays put. */
function startDownload(url: string): void {
  window.location.assign(url)
}

function OffboardingExportCard({ tenantId }: { tenantId: string }): JSX.Element {
  const { data: exportInfo, error: loadError } = useOffboardingExport(tenantId, true)
  const [busy, setBusy] = useState<'download' | 'queue' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const error = actionError ?? loadErrorMessage(loadError, 'Could not load the export.')

  async function run(kind: 'download' | 'queue'): Promise<void> {
    setBusy(kind)
    setActionError(null)
    try {
      if (kind === 'download') startDownload((await platformExtras.offboardingExportLink(tenantId)).download_url)
      else await platformExtras.queueOffboardingExport(tenantId)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : kind === 'download' ? 'Could not start the download.' : 'Could not queue the export.')
    } finally {
      setBusy(null)
    }
  }

  const status = exportInfo ? EXPORT_STATUS[exportInfo.status] : null
  return (
    <Card padding={20}>
      <SectionHead
        title="Data export"
        sub="Everything the tenant kept on ShipX, as one archive (JSON Lines). Hand it over before the data is deleted."
      />
      {error && <div style={{ margin: '8px 0' }}><Banner variant="error" title="Error">{error}</Banner></div>}
      {!exportInfo && !error && <p style={{ color: 'var(--color-ink-3)' }}>Loading export…</p>}
      {exportInfo && status && (
        <>
          <Kvp label="Status" value={<Badge variant={status.variant}>{status.label}</Badge>} />
          {exportInfo.status === 'completed' && (
            <>
              <Kvp label="Prepared" value={formatDateTime(exportInfo.completed_at)} />
              {exportInfo.size_bytes !== null && <Kvp label="Size" value={formatBytes(exportInfo.size_bytes)} />}
              {exportInfo.row_count !== null && <Kvp label="Records" value={formatCount(exportInfo.row_count)} />}
              {exportInfo.sha256 && (
                <Kvp label="SHA-256" value={<Mono style={{ fontSize: 'var(--text-xs)', wordBreak: 'break-all' }}>{exportInfo.sha256}</Mono>} />
              )}
            </>
          )}
          {(exportInfo.status === 'pending' || exportInfo.status === 'running') && (
            <p style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>The export runs within the hour. This page checks again every minute.</p>
          )}
          {exportInfo.retrying && (
            <p style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>
              Attempt {exportInfo.attempts} of {exportInfo.max_attempts} failed. It is tried again within the hour.
            </p>
          )}
          {exportInfo.status === 'failed' && !exportInfo.retrying && (
            <p style={{ color: 'var(--color-error)', fontSize: 'var(--text-sm)' }}>
              Every attempt failed. Check the export job's logs (runbook: "Offboarding export failed"), then queue it again.
            </p>
          )}
          {exportInfo.deletion_scheduled_at && (
            <Kvp
              label="Data deleted on"
              value={formatDate(exportInfo.deletion_scheduled_at)}
              divider={false}
            />
          )}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
            {exportInfo.can_queue && (
              <Button variant="secondary" loading={busy === 'queue'} disabled={busy !== null} onClick={() => void run('queue')}>
                Queue export
              </Button>
            )}
            {exportInfo.status === 'completed' && (
              <Button variant="primary" icon="download" loading={busy === 'download'} disabled={busy !== null} onClick={() => void run('download')}>
                Download archive
              </Button>
            )}
          </div>
          {exportInfo.status === 'completed' && (
            <p style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)', textAlign: 'right', marginTop: 6 }}>
              The link works for five minutes and every download is recorded in the audit log.
            </p>
          )}
        </>
      )}
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
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(tenant?.company_name)

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
          <div className={styles.tenantActions}>
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
        <Kvp label="Tenant ID" value={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}>{tenant.id}</span>} divider={false} />
      </Card>
      {tenant.status === 'offboarded' && (
        <div style={{ marginTop: 16 }}>
          <OffboardingExportCard tenantId={tenant.id} />
        </div>
      )}
      </>
      )}

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
