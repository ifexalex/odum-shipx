import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { platformApi, type SubscriptionTier, type Tenant } from '../../api/tenantManagement'
import { platformTenantKeys } from '../../api/keys'
import { describeOutcome } from '../../api/platformSecurity'
import { useCanPlatform } from '../../hooks/usePlatformSecurity'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, ConfirmDialog, Field, Kvp, Modal, Mono, Select, StatusBadge, Table, UserCell, LinesSkeleton, PageSkeleton, EmptyState } from '../../design/components'
import {
  platformApi as platformExtras,
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
import { toast } from '../../design/toast'
import { Section } from '../../shell/Section'
import { DetailPage } from '../../shell/DetailPage'

interface ActionModalProps {
  action: 'suspend' | 'activate' | 'offboard'
  tenant: Tenant
  onCancel: () => void
  onSuccess: (updated: Tenant) => void
}

function ActionModal({ action, tenant, onCancel, onSuccess }: ActionModalProps): JSX.Element {
  const [reason, setReason] = useState('')
  const [confirmSlug, setConfirmSlug] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const needsReason = action === 'suspend' || action === 'offboard'
  // Typing the slug is what stands in for a second admin when there is none (decision D4); asked every time.
  const slugConfirmed = action !== 'offboard' || confirmSlug.trim().toLowerCase() === tenant.slug.toLowerCase()
  const canSubmit = (!needsReason || reason.trim().length > 0) && slugConfirmed

  const LABELS = {
    suspend: { title: 'Suspend tenant', button: 'Suspend', variant: 'danger' as const },
    activate: { title: 'Lift suspension', button: 'Activate', variant: 'primary' as const },
    offboard: { title: 'Offboard tenant', button: 'Offboard permanently', variant: 'danger' as const },
  }
  const label = LABELS[action]

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      if (action === 'offboard') {
        // Offboarding needs a second admin (decision D4): it usually waits; it runs now only for a sole admin.
        const outcome = await platformApi.offboardTenant(tenant.id, reason, confirmSlug.trim())
        if (outcome.outcome === 'executed' && outcome.result) {
          toast.success('Tenant offboarded', outcome.result.company_name)
          onSuccess(outcome.result)
        } else {
          toast.success(outcome.outcome === 'scheduled' ? 'Offboarding scheduled' : 'Sent for approval', describeOutcome(outcome))
          onCancel()
        }
        return
      }
      const updated =
        action === 'suspend'
          ? await platformApi.suspendTenant(tenant.id, reason)
          : await platformApi.activateTenant(tenant.id)
      toast.success(action === 'suspend' ? 'Tenant suspended' : 'Suspension lifted', updated.company_name)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Action failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onCancel} title={`${label.title} — ${tenant.company_name}`} size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        {action === 'offboard' && (
          <Banner variant="error">
            Offboarding is permanent. The tenant&apos;s data will be scheduled for deletion in 90 days. A full export of
            it is prepared within the hour; download it from this page and hand it to the tenant before then.
          </Banner>
        )}
        {needsReason && (
          <Field label="Reason" name="reason" required multiline value={reason} onChange={(e) => setReason(e.target.value)} />
        )}
        {action === 'offboard' && (
          <>
            <Field
              label={`Type ${tenant.slug} to confirm`}
              name="confirm_slug"
              required
              autoComplete="off"
              value={confirmSlug}
              onChange={(e) => setConfirmSlug(e.target.value)}
            />
            <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
              Another platform admin must approve this before it runs. If there is no one else to ask, it runs 24 hours
              from now unless cancelled, and the owners are emailed.
            </p>
          </>
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant={label.variant} loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            {label.button}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Edit tenant (audit PA-09): the backend's PATCH had no screen, so a plan could not be changed from the console
// ---------------------------------------------------------------------------

const TIER_OPTIONS: { value: SubscriptionTier; label: string }[] = [
  { value: 'starter', label: 'Starter' },
  { value: 'business', label: 'Business' },
  { value: 'enterprise', label: 'Enterprise' },
]

interface EditTenantModalProps {
  tenant: Tenant
  onCancel: () => void
  onSuccess: (updated: Tenant) => void
}

function EditTenantModal({ tenant, onCancel, onSuccess }: EditTenantModalProps): JSX.Element {
  const [companyName, setCompanyName] = useState(tenant.company_name)
  const [contactEmail, setContactEmail] = useState(tenant.primary_contact_email)
  const [tier, setTier] = useState<SubscriptionTier>(tenant.subscription_tier)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Only what changed is sent, so the audit row records exactly what the admin edited.
  const changes = {
    ...(companyName.trim() !== tenant.company_name ? { company_name: companyName.trim() } : {}),
    ...(contactEmail.trim() !== tenant.primary_contact_email ? { primary_contact_email: contactEmail.trim() } : {}),
    ...(tier !== tenant.subscription_tier ? { subscription_tier: tier } : {}),
  }
  const canSubmit = Object.keys(changes).length > 0 && companyName.trim() !== '' && contactEmail.trim() !== ''

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await platformApi.updateTenant(tenant.id, changes)
      toast.success('Tenant updated', updated.company_name)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update the tenant.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onCancel} title={`Edit ${tenant.company_name}`} size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        <Field label="Company name" name="company_name" required value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
        <Field
          label="Contact email"
          name="primary_contact_email"
          type="email"
          required
          value={contactEmail}
          onChange={(e) => setContactEmail(e.target.value)}
        />
        <Select label="Plan" value={tier} onChange={(e) => setTier(e.target.value as SubscriptionTier)}>
          {TIER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        {tier !== tenant.subscription_tier && (
          <Banner variant="info">
            The new plan&apos;s limits apply at once. Billing for the plan is still handled outside ShipX.
          </Banner>
        )}
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Save changes
          </Button>
        </div>
      </div>
    </Modal>
  )
}

/** "CODE: sentence" notices from the reactivate route, shown as plain sentences. */
function noticeText(notice: string): string {
  const colon = notice.indexOf(':')
  return colon >= 0 ? notice.slice(colon + 1).trim() : notice
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
    <Card padding="none">
      <Table
        columns={[{ title: 'User' }, { title: 'Role' }, { title: 'Status', type: 'status' }, { title: 'Locale' }]}
        rows={users.map((u) => ({
          cells: [
            <UserCell key="u" name={u.full_name} email={u.email} />,
            <Badge key="r" variant="info">{u.role.replace(/_/g, ' ')}</Badge>,
            <StatusBadge key="s" kind="staffUser" status={u.status} />,
            <Mono key="l">{u.locale ?? 'en'}</Mono>,
          ],
        }))}
        emptyState={loading ? <LinesSkeleton label="Loading users" /> : <EmptyState compact title="No staff users" />}
      />
    </Card>
  )
}

function QuotaBar({ label, used, max }: { label: string; used: number; max: number }): JSX.Element {
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0
  const color = pct >= 100 ? 'var(--color-error)' : pct >= 80 ? 'var(--color-warning)' : 'var(--color-primary)'
  return (
    <div style={{ marginBottom: 'var(--space-4)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'var(--text-xs)', marginBottom: 'var(--space-1)' }}>
        <span style={{ fontWeight: 600, color: 'var(--color-ink-2)' }}>{label}</span>
        <Mono>{used} / {max >= 999999 ? '∞' : max}</Mono>
      </div>
      <div style={{ height: 8, borderRadius: 'var(--radius-sm)', background: 'var(--color-surface-muted)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 'var(--radius-sm)' }} />
      </div>
    </div>
  )
}

function UsageTab({ tenantId }: { tenantId: string }): JSX.Element {
  const qc = useQueryClient()
  const { data: usage = null, error: loadError } = useQuery({
    queryKey: platformTenantKeys.usage(tenantId),
    queryFn: () => platformExtras.tenantUsage(tenantId),
    enabled: !!tenantId,
    staleTime: STALE_30S,
  })
  const [override, setOverride] = useState<{ users: string; containers: string; storage: string }>({ users: '', containers: '', storage: '' })
  const [saving, setSaving] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load usage.'
      : null)

  const hasOverrideInput =
    override.users.trim() !== '' || override.containers.trim() !== '' || override.storage.trim() !== ''

  async function handleOverride(): Promise<void> {
    if (!hasOverrideInput) return
    setSaving(true)
    setActionError(null)
    try {
      const body: Partial<PlanLimits> = {}
      if (override.users.trim()) body.users = Number(override.users)
      if (override.containers.trim()) body.containers_per_month = Number(override.containers)
      if (override.storage.trim()) body.storage_gb = Number(override.storage)
      await platformExtras.setQuotaOverride(tenantId, body)
      await qc.invalidateQueries({ queryKey: platformTenantKeys.usage(tenantId) })
      toast.success('Plan override applied', 'The bars above show the new limits.')
      setOverride({ users: '', containers: '', storage: '' })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not set override.')
    } finally {
      setSaving(false)
    }
  }

  async function handleResetOverride(): Promise<void> {
    setSaving(true)
    setActionError(null)
    try {
      await platformExtras.setQuotaOverride(tenantId, {})
      await qc.invalidateQueries({ queryKey: platformTenantKeys.usage(tenantId) })
      setConfirmReset(false)
      setOverride({ users: '', containers: '', storage: '' })
      toast.success('Overrides cleared', 'This tenant now uses its plan tier defaults.')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not reset overrides.')
    } finally {
      setSaving(false)
    }
  }

  if (error && !usage) return <Banner variant="error" title="Error">{error}</Banner>
  if (!usage) return <PageSkeleton kind="detail" label="Loading usage" />

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Card padding="large">
        <SectionHead title={`Usage — ${usage.period}`} sub={`Tier: ${usage.subscription_tier}`} />
        <div style={{ height: 12 }} />
        <QuotaBar label="Staff users" used={usage.limits.users.used} max={usage.limits.users.max} />
        <QuotaBar label="Containers this month" used={usage.limits.containers_per_month.used} max={usage.limits.containers_per_month.max} />
        <QuotaBar label="Storage (GB)" used={usage.limits.storage_gb.used} max={usage.limits.storage_gb.max} />
        <div style={{ display: 'flex', gap: 'var(--space-5)', fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginTop: 'var(--space-2)', flexWrap: 'wrap' }}>
          <span>API calls: <Mono>{usage.api_calls}</Mono></span>
          <span>SMS: <Mono>{usage.notifications.sms_sent}</Mono></span>
          <span>WhatsApp: <Mono>{usage.notifications.whatsapp_sent}</Mono></span>
          <span>Email: <Mono>{usage.notifications.emails_sent}</Mono></span>
        </div>
      </Card>

      <Card padding="large">
        <SectionHead title="Quota override" sub="Wins over tier defaults and plan overrides. Enter only the limits you want to override." />
        {error && <div style={{ margin: 'var(--space-2) 0' }}><Banner variant="error" title="Error">{error}</Banner></div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
          <Field label="Users" name="ovr_users" type="number" optional value={override.users} onChange={(e) => setOverride((p) => ({ ...p, users: e.target.value }))} />
          <Field label="Containers / month" name="ovr_containers" type="number" optional value={override.containers} onChange={(e) => setOverride((p) => ({ ...p, containers: e.target.value }))} />
          <Field label="Storage (GB)" name="ovr_storage" type="number" optional value={override.storage} onChange={(e) => setOverride((p) => ({ ...p, storage: e.target.value }))} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap', marginTop: 'var(--space-3)' }}>
          <Button variant="danger-ghost" size="sm" disabled={saving} onClick={() => setConfirmReset(true)}>
            Reset to plan defaults
          </Button>
          <Button variant="primary" size="sm" icon="check" loading={saving} disabled={!hasOverrideInput} onClick={() => void handleOverride()}>
            Apply override
          </Button>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmReset}
        title="Reset quota overrides?"
        confirmLabel="Reset to plan defaults"
        undo="You can set a new per-tenant override at any time."
        busy={saving}
        error={actionError}
        onConfirm={() => void handleResetOverride()}
        onCancel={() => setConfirmReset(false)}
      >
        Clears all custom quota limits for this tenant so it reverts to its {usage.subscription_tier} tier limits.
      </ConfirmDialog>
    </div>
  )
}

function formatConfigValue(value: unknown): JSX.Element {
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: 'var(--color-ink-4)' }}>Not set</span>
  }
  if (typeof value === 'boolean') {
    return <Badge variant={value ? 'success' : 'neutral'} size="sm" dot={false}>{value ? 'Enabled' : 'Disabled'}</Badge>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: 'var(--color-ink-4)' }}>None</span>
    return <Mono style={{ fontSize: 'var(--text-xs)' }}>{value.map((v) => String(v)).join(', ')}</Mono>
  }
  if (typeof value === 'object') {
    return <Mono style={{ fontSize: 'var(--text-xs)' }}>{JSON.stringify(value)}</Mono>
  }
  return <Mono style={{ fontSize: 'var(--text-xs)' }}>{String(value)}</Mono>
}

function humanKey(key: string): string {
  const spaced = key.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function ConfigTab({ tenantId }: { tenantId: string }): JSX.Element {
  const { data: config = null, error: loadError } = usePlatformTenantConfig(tenantId)
  const error = loadErrorMessage(loadError, 'Could not load config.')

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  if (!config) return <PageSkeleton kind="detail" label="Loading config" />

  const entries = Object.entries(config)
  const objectSections = entries.filter(([, v]) => v !== null && typeof v === 'object' && !Array.isArray(v))
  const scalarEntries = entries.filter(([, v]) => v === null || typeof v !== 'object' || Array.isArray(v))

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      {scalarEntries.length > 0 && (
        <Card padding="default">
          <SectionHead title="General settings" sub="Read-only view — secrets are masked server-side" />
          <div style={{ height: 8 }} />
          {scalarEntries.map(([key, value], i, arr) => (
            <Kvp
              key={key}
              label={humanKey(key)}
              value={formatConfigValue(value)}
              divider={i < arr.length - 1}
            />
          ))}
        </Card>
      )}

      {objectSections.map(([sectionKey, sectionVal]) => {
        const subEntries = Object.entries(sectionVal as Record<string, unknown>)
        return (
          <Card key={sectionKey} padding="default">
            <SectionHead title={humanKey(sectionKey)} />
            <div style={{ height: 8 }} />
            {subEntries.length === 0 ? (
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-4)' }}>Not configured</span>
            ) : (
              subEntries.map(([k, v], i, arr) => (
                <Kvp
                  key={k}
                  label={humanKey(k)}
                  value={formatConfigValue(v)}
                  divider={i < arr.length - 1}
                />
              ))
            )}
          </Card>
        )
      })}

      <details>
        <summary style={{ cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-ink-3)' }}>
          Raw configuration JSON
        </summary>
        <pre
          style={{
            marginTop: 'var(--space-2)',
            padding: 'var(--space-4)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--color-surface-muted)',
            border: '1px solid var(--color-line-soft)',
            fontSize: 'var(--text-xs)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'pre-wrap',
            overflowX: 'auto',
          }}
        >
          {JSON.stringify(config, null, 2)}
        </pre>
      </details>
    </div>
  )
}

function AuditTab({ tenantId }: { tenantId: string }): JSX.Element {
  const { data, isLoading: loading, error: loadError } = usePlatformTenantAudit(tenantId)
  const entries = data?.data ?? []
  const error = loadErrorMessage(loadError, 'Could not load audit entries.')

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  return (
    <Card padding="none">
      <Table
        columns={[{ title: 'Timestamp', type: 'date' }, { title: 'Action' }, { title: 'IP', type: 'reference' }]}
        rows={entries.map((e) => ({
          cells: [
            <Mono key="ts">{formatDateTime(e.created_at, { year: false })}</Mono>,
            <Badge key="a" variant="info">{e.action.replace(/_/g, ' ')}</Badge>,
            <Mono key="ip" color="var(--color-ink-4)">{e.ip_address ?? '—'}</Mono>,
          ],
        }))}
        emptyState={loading ? <LinesSkeleton label="Loading" /> : <EmptyState compact title="No platform-level audit entries for this tenant" />}
      />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Offboarding data export (audit BE-10)
// ---------------------------------------------------------------------------

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

  return (
    <Card padding="default">
      <SectionHead
        title="Data export"
        sub="Everything the tenant kept on ShipX, as one archive (JSON Lines). Hand it over before the data is deleted."
      />
      {error && <div style={{ margin: 'var(--space-2) 0' }}><Banner variant="error" title="Error">{error}</Banner></div>}
      {!exportInfo && !error && <LinesSkeleton label="Loading export" />}
      {exportInfo && (
        <>
          <Kvp label="Status" value={<StatusBadge kind="offboardingExport" status={exportInfo.status} />} />
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
          <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', marginTop: 'var(--space-3)' }}>
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
            <p style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-xs)', textAlign: 'right', marginTop: 'var(--space-2)' }}>
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
  const [editing, setEditing] = useState(false)
  const [confirmReactivate, setConfirmReactivate] = useState(false)
  const [reactivating, setReactivating] = useState(false)
  const [reactivateError, setReactivateError] = useState<string | null>(null)
  const [reactivationNotices, setReactivationNotices] = useState<string[]>([])
  const [tab, setTab] = useState('overview')
  const [impersonating, setImpersonating] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)
  // What the caller's platform role allows (Phase 1); the API enforces the same, this only hides what would be refused.
  const canLifecycle = useCanPlatform('tenant_lifecycle')
  const canSupport = useCanPlatform('support')

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

  async function handleReactivate(): Promise<void> {
    if (!tenant) return
    setReactivating(true)
    setReactivateError(null)
    try {
      const result = await platformApi.reactivateTenant(tenant.id)
      qc.setQueryData(platformTenantKeys.detail(id ?? ''), result.tenant)
      setReactivationNotices(result.notices)
      setConfirmReactivate(false)
      toast.success('Tenant reactivated', result.tenant.company_name)
    } catch (err) {
      setReactivateError(err instanceof ApiError ? err.message : 'Could not reactivate the tenant.')
    } finally {
      setReactivating(false)
    }
  }

  if (loading && !tenant) return <PageSkeleton kind="detail" label="Loading the page" />
  if (error && !tenant)
    return (
      <>
        <PageHeader title="Tenant" />
        <div className={styles.banner}><Banner variant="error">{error}</Banner></div>
      </>
    )
  if (!tenant) return <></>

  return (
    <DetailPage
      header={
        <PageHeader
          title={tenant.company_name}
          meta={tenant.slug}
          status={
            <>
              <StatusBadge kind="tenant" status={tenant.status} />
              <Badge variant="info" dot={false}>
                <span style={{ textTransform: 'capitalize' }}>{tenant.subscription_tier}</span>
              </Badge>
            </>
          }
          primary={
            !canLifecycle ? undefined : tenant.status === 'suspended' ? (
              <Button variant="primary" onClick={() => setActiveModal('activate')}>
                Lift suspension
              </Button>
            ) : tenant.status === 'offboarded' ? (
              <Button variant="primary" onClick={() => setConfirmReactivate(true)}>
                Reactivate tenant
              </Button>
            ) : undefined
          }
          actions={
            tenant.status === 'active' && canSupport && (
              <Button variant="secondary" icon="eye" loading={impersonating} onClick={() => void handleImpersonate()}>
                Impersonate
              </Button>
            )
          }
          // Destructive actions live in the overflow menu, never beside the main button (FD-24); each confirms.
          more={canLifecycle ? [
            ...(tenant.status !== 'offboarded'
              ? [{ label: 'Edit tenant', icon: 'edit' as const, onSelect: () => setEditing(true) }]
              : []),
            ...(tenant.status === 'active'
              ? [{ label: 'Suspend tenant', icon: 'pause' as const, tone: 'danger' as const, onSelect: () => setActiveModal('suspend') }]
              : []),
            ...(tenant.status !== 'offboarded'
              ? [{ label: 'Offboard tenant', icon: 'x' as const, tone: 'danger' as const, onSelect: () => setActiveModal('offboard') }]
              : []),
          ] : []}
          moreLabel="More tenant actions"
        />
      }
    >
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}
      {reactivationNotices.length > 0 && (
        <div className={styles.banner}>
          <Banner variant="warning" title="Tell the tenant before they resume work">
            <ul style={{ margin: 0, paddingLeft: 'var(--space-5)' }}>
              {reactivationNotices.map((n) => (
                <li key={n}>{noticeText(n)}</li>
              ))}
            </ul>
          </Banner>
        </div>
      )}

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
          <Section title="Tenant details">
            <Kvp label="Status" value={<StatusBadge kind="tenant" status={tenant.status} />} />
            <Kvp
              label="Subscription"
              value={
                <span style={{ textTransform: 'capitalize' }}>{tenant.subscription_tier}</span>
              }
            />
            <Kvp label="Contact email" value={tenant.primary_contact_email} />
            {tenant.primary_contact_phone && (
              <Kvp label="Contact phone" value={tenant.primary_contact_phone} />
            )}
            <Kvp label="Created" value={formatDate(tenant.created_at)} />
            {tenant.offboarded_at && (
              <Kvp label="Offboarded" value={formatDate(tenant.offboarded_at)} />
            )}
            {tenant.reactivated_at && (
              <Kvp label="Reactivated" value={formatDate(tenant.reactivated_at)} />
            )}
            <Kvp
              label="Tenant ID"
              value={
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}>
                  {tenant.id}
                </span>
              }
              divider={false}
            />
          </Section>
          {tenant.status === 'offboarded' && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <OffboardingExportCard tenantId={tenant.id} />
            </div>
          )}
        </>
      )}

      {editing && (
        <EditTenantModal
          tenant={tenant}
          onCancel={() => setEditing(false)}
          onSuccess={(updated) => {
            qc.setQueryData(platformTenantKeys.detail(id ?? ''), updated)
            setEditing(false)
          }}
        />
      )}

      <ConfirmDialog
        open={confirmReactivate}
        title={`Reactivate ${tenant.company_name}?`}
        confirmLabel="Reactivate tenant"
        undo="You can offboard the tenant again later."
        busy={reactivating}
        error={reactivateError}
        onConfirm={() => void handleReactivate()}
        onCancel={() => {
          setConfirmReactivate(false)
          setReactivateError(null)
        }}
      >
        The tenant&apos;s users can sign in again under a new agreement, and its data stops counting down to deletion.
        Customer records anonymised while it was offboarded cannot be restored.
      </ConfirmDialog>

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
    </DetailPage>
  )
}
