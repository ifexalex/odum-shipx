import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import {
  configApi,
  type WebhookConfig as WebhookConfigType,
  type WebhookEventType,
  type WebhookTestResult,
} from '../../api/tenantManagement'
import { Banner, Button, Card, ConfirmDialog, Field, Icon, Mono, ToggleSwitch, IconButton, PageSkeleton } from '../../design/components'
import { useTenantConfig } from '../../hooks/useConfig'
import { useSeedOnce } from '../../hooks/useSeedOnce'
import { SectionHead } from '../../shell/SectionHead'
import styles from './WebhookConfig.module.css'
import { toast } from '../../design/toast'
import { PageHeader } from '../../shell/PageHeader'

// ─── Event toggle row ──────────────────────────────────────────────────────────
// Only events that have an active backend sender are offered (TA-01 / D1).
const WEBHOOK_EVENTS: Array<{ type: WebhookEventType; label: string }> = [
  { type: 'container.status_updated', label: 'Container status updated' },
]

interface EventToggleProps {
  label: string
  code: WebhookEventType
  checked: boolean
  onChange: (checked: boolean) => void
}

function EventToggleRow({ label, code, checked, onChange }: EventToggleProps): JSX.Element {
  return (
    <div className={styles.eventRow}>
      <ToggleSwitch label={`Send ${label} events`} checked={checked} onChange={onChange} />
      <div className={styles.eventInfo}>
        <span className={styles.eventLabel}>{label}</span>
        <Mono color="var(--color-ink-4)"><span style={{ fontSize: 'var(--text-xs)' }}>{code}</span></Mono>
      </div>
    </div>
  )
}

// ─── Rotate confirm modal ──────────────────────────────────────────────────────
interface RotateModalProps {
  onCancel: () => void
  onConfirm: () => void
  rotating: boolean
}

function RotateModal({ onCancel, onConfirm, rotating }: RotateModalProps): JSX.Element {
  return (
    <ConfirmDialog
      open
      title="Rotate signing secret"
      confirmLabel="Rotate secret"
      undo={false}
      busy={rotating}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      Rotating the secret immediately invalidates the current one — any endpoint still verifying with the old secret
      will start receiving 401 Unauthorized responses. After rotation, the new secret is shown once; copy it
      immediately because it cannot be retrieved again.
    </ConfirmDialog>
  )
}

// ─── New secret reveal banner ──────────────────────────────────────────────────
function NewSecretBanner({ secret, onDismiss }: { secret: string; onDismiss: () => void }): JSX.Element {
  const [copied, setCopied] = useState(false)

  async function handleCopy(): Promise<void> {
    await navigator.clipboard.writeText(secret)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={styles.newSecretBanner}>
      <div className={styles.newSecretTop}>
        <span className={styles.newSecretTitle}>New signing secret — copy now, it won't be shown again</span>
        <IconButton icon="x" label="Close" size="sm" onClick={onDismiss} />
      </div>
      <div className={styles.newSecretRow}>
        <Mono color="var(--color-ink)">{secret}</Mono>
        <Button variant="secondary" size="sm" icon={copied ? 'check' : 'copy'} onClick={() => void handleCopy()}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
    </div>
  )
}

// ─── Main component ────────────────────────────────────────────────────────────
const EMPTY_CONFIG: WebhookConfigType = {
  endpoint_url: '',
  enabled: false,
  events: [],
  secret: '****',
}

function maskSecret(raw: string): string {
  if (!raw || raw === '****') return 'whsec_••••••••••••••••••••'
  const last4 = raw.slice(-4)
  return `whsec_••••••••••••••••${last4}`
}

export function WebhookConfig(): JSX.Element {
  const [config, setConfig] = useState<WebhookConfigType>(EMPTY_CONFIG)
  const tenantConfig = useTenantConfig({ freshOnOpen: true })
  // A failed read shows the empty form, as before, not an endless "Loading…".
  const loading = !tenantConfig.isFetchedAfterMount && !tenantConfig.isError
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [showRotateModal, setShowRotateModal] = useState(false)
  const [rotating, setRotating] = useState(false)
  const [newSecret, setNewSecret] = useState<string | null>(null)

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<WebhookTestResult | null>(null)

  useSeedOnce(tenantConfig, (res) => {
    if (res.webhook_config) setConfig(res.webhook_config)
  })

  function toggleEvent(type: WebhookEventType, on: boolean): void {
    setConfig((prev) => ({
      ...prev,
      events: on ? [...prev.events, type] : prev.events.filter((e) => e !== type),
    }))
  }

  const endpointValid = config.endpoint_url.startsWith('https://')

  async function handleSave(): Promise<void> {
    if (!endpointValid && config.endpoint_url.length > 0) return
    setSaving(true)
    setError(null)
    try {
      const updated = await configApi.updateConfig({
        webhook_config: {
          endpoint_url: config.endpoint_url,
          enabled: config.enabled,
          events: config.events,
        },
      })
      if (updated.webhook_config) setConfig(updated.webhook_config)
      toast.success('Webhook settings saved')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save webhook config.')
    } finally {
      setSaving(false)
    }
  }

  async function handleRotate(): Promise<void> {
    setRotating(true)
    try {
      const result = await configApi.rotateWebhookSecret()
      setNewSecret(result.secret)
      setShowRotateModal(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not rotate secret.')
    } finally {
      setRotating(false)
    }
  }

  async function handleTest(): Promise<void> {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await configApi.testWebhook()
      setTestResult(result)
    } catch (err) {
      setTestResult({
        success: false,
        status_code: null,
        error: err instanceof ApiError ? err.message : 'Test request failed.',
      })
    } finally {
      setTesting(false)
    }
  }

  if (loading) return <PageSkeleton kind="form" label="Loading the page" />

  return (
    <div>
      <PageHeader title="Webhooks" meta="Send ShipX events to your own systems as they happen." />
      {error && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}
      {newSecret && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <NewSecretBanner secret={newSecret} onDismiss={() => setNewSecret(null)} />
        </div>
      )}

      {/* Card 1 — Endpoint + secret */}
      <Card padding="large" style={{ marginBottom: 'var(--space-4)' }}>
        <SectionHead
          title="Outbound webhook"
          sub="Push domain events to your ERP / WMS in real time."
          action={
            <div className={styles.enabledRow}>
              <span className={styles.enabledLabel} style={{ color: config.enabled ? 'var(--color-success)' : 'var(--color-ink-4)' }}>
                {config.enabled ? 'Enabled' : 'Disabled'}
              </span>
              <ToggleSwitch
                label="Outbound webhook"
                checked={config.enabled}
                onChange={(v) => setConfig((p) => ({ ...p, enabled: v }))}
              />
            </div>
          }
        />

        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Field
            label="Endpoint URL"
            name="endpoint_url"
            icon="map"
            value={config.endpoint_url}
            onChange={(e) => setConfig((p) => ({ ...p, endpoint_url: e.target.value }))}
            helper={
              config.endpoint_url.length > 0 && !endpointValid
                ? 'Must start with https://'
                : 'We POST a JSON payload signed with HMAC-SHA256.'
            }
            error={config.endpoint_url.length > 0 && !endpointValid ? 'Must start with https://' : undefined}
          />
        </div>

        <div>
          <label className={styles.secretLabel}>Signing secret</label>
          <div className={styles.secretRow}>
            <div className={styles.secretDisplay}>
              <Icon name="shield" size={15} color="var(--color-ink-4)" />
              <Mono color="var(--color-ink-2)">{maskSecret(config.secret)}</Mono>
            </div>
            <Button variant="secondary" icon="refresh" onClick={() => setShowRotateModal(true)}>
              Rotate secret
            </Button>
          </div>
          <p className={styles.secretHint}>
            Sent as header <Mono color="var(--color-ink-3)">X-ShipX-Signature-256: sha256=…</Mono>
          </p>
        </div>
      </Card>

      {/* Card 2 — Events */}
      <Card padding="large" style={{ marginBottom: 'var(--space-4)' }}>
        <SectionHead title="Subscribed events" sub="Choose which events fire a webhook." />
        {WEBHOOK_EVENTS.map(({ type, label }) => (
          <EventToggleRow
            key={type}
            label={label}
            code={type}
            checked={config.events.includes(type)}
            onChange={(on) => toggleEvent(type, on)}
          />
        ))}
      </Card>

      {/* Test result */}
      {testResult && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner
            variant={testResult.success ? 'success' : 'error'}
            title={testResult.success ? 'Test event delivered' : 'Test event failed'}
          >
            {testResult.success
              ? `HTTP ${testResult.status_code} — your endpoint received the test payload.`
              : testResult.error ?? `HTTP ${testResult.status_code ?? 'no response'}`}
          </Banner>
        </div>
      )}

      {/* Footer actions */}
      <div className={styles.footer}>
        <Button variant="secondary" icon="bell" loading={testing} onClick={() => void handleTest()}>
          Send test event
        </Button>
        <Button
          variant="primary"
          loading={saving}
          disabled={config.endpoint_url.length > 0 && !endpointValid}
          onClick={() => void handleSave()}
        >
          Save webhook
        </Button>
      </div>

      {showRotateModal && (
        <RotateModal
          onCancel={() => setShowRotateModal(false)}
          onConfirm={() => void handleRotate()}
          rotating={rotating}
        />
      )}
    </div>
  )
}
