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
import { Banner, Button, Card, Field, Mono, ToggleSwitch } from '../../design/components'
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
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useSeedOnce(query, (s) => {
    setEmailFrom(String(s.platform_email_from ?? ''))
    setMaxTenants(String(s.max_tenants ?? ''))
    setMaintenance(Boolean(s.maintenance_mode))
  })

  const loadError = query.error ? (query.error instanceof ApiError ? query.error.message : 'Could not load settings.') : null
  const error = saveError ?? loadError

  async function handleSave(): Promise<void> {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await platformSettingsApi.update({
        platform_email_from: emailFrom,
        max_tenants: Number(maxTenants) || 0,
        maintenance_mode: maintenance,
      })
      qc.setQueryData(platformSettingsKeys.general(), updated)
      toast.success('Platform settings saved')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save settings.')
    } finally {
      setSaving(false)
    }
  }

  if (!settings && !error) return <p style={{ color: 'var(--color-ink-3)' }}>Loading settings…</p>

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
        <Button variant="primary" icon="check" loading={saving} onClick={() => void handleSave()}>
          Save settings
        </Button>
      </div>
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
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(spec.fields.map((f) => [f.key, String(initial[f.key] ?? '')])),
  )
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ kind: 'success' | 'error'; msg: string } | null>(null)

  async function handleSave(): Promise<void> {
    setSaving(true)
    setResult(null)
    try {
      await platformSettingsApi.updateGateway(spec.kind, values)
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
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
        <Button variant="secondary" size="sm" loading={testing} onClick={() => void handleTest()}>
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
  if (!configs) return <p style={{ color: 'var(--color-ink-3)' }}>Loading providers…</p>

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

function PlanEditor({ tier, limits, onSaved }: { tier: SubscriptionTier; limits: PlanLimits; onSaved: (plans: Record<SubscriptionTier, PlanLimits>) => void }): JSX.Element {
  const [users, setUsers] = useState(String(limits.users))
  const [containers, setContainers] = useState(String(limits.containers_per_month))
  const [storage, setStorage] = useState(String(limits.storage_gb))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const result = await platformSettingsApi.updatePlan(tier, {
        users: Number(users),
        containers_per_month: Number(containers),
        storage_gb: Number(storage),
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
        <Field label="Users" name={`${tier}_users`} type="number" value={users} onChange={(e) => setUsers(e.target.value)} />
        <Field label="Containers / month" name={`${tier}_containers`} type="number" value={containers} onChange={(e) => setContainers(e.target.value)} />
        <Field label="Storage (GB)" name={`${tier}_storage`} type="number" value={storage} onChange={(e) => setStorage(e.target.value)} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
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
  if (!plans) return <p style={{ color: 'var(--color-ink-3)' }}>Loading plans…</p>

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Banner variant="info" title="How overrides resolve">
        Static tier defaults → these plan overrides → per-tenant quota overrides (set on a tenant&apos;s
        Usage tab). Only edited dimensions are overridden. Enterprise is effectively unlimited (
        <Mono>999999</Mono>).
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
        eyebrow="Platform"
        title="Platform settings"
        subtitle="Global configuration for the ShipX platform — identity, providers, and plan limits."
      />
      <Tabs items={SUB_PAGES} active={active} onChange={(key) => navigate(key)} />
      {active === '/platform/settings' && <GeneralSettings />}
      {active === '/platform/settings/notifications' && <ProviderSettings />}
      {active === '/platform/settings/plans' && <PlanSettings />}
    </div>
  )
}
