import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import {
  configApi,
  type WebhookConfig as WebhookConfigType,
  type WebhookEventType,
  type WebhookTestResult,
} from '../../api/tenantManagement'
import { Banner, Button, Card, Field, Icon, Mono, ToggleSwitch } from '../../design/components'
import { useTenantConfig } from '../../hooks/useConfig'
import { useSeedOnce } from '../../hooks/useSeedOnce'
import { SectionHead } from '../../shell/SectionHead'
import styles from './WebhookConfig.module.css'

// ─── Event toggle row ──────────────────────────────────────────────────────────
const WEBHOOK_EVENTS: Array<{ type: WebhookEventType; label: string }> = [
  { type: 'container.status_updated', label: 'Container status updated' },
  { type: 'billing.payment_due',      label: 'Billing payment due' },
  { type: 'release_note.generated',   label: 'Release note generated' },
  { type: 'packing_list.approved',    label: 'Packing list approved' },
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
      <ToggleSwitch checked={checked} onChange={onChange} />
      <div className={styles.eventInfo}>
        <span className={styles.eventLabel}>{label}</span>
        <Mono color="var(--color-ink-4)"><span style={{ fontSize: 11 }}>{code}</span></Mono>
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
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3 className={styles.modalTitle}>Rotate signing secret</h3>
          <button type="button" className={styles.closeBtn} onClick={onCancel}>
            <Icon name="x" size={18} />
          </button>
        </div>
        <div className={styles.modalBody}>
          <Banner variant="warning" icon="warn" title="This is irreversible">
            Rotating the secret immediately invalidates the current one. Any endpoint still verifying
            with the old secret will start receiving <strong>401 Unauthorized</strong> responses.
            Update your integration before confirming.
          </Banner>
          <p className={styles.modalText}>
            After rotation, the new secret is shown <strong>once</strong>. Copy it immediately — it
            cannot be retrieved again.
          </p>
        </div>
        <div className={styles.modalFooter}>
          <Button variant="secondary" onClick={onCancel} disabled={rotating}>Cancel</Button>
          <Button variant="danger" loading={rotating} onClick={onConfirm}>
            Rotate secret
          </Button>
        </div>
      </div>
    </div>
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
        <button type="button" className={styles.closeBtn} onClick={onDismiss}>
          <Icon name="x" size={16} />
        </button>
      </div>
      <div className={styles.newSecretRow}>
        <Mono color="var(--color-ink)">{secret}</Mono>
        <Button variant="secondary" size="sm" icon={copied ? 'check' : 'download'} onClick={() => void handleCopy()}>
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
  const [saveSuccess, setSaveSuccess] = useState(false)

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
    setSaveSuccess(false)
    try {
      const updated = await configApi.updateConfig({
        webhook_config: {
          endpoint_url: config.endpoint_url,
          enabled: config.enabled,
          events: config.events,
        },
      })
      if (updated.webhook_config) setConfig(updated.webhook_config)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
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

  if (loading) return <div style={{ padding: 32, color: 'var(--color-ink-4)' }}>Loading…</div>

  return (
    <div>
      {error && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}
      {saveSuccess && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="success">Webhook configuration saved.</Banner>
        </div>
      )}
      {newSecret && (
        <div style={{ marginBottom: 16 }}>
          <NewSecretBanner secret={newSecret} onDismiss={() => setNewSecret(null)} />
        </div>
      )}

      {/* Card 1 — Endpoint + secret */}
      <Card padding={24} style={{ marginBottom: 16 }}>
        <SectionHead
          title="Outbound webhook"
          sub="Push domain events to your ERP / WMS in real time."
          action={
            <div className={styles.enabledRow}>
              <span className={styles.enabledLabel} style={{ color: config.enabled ? 'var(--color-success)' : 'var(--color-ink-4)' }}>
                {config.enabled ? 'Enabled' : 'Disabled'}
              </span>
              <ToggleSwitch
                checked={config.enabled}
                onChange={(v) => setConfig((p) => ({ ...p, enabled: v }))}
              />
            </div>
          }
        />

        <div style={{ marginBottom: 16 }}>
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
      <Card padding={24} style={{ marginBottom: 16 }}>
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
        <div style={{ marginBottom: 16 }}>
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
