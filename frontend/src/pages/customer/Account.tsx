/**
 * 10.7 — Customer Account (Section 10 of the prototype).
 *
 * Three tabs:
 *  - Profile: contact info; name/email locked (Cognito Username is immutable),
 *    phone/whatsapp editable via customer self-service PATCH.
 *  - Notifications: channel consent toggles → customer.notification_consent.
 *  - Privacy (GDPR/NDPR): data export download, consent summary, and
 *    Delete-my-account (anonymise; requires typing DELETE).
 *
 * The customer's own record is resolved via GET /v1/customers, which the
 * backend scopes to [own record] for the customer role.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { customersApi, type Customer } from '../../api/tenantManagement'
import { useSession } from '../../auth/useSession'
import { OWN_CUSTOMER_KEY, useOwnCustomer } from '../../hooks/useCustomers'
import { Avatar, Banner, Button, Card, Field, Icon, PhoneField, ToggleSwitch, RadioGroup } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import { Tabs } from '../../shell/Tabs'
import styles from './customer.module.css'
import { todayIso, formatDate } from '../../lib/format'
import { toast } from '../../design/toast'

type TabKey = 'Profile' | 'Notifications' | 'Privacy'

const CHANNELS = [
  {
    key: 'sms',
    label: 'SMS',
    sub: 'Text messages, for optional announcements and offers',
  },
  {
    key: 'whatsapp',
    label: 'WhatsApp',
    sub: 'Richer formatting · most reliable, for optional announcements and offers',
    recommended: true,
  },
  {
    key: 'email',
    label: 'Email',
    sub: 'For optional announcements and offers',
  },
] as const

// ---------------------------------------------------------------------------
// Profile tab
// ---------------------------------------------------------------------------

function ProfileTab({ customer, onSaved }: { customer: Customer; onSaved: (c: Customer) => void }): JSX.Element {
  const [phone, setPhone] = useState(customer.phone ?? '')
  const [whatsapp, setWhatsapp] = useState(customer.whatsapp ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = phone !== (customer.phone ?? '') || whatsapp !== (customer.whatsapp ?? '')

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await customersApi.update(customer.id, { phone, whatsapp })
      onSaved(updated)
      toast.success('Contact details saved')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update your profile.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card padding="large">
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <Avatar size={72} name={customer.name ?? 'Customer'} />
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-xl)' }}>{customer.name}</div>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>
            {customer.shipment_count != null ? `${customer.shipment_count} shipments` : 'Customer'}
          </div>
        </div>
      </div>

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Update failed">{error}</Banner></div>}

      <SectionHead title="Contact info" sub="Name and email are locked once an account is created. Other fields can be updated." />
      <div style={{ height: 16 }} />
      <div className={styles.twoCol}>
        <Field label="Full name" name="name" value={customer.name ?? ''} disabled />
        <Field
          label="Email address"
          name="email"
          icon="mail"
          value={customer.email ?? ''}
          disabled
          helper="Contact support to change your email."
        />
      </div>
      <div className={styles.twoCol}>
        <PhoneField label="Phone number" name="phone" required value={phone} onChange={setPhone} />
        <Field
          label="WhatsApp number"
          name="whatsapp"
          icon="phone"
          optional
          value={whatsapp}
          onChange={(e) => setWhatsapp(e.target.value)}
          helper="Leave blank to use your phone number."
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-2)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-line-soft)' }}>
        <Button variant="ghost" disabled={!dirty || saving} onClick={() => { setPhone(customer.phone ?? ''); setWhatsapp(customer.whatsapp ?? '') }}>
          Discard
        </Button>
        <Button variant="primary" icon="check" loading={saving} disabled={!dirty} onClick={() => void handleSave()}>
          Update profile
        </Button>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Notifications tab
// ---------------------------------------------------------------------------

function NotificationsTab({ customer, onSaved }: { customer: Customer; onSaved: (c: Customer) => void }): JSX.Element {
  const [consent, setConsent] = useState<string[]>(customer.notification_consent ?? [])
  const [locale, setLocale] = useState<'en' | 'zh'>(customer.locale ?? 'en')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const consentDirty =
    JSON.stringify([...consent].sort()) !== JSON.stringify([...(customer.notification_consent ?? [])].sort())
  const dirty = consentDirty || locale !== (customer.locale ?? 'en')

  function toggle(key: string): void {
    setConsent((prev) => (prev.includes(key) ? prev.filter((c) => c !== key) : [...prev, key]))
  }

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      // Send only what changed. Saving notification_consent is what records that the customer made a
      // choice (shared/notification_consent.py), so a customer who only switches language must not be
      // recorded as having chosen the channel list they never touched, empty or not.
      const body: { notification_consent?: string[]; locale?: 'en' | 'zh' } = {}
      if (consentDirty) body.notification_consent = consent
      if (locale !== (customer.locale ?? 'en')) body.locale = locale
      const updated = await customersApi.update(customer.id, body)
      onSaved(updated)
      toast.success('Notification preferences saved')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your preferences.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card padding="large">
      <SectionHead
        title="How would you like updates?"
        sub="Choose the channels for optional messages such as announcements and offers. Updates about your own shipments, invoices and claims, and emails about your account, are always sent."
      />
      <div style={{ height: 12 }} />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Save failed">{error}</Banner></div>}

      {CHANNELS.map(({ key, label, sub, ...rest }, i) => {
        const enabled = consent.includes(key)
        return (
          <div
            key={key}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-4)',
              padding: 'var(--space-4) 0',
              borderBottom: i === CHANNELS.length - 1 ? 'none' : '1px solid var(--color-line-soft)',
            }}
          >
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 'var(--radius-lg)',
                background: enabled ? 'var(--color-primary-soft)' : 'var(--color-line-soft)',
                color: enabled ? 'var(--color-primary)' : 'var(--color-ink-4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Icon name={key === 'email' ? 'mail' : 'phone'} size={16} stroke={2} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-md)' }}>{label}</span>
                {'recommended' in rest && (
                  <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', color: 'var(--color-primary-deep)', background: 'var(--color-primary-soft)', borderRadius: 'var(--radius-full)', padding: 'var(--space-0-5) var(--space-2)' }}>
                    Recommended
                  </span>
                )}
              </div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginTop: 'var(--space-1)' }}>{sub}</div>
            </div>
            <ToggleSwitch checked={enabled} onChange={() => toggle(key)} label={label} />
          </div>
        )
      })}

      {/* Notification language (P2-1) — selects the EN/ZH template set for SMS/WhatsApp/email */}
      <div style={{ marginTop: 'var(--space-6)', paddingTop: 'var(--space-5)', borderTop: '1px solid var(--color-line-soft)' }}>
        <SectionHead title="Message language" sub="The language we use for SMS, WhatsApp and email updates" />
        <div style={{ marginTop: 'var(--space-3)' }}>
          <RadioGroup
            label="Message language"
            hideLabel
            name="locale"
            layout="cards"
            value={locale}
            onChange={setLocale}
            options={[
              { value: 'en', label: 'English', hint: 'EN — default' },
              { value: 'zh', label: '中文 (简体)', hint: 'ZH — Simplified Chinese' },
            ]}
          />
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-6)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-line-soft)' }}>
        <Button variant="primary" icon="check" loading={saving} disabled={!dirty} onClick={() => void handleSave()}>
          Save preferences
        </Button>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Privacy tab (GDPR / NDPR)
// ---------------------------------------------------------------------------

function PrivacyTab({ customer }: { customer: Customer }): JSX.Element {
  const { logout } = useSession()
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showDelete, setShowDelete] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)

  async function handleExport(): Promise<void> {
    setExporting(true)
    setError(null)
    try {
      const bundle = await customersApi.export(customer.id)
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `my-data-export-${todayIso()}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not export your data.')
    } finally {
      setExporting(false)
    }
  }

  async function handleDelete(): Promise<void> {
    setDeleting(true)
    setError(null)
    try {
      await customersApi.anonymise(customer.id)
      // Personal data is gone — end the session immediately.
      logout()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete your account.')
      setDeleting(false)
    }
  }

  return (
    <Card padding="large">
      <SectionHead
        title="Your data, your choice"
        sub="Under Nigeria's NDPR and the EU's GDPR, you have full control over your personal data."
      />
      <div style={{ height: 16 }} />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Action failed">{error}</Banner></div>}

      {customer.consent_given_at && (
        <Banner variant="success" title="Consent on file">
          You consented to data processing on <strong>{formatDate(customer.consent_given_at)}</strong>. Lawful
          basis: contract performance (NDPR Art. 2.2). You can withdraw at any time below.
        </Banner>
      )}

      <div className={styles.twoCol} style={{ margin: 'var(--space-6) 0' }}>
        <div style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-line-soft)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-5)' }}>
          <div style={{ width: 36, height: 36, borderRadius: 'var(--radius-lg)', background: 'var(--color-primary-soft)', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 'var(--space-3)' }}>
            <Icon name="download" size={16} />
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-md)', marginBottom: 'var(--space-1)' }}>Download your data</div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', lineHeight: 'var(--leading-body)', marginBottom: 'var(--space-3)' }}>
            Get a JSON export of everything we hold — profile, shipments, billing, claims, consents.
          </div>
          <Button variant="ghost" size="sm" icon="download" loading={exporting} onClick={() => void handleExport()}>
            Request my data export
          </Button>
        </div>
        <div style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-line-soft)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-5)' }}>
          <div style={{ width: 36, height: 36, borderRadius: 'var(--radius-lg)', background: 'var(--color-primary-soft)', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 'var(--space-3)' }}>
            <Icon name="settings" size={16} />
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-md)', marginBottom: 'var(--space-1)' }}>Update consent preferences</div>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', lineHeight: 'var(--leading-body)', marginBottom: 'var(--space-3)' }}>
            Change which channels you&apos;ve consented to on the Notifications tab. Transactional messages always go through.
          </div>
        </div>
      </div>

      {/* Danger zone */}
      <div style={{ background: 'color-mix(in srgb, var(--color-error) 4%, var(--color-surface))', border: '1px solid color-mix(in srgb, var(--color-error) 20%, transparent)', borderLeft: '4px solid var(--color-error)', borderRadius: 'var(--radius-lg)', padding: 'var(--space-5)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-4)' }}>
          <div style={{ width: 40, height: 40, borderRadius: 'var(--radius-lg)', background: 'var(--color-error-soft)', color: 'var(--color-error)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Icon name="suspend" size={18} stroke={2.2} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-lg)', color: 'var(--color-error)' }}>Delete my account</div>
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', margin: 'var(--space-2) 0 var(--space-3)', lineHeight: 'var(--leading-body)' }}>
              Permanently erase your personal data — name, phone, email and address. Your{' '}
              <strong>billing and shipment records are kept</strong> as required by law, but they will no longer be
              linked to you. <strong>This cannot be undone.</strong>
            </p>
            {!showDelete ? (
              <Button variant="danger-ghost" icon="suspend" onClick={() => setShowDelete(true)}>
                Delete my account
              </Button>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <Field
                  label='Type "DELETE" to confirm'
                  name="confirm_delete"
                  placeholder="DELETE"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                />
                <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  <Button variant="ghost" size="sm" onClick={() => { setShowDelete(false); setConfirmText('') }} disabled={deleting}>
                    Cancel
                  </Button>
                  <Button variant="danger" size="sm" loading={deleting} disabled={confirmText !== 'DELETE'} onClick={() => void handleDelete()}>
                    Permanently delete my data
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Account(): JSX.Element {
  const { session } = useSession()
  const [tab, setTab] = useState<TabKey>('Profile')
  const qc = useQueryClient()
  const own = useOwnCustomer()
  const customer = own.data ?? null
  const loading = own.isLoading
  const error = own.error ? (own.error instanceof ApiError ? own.error.message : 'Could not load your account.') : null
  // A tab that saves hands back the updated record: show it at once (the write also invalidates the query).
  const setCustomer = (updated: Customer): void => {
    qc.setQueryData(OWN_CUSTOMER_KEY, updated)
  }

  if (!session) return <></>

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Account"
        title="Your details and preferences"
        subtitle="Update your contact info, notification channels, and privacy choices."
      />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Couldn't load your account">{error}</Banner></div>}
      {loading && <p style={{ color: 'var(--color-ink-3)' }}>Loading your account…</p>}

      {!loading && !customer && !error && (
        <Banner variant="info" title="No customer profile linked">
          Your sign-in isn&apos;t linked to a customer record yet. Contact support to complete your account setup.
        </Banner>
      )}

      {customer && (
        <>
          <Tabs
            items={[
              { key: 'Profile', label: 'Profile' },
              { key: 'Notifications', label: 'Notifications' },
              { key: 'Privacy', label: 'Privacy' },
            ]}
            active={tab}
            onChange={(t) => setTab(t as TabKey)}
          />
          {tab === 'Profile' && <ProfileTab customer={customer} onSaved={setCustomer} />}
          {tab === 'Notifications' && <NotificationsTab customer={customer} onSaved={setCustomer} />}
          {tab === 'Privacy' && <PrivacyTab customer={customer} />}
        </>
      )}
    </div>
  )
}
