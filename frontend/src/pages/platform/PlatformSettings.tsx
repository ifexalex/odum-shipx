/**
 * 2.5 — Platform Settings (Section 2 of the prototype, platform-screens.jsx:1090).
 *
 * Three sub-pages on one component, selected by route:
 *  /platform/settings               → General (email-from, max tenants, default tier, maintenance)
 *  /platform/settings/notifications → Providers (Termii SMS / Meta WhatsApp / Postmark email + test)
 *  /platform/settings/plans         → Plans & Limits (per-tier limit editor)
 *
 * Provider "Test" is a config-shape validation on the server (required fields
 * present) — live deliverability is proven by the notification pipeline.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { platformSettingsKeys } from '../../api/keys'
import {
  platformSettingsApi,
  type GatewayKind,
  type PlanLimits,
  type SubscriptionTier,
} from '../../api/tenantManagement'
import { usePlatformGateways, usePlatformGeneralSettings, usePlatformPlans } from '../../hooks/usePlatformSettings'
import { useSeedOnce } from '../../hooks/useSeedOnce'
import { Banner, Button, Card, Check, ConfirmDialog, Field, ToggleSwitch, PageSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import { Tabs } from '../../shell/Tabs'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// General
// ---------------------------------------------------------------------------

function GeneralSettings(): JSX.Element {
  const qc = useQueryClient()
  const query = usePlatformGeneralSettings()
  const settings = query.isFetchedAfterMount ? (query.data ?? null) : null
  const [emailFrom, setEmailFrom] = useState('')
  const [maxTenants, setMaxTenants] = useState('')
  const [maintenance, setMaintenance] = useState(false)
  const [confirmMaintenance, setConfirmMaintenance] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useSeedOnce(query, (s) => {
    setEmailFrom(String(s.platform_email_from ?? ''))
    setMaxTenants(String(s.max_tenants ?? ''))
    setMaintenance(Boolean(s.maintenance_mode))
  })

  const loadError = query.error ? (query.error instanceof ApiError ? query.error.message : 'Could not load settings.') : null
  const error = saveError ?? loadError

  async function commitSave(): Promise<void> {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await platformSettingsApi.update({
        platform_email_from: emailFrom,
        max_tenants: Number(maxTenants) || 0,
        maintenance_mode: maintenance,
      })
      qc.setQueryData(platformSettingsKeys.general(), updated)
      setConfirmMaintenance(false)
      toast.success('Platform settings saved')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save settings.')
    } finally {
      setSaving(false)
    }
  }

  function handleSaveClick(): void {
    const enablingMaintenance = maintenance && !settings?.maintenance_mode
    if (enablingMaintenance) {
      setConfirmMaintenance(true)
      return
    }
    void commitSave()
  }

  if (!settings && !error) return <PageSkeleton kind="detail" label="Loading settings" />

  return (
    <Card padding="large">
      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Error">{error}</Banner></div>}

      <SectionHead title="General" sub="Platform-wide identity and safety switches" />
      <div style={{ height: 16 }} />
      <Field
        label="Notification from-address"
        name="platform_email_from"
        icon="mail"
        value={emailFrom}
        onChange={(e) => setEmailFrom(e.target.value)}
        helper="Sender address on platform-originated emails."
      />
      <Field
        label="Max tenants"
        name="max_tenants"
        type="number"
        value={maxTenants}
        onChange={(e) => setMaxTenants(e.target.value)}
        helper="Hard cap on tenant onboarding."
      />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-4) 0', borderTop: '1px solid var(--color-line-soft)' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 'var(--text-md)', color: maintenance ? 'var(--color-error)' : 'var(--color-ink)' }}>Maintenance mode</div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
            Blocks tenant onboarding and shows a maintenance banner. Existing sessions keep working.
          </div>
        </div>
        <ToggleSwitch label="Maintenance mode" checked={maintenance} onChange={setMaintenance} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-line-soft)' }}>
        <Button variant="primary" icon="check" loading={saving} onClick={handleSaveClick}>
          Save settings
        </Button>
      </div>

      <ConfirmDialog
        open={confirmMaintenance}
        title="Enable maintenance mode?"
        confirmLabel="Enable maintenance mode"
        undo="You can turn maintenance mode off again from this page at any time."
        busy={saving}
        error={saveError}
        onConfirm={() => void commitSave()}
        onCancel={() => setConfirmMaintenance(false)}
      >
        Tenant onboarding will be blocked and a maintenance banner will appear across the platform. Existing user sessions will keep working.
      </ConfirmDialog>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

interface ProviderSpec {
  kind: GatewayKind
  title: string
  provider: string
  fields: { key: string; label: string; secret?: boolean; placeholder: string }[]
}

const PROVIDERS: ProviderSpec[] = [
  {
    kind: 'sms',
    title: 'SMS',
    provider: 'Termii',
    fields: [
      { key: 'api_key', label: 'API key', secret: true, placeholder: 'TL•••••••••••' },
      { key: 'sender_id', label: 'Sender ID', placeholder: 'ShipX' },
    ],
  },
  {
    kind: 'whatsapp',
    title: 'WhatsApp',
    provider: 'Meta Cloud API',
    fields: [
      { key: 'access_token', label: 'Access token', secret: true, placeholder: 'EAAG•••••••••' },
      { key: 'phone_number_id', label: 'Phone number ID', placeholder: '10945••••••' },
    ],
  },
  {
    kind: 'email',
    title: 'Email',
    provider: 'Postmark',
    fields: [
      { key: 'server_token', label: 'Server token', secret: true, placeholder: 'pm-•••••••••' },
      { key: 'from_email', label: 'From address', placeholder: 'notifications@shipx.co' },
    ],
  },
]

function ProviderCard({ spec, initial }: { spec: ProviderSpec; initial: Record<string, unknown> }): JSX.Element {
  const initialMap = Object.fromEntries(spec.fields.map((f) => [f.key, String(initial[f.key] ?? '')]))
  const [savedValues, setSavedValues] = useState<Record<string, string>>(initialMap)
  const [values, setValues] = useState<Record<string, string>>(initialMap)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ kind: 'success' | 'error'; msg: string } | null>(null)

  const dirty = spec.fields.some((f) => (values[f.key] ?? '') !== (savedValues[f.key] ?? ''))

  async function handleSave(): Promise<void> {
    setSaving(true)
    setResult(null)
    try {
      await platformSettingsApi.updateGateway(spec.kind, values)
      setSavedValues({ ...values })
      toast.success('Gateway settings saved')
      setResult({ kind: 'success', msg: 'Configuration saved.' })
    } catch (err) {
      setResult({ kind: 'error', msg: err instanceof ApiError ? err.message : 'Save failed.' })
    } finally {
      setSaving(false)
    }
  }

  async function handleTest(): Promise<void> {
    setTesting(true)
    setResult(null)
    try {
      const test = await platformSettingsApi.testGateway(spec.kind)
      setResult(
        test.success
          ? { kind: 'success', msg: 'Configuration valid — all required fields present.' }
          : { kind: 'error', msg: test.error ?? 'Configuration incomplete.' },
      )
    } catch (err) {
      setResult({ kind: 'error', msg: err instanceof ApiError ? err.message : 'Test failed.' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Card padding="large">
      <SectionHead title={spec.title} sub={`Provider: ${spec.provider}`} />
      <div style={{ height: 12 }} />
      {result && (
        <div style={{ marginBottom: 'var(--space-3)' }}>
          <Banner variant={result.kind} title={result.kind === 'success' ? 'OK' : 'Problem'}>{result.msg}</Banner>
        </div>
      )}
      {spec.fields.map((f) => (
        <Field
          key={f.key}
          label={f.label}
          name={`${spec.kind}_${f.key}`}
          type={f.secret ? 'password' : 'text'}
          placeholder={f.placeholder}
          value={values[f.key] ?? ''}
          onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
          helper={f.secret ? 'Stored value shows as **** — leave as-is to keep it.' : undefined}
        />
      ))}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        {dirty && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginRight: 'auto' }}>
            Save changes before testing configuration.
          </span>
        )}
        <Button variant="secondary" size="sm" loading={testing} disabled={dirty || saving} onClick={() => void handleTest()}>
          Test configuration
        </Button>
        <Button variant="primary" size="sm" icon="check" loading={saving} onClick={() => void handleSave()}>
          Save
        </Button>
      </div>
    </Card>
  )
}

function ProviderSettings(): JSX.Element {
  const query = usePlatformGateways()
  // Each card copies its provider's config into its own form when it mounts, so wait for the fresh read.
  const configs = query.isFetchedAfterMount ? (query.data ?? null) : null
  const error = query.error
    ? query.error instanceof ApiError
      ? query.error.message
      : 'Could not load provider settings.'
    : null

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  if (!configs) return <PageSkeleton kind="detail" label="Loading providers" />

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      {PROVIDERS.map((spec) => (
        <ProviderCard key={spec.kind} spec={spec} initial={(configs[spec.kind] ?? {}) as Record<string, unknown>} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Plans & Limits
// ---------------------------------------------------------------------------

const TIERS: SubscriptionTier[] = ['starter', 'business', 'enterprise']
const UNLIMITED_SENTINEL = 999999

function LimitField({
  label,
  name,
  value,
  unlimited,
  onChangeValue,
  onToggleUnlimited,
}: {
  label: string
  name: string
  value: string
  unlimited: boolean
  onChangeValue: (v: string) => void
  onToggleUnlimited: (next: boolean) => void
}): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <Field
        label={label}
        name={name}
        type="number"
        value={unlimited ? '' : value}
        placeholder={unlimited ? 'Unlimited' : undefined}
        disabled={unlimited}
        onChange={(e) => onChangeValue(e.target.value)}
      />
      <Check
        label="Unlimited"
        checked={unlimited}
        onChange={onToggleUnlimited}
      />
    </div>
  )
}

function PlanEditor({ tier, limits, onSaved }: { tier: SubscriptionTier; limits: PlanLimits; onSaved: (plans: Record<SubscriptionTier, PlanLimits>) => void }): JSX.Element {
  const [users, setUsers] = useState(limits.users >= UNLIMITED_SENTINEL ? '100' : String(limits.users))
  const [usersUnlimited, setUsersUnlimited] = useState(limits.users >= UNLIMITED_SENTINEL)
  const [containers, setContainers] = useState(limits.containers_per_month >= UNLIMITED_SENTINEL ? '100' : String(limits.containers_per_month))
  const [containersUnlimited, setContainersUnlimited] = useState(limits.containers_per_month >= UNLIMITED_SENTINEL)
  const [storage, setStorage] = useState(limits.storage_gb >= UNLIMITED_SENTINEL ? '100' : String(limits.storage_gb))
  const [storageUnlimited, setStorageUnlimited] = useState(limits.storage_gb >= UNLIMITED_SENTINEL)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const result = await platformSettingsApi.updatePlan(tier, {
        users: usersUnlimited ? UNLIMITED_SENTINEL : Number(users),
        containers_per_month: containersUnlimited ? UNLIMITED_SENTINEL : Number(containers),
        storage_gb: storageUnlimited ? UNLIMITED_SENTINEL : Number(storage),
      })
      toast.success('Plan limits saved')
      onSaved(result.plans)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update plan.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card padding="default">
      <SectionHead title={tier[0]!.toUpperCase() + tier.slice(1)} sub="Limits apply to every tenant on this tier unless a per-tenant override exists" />
      {error && <div style={{ margin: 'var(--space-2) 0' }}><Banner variant="error" title="Save failed">{error}</Banner></div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-4)', marginTop: 'var(--space-3)' }}>
        <LimitField
          label="Users"
          name={`${tier}_users`}
          value={users}
          unlimited={usersUnlimited}
          onChangeValue={setUsers}
          onToggleUnlimited={setUsersUnlimited}
        />
        <LimitField
          label="Containers / month"
          name={`${tier}_containers`}
          value={containers}
          unlimited={containersUnlimited}
          onChangeValue={setContainers}
          onToggleUnlimited={setContainersUnlimited}
        />
        <LimitField
          label="Storage (GB)"
          name={`${tier}_storage`}
          value={storage}
          unlimited={storageUnlimited}
          onChangeValue={setStorage}
          onToggleUnlimited={setStorageUnlimited}
        />
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-3)' }}>
        <Button variant="primary" size="sm" icon="check" loading={saving} onClick={() => void handleSave()}>
          Save {tier} limits
        </Button>
      </div>
    </Card>
  )
}

function PlanSettings(): JSX.Element {
  const qc = useQueryClient()
  const query = usePlatformPlans()
  const plans = query.isFetchedAfterMount ? (query.data?.plans ?? null) : null
  const error = query.error ? (query.error instanceof ApiError ? query.error.message : 'Could not load plans.') : null
  // A save returns every tier's limits: show them at once (the write also invalidates the query).
  const setPlans = (updated: Record<SubscriptionTier, PlanLimits>): void => {
    qc.setQueryData(platformSettingsKeys.plans(), { plans: updated })
  }

  if (error) return <Banner variant="error" title="Error">{error}</Banner>
  if (!plans) return <PageSkeleton kind="detail" label="Loading plans" />

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Banner variant="info" title="How overrides resolve">
        Static tier defaults → these plan overrides → per-tenant quota overrides (set on a tenant&apos;s
        Usage tab). Check <strong>Unlimited</strong> on any dimension to lift its cap.
      </Banner>
      {TIERS.map((tier) => (
        <PlanEditor key={tier} tier={tier} limits={plans[tier]!} onSaved={setPlans} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page shell with sub-nav
// ---------------------------------------------------------------------------

const SUB_PAGES = [
  { key: '/platform/settings', label: 'General' },
  { key: '/platform/settings/notifications', label: 'Notification providers' },
  { key: '/platform/settings/plans', label: 'Plans & limits' },
]

export function PlatformSettings(): JSX.Element {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const active = SUB_PAGES.find((p) => p.key === pathname)?.key ?? '/platform/settings'

  return (
    <div>
      <PageHeader
        title="Platform settings"
        meta="Global configuration for the ShipX platform — identity, providers, and plan limits."
      />
      <Tabs items={SUB_PAGES} active={active} onChange={(key) => navigate(key)} />
      {active === '/platform/settings' && <GeneralSettings />}
      {active === '/platform/settings/notifications' && <ProviderSettings />}
      {active === '/platform/settings/plans' && <PlanSettings />}
    </div>
  )
}
