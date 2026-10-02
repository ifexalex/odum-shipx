/**
 * Multi-tenant Paystack config (2026-07-19) — each tenant connects their own
 * Paystack secret key so customer online payments land directly in their own
 * account. There is no platform-wide key anywhere in the system; a tenant
 * who hasn't connected one yet simply doesn't offer "Pay online" — bank
 * transfer remains available regardless (see MyBillingDetail.tsx).
 *
 * Modelled closely on WebhookConfig.tsx: masked status display, a
 * password-type input for a new key (never prefilled with the real value —
 * GET /v1/tenant/config only ever returns last4), Save + Test-connection +
 * Disconnect actions.
 */
import { useEffect, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configApi, type BankTransferConfig, type PaystackConfig } from '../../api/tenantManagement'
import { Banner, Button, Card, Field, Icon, Mono } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './PaymentGatewayConfig.module.css'

const EMPTY_BANK_FORM = { bank_name: '', account_name: '', account_number: '', sort_code: '', instructions: '' }

/**
 * Ground-truth gap found live: MyBillingDetail.tsx's "Manual bank transfer"
 * panel used to show one hardcoded bank account to every tenant's customers
 * — a real money-misdirection risk, not just an ambiguity. This is the
 * tenant-admin side of making it a real per-tenant setting.
 */
function BankTransferSettings(): JSX.Element {
  const [config, setConfig] = useState<BankTransferConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(EMPTY_BANK_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  useEffect(() => {
    void configApi
      .getConfig()
      .then((res) => {
        const bt = res.bank_transfer_config ?? null
        setConfig(bt)
        if (bt) {
          setForm({
            bank_name: bt.bank_name,
            account_name: bt.account_name,
            account_number: bt.account_number,
            sort_code: bt.sort_code ?? '',
            instructions: bt.instructions ?? '',
          })
        }
      })
      .catch(() => setConfig(null))
      .finally(() => setLoading(false))
  }, [])

  const canSave = form.bank_name.trim() && form.account_name.trim() && form.account_number.trim()

  async function handleSave(): Promise<void> {
    if (!canSave) return
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const updated = await configApi.updateConfig({
        bank_transfer_config: {
          bank_name: form.bank_name.trim(),
          account_name: form.account_name.trim(),
          account_number: form.account_number.trim(),
          sort_code: form.sort_code.trim() || null,
          instructions: form.instructions.trim() || null,
        },
      })
      setConfig(updated.bank_transfer_config ?? null)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save these bank details.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--color-ink-4)' }}>Loading…</div>

  return (
    <Card padding={24} style={{ marginBottom: 16 }}>
      <SectionHead
        title="Manual bank transfer"
        sub="Shown to your customers when they choose to pay by bank transfer. Get this right — it's where their money goes."
        action={
          <span className={config ? styles.badgeLive : styles.badgeUnconfigured}>
            {config ? 'Configured' : 'Not set'}
          </span>
        }
      />
      {!config && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="warning" title="No bank account configured">
            Until you save one, customers who choose "Manual bank transfer" won't be shown any account
            details — that option is effectively unusable for them.
          </Banner>
        </div>
      )}
      {saveError && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="error">{saveError}</Banner>
        </div>
      )}
      {saveSuccess && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="success">Bank details saved.</Banner>
        </div>
      )}
      <div className={styles.bankGrid}>
        <Field
          label="Bank name"
          name="bank_name"
          required
          value={form.bank_name}
          onChange={(e) => setForm({ ...form, bank_name: e.target.value })}
        />
        <Field
          label="Account name"
          name="account_name"
          required
          value={form.account_name}
          onChange={(e) => setForm({ ...form, account_name: e.target.value })}
        />
        <Field
          label="Account number"
          name="account_number"
          required
          value={form.account_number}
          onChange={(e) => setForm({ ...form, account_number: e.target.value })}
        />
        <Field
          label="Sort code"
          name="sort_code"
          optional
          value={form.sort_code}
          onChange={(e) => setForm({ ...form, sort_code: e.target.value })}
        />
      </div>
      <div style={{ marginTop: 16 }}>
        <Field
          label="Extra instructions"
          name="instructions"
          multiline
          optional
          placeholder="e.g. Use your invoice number as the payment description"
          value={form.instructions}
          onChange={(e) => setForm({ ...form, instructions: e.target.value })}
        />
      </div>
      <div className={styles.footer}>
        <Button variant="primary" loading={saving} disabled={!canSave} onClick={() => void handleSave()}>
          Save bank details
        </Button>
      </div>
    </Card>
  )
}

const KEY_PATTERN = /^sk_(test|live)_[A-Za-z0-9]{20,}$/

export function PaymentGatewayConfig(): JSX.Element {
  const [config, setConfig] = useState<PaystackConfig | null>(null)
  const [loading, setLoading] = useState(true)

  const [newKey, setNewKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [disconnecting, setDisconnecting] = useState(false)
  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false)

  useEffect(() => {
    void configApi.getConfig()
      .then((res) => setConfig(res.paystack_config ?? null))
      .catch(() => setConfig(null))
      .finally(() => setLoading(false))
  }, [])

  const keyValid = newKey.length === 0 || KEY_PATTERN.test(newKey)

  async function handleSave(): Promise<void> {
    if (!KEY_PATTERN.test(newKey)) return
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    setTestResult(null)
    try {
      const updated = await configApi.updatePaystackConfig(newKey)
      setConfig(updated)
      setNewKey('')
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save this key.')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest(): Promise<void> {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await configApi.testPaystackConnection()
      setTestResult({ success: true, message: `Connected — Paystack accepted the key (${result.environment} mode).` })
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof ApiError ? err.message : 'Could not reach Paystack.',
      })
    } finally {
      setTesting(false)
    }
  }

  async function handleDisconnect(): Promise<void> {
    setDisconnecting(true)
    try {
      await configApi.deletePaystackConfig()
      setConfig(null)
      setTestResult(null)
      setShowDisconnectConfirm(false)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not disconnect Paystack.')
    } finally {
      setDisconnecting(false)
    }
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--color-ink-4)' }}>Loading…</div>

  const connected = config?.enabled === true

  return (
    <div>
      {saveError && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="error">{saveError}</Banner>
        </div>
      )}
      {saveSuccess && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="success">Paystack key saved.</Banner>
        </div>
      )}

      <Card padding={24} style={{ marginBottom: 16 }}>
        <SectionHead
          title="Paystack"
          sub="Customer payments go straight to your own Paystack account — ShipX never holds or touches your funds."
          action={
            connected ? (
              <span className={config?.environment === 'live' ? styles.badgeLive : styles.badgeTest}>
                {config?.environment === 'live' ? 'Live mode' : 'Test mode'}
              </span>
            ) : (
              <span className={styles.badgeUnconfigured}>Not connected</span>
            )
          }
        />

        {connected && (
          <div className={styles.statusRow}>
            <Icon name="shield" size={15} color="var(--color-ink-4)" />
            <Mono color="var(--color-ink-2)">sk_{config?.environment}_••••••••••••••••{config?.last4}</Mono>
            <Button variant="secondary" size="sm" loading={testing} onClick={() => void handleTest()}>
              Test connection
            </Button>
          </div>
        )}

        {testResult && (
          <div style={{ marginTop: 12 }}>
            <Banner variant={testResult.success ? 'success' : 'error'}>{testResult.message}</Banner>
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <Field
            label={connected ? 'Replace secret key' : 'Secret key'}
            name="secret_key"
            type="password"
            icon="shield"
            placeholder="sk_test_••••••••••••••••••••••••••••"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            helper={
              newKey.length > 0 && !keyValid
                ? 'Must look like sk_test_… or sk_live_… from your Paystack dashboard.'
                : 'From your Paystack dashboard → Settings → API Keys & Webhooks. Never shared, never logged.'
            }
            error={newKey.length > 0 && !keyValid ? 'Invalid key format.' : undefined}
          />
        </div>

        <div className={styles.footer}>
          {connected && (
            <Button variant="danger-outline" onClick={() => setShowDisconnectConfirm(true)}>
              Disconnect
            </Button>
          )}
          <Button
            variant="primary"
            loading={saving}
            disabled={newKey.length === 0 || !keyValid}
            onClick={() => void handleSave()}
          >
            {connected ? 'Replace key' : 'Connect Paystack'}
          </Button>
        </div>
      </Card>

      {!connected && (
        <Banner variant="info" title="Online payment is unavailable until you connect a key">
          Customers can still pay by bank transfer in the meantime — connecting Paystack just adds the
          instant card/transfer/USSD option.
        </Banner>
      )}

      <BankTransferSettings />

      {showDisconnectConfirm && (
        <div className={styles.modalOverlay} onClick={() => setShowDisconnectConfirm(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3 className={styles.modalTitle}>Disconnect Paystack</h3>
              <button type="button" className={styles.closeBtn} onClick={() => setShowDisconnectConfirm(false)}>
                <Icon name="x" size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <Banner variant="warning" icon="warn" title="Online payment will stop working immediately">
                Customers won&apos;t see the &quot;Pay online&quot; option until you reconnect a key. Bank
                transfer stays available the whole time.
              </Banner>
            </div>
            <div className={styles.modalFooter}>
              <Button variant="secondary" onClick={() => setShowDisconnectConfirm(false)} disabled={disconnecting}>
                Cancel
              </Button>
              <Button variant="danger" loading={disconnecting} onClick={() => void handleDisconnect()}>
                Disconnect
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
