/**
 * Notification template editor.
 *
 * SMS character counter (spec requirement — 07_domain_modules.md 7.9):
 *  - ≤ 160 chars → 1 segment (gray)
 *  - 161–320 chars → 2 segments (amber warning)
 *  - > 320 chars → 3+ segments (red warning)
 *
 * This is a cost/deliverability signal, NOT validation that blocks save.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configApi, type NotificationTemplate } from '../../api/tenantManagement'
import { configKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Banner, Button, Field, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './admin.module.css'
import { formatTime } from '../../lib/format'
import waStyles from './NotificationTemplates.module.css'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// SMS counter
// ---------------------------------------------------------------------------

function SmsCounter({ text }: { text: string }): JSX.Element {
  const len = text.length
  const segments = len === 0 ? 0 : len <= 160 ? 1 : len <= 320 ? 2 : Math.ceil(len / 160)
  const cssClass = len === 0 || len <= 160 ? styles.smsCounterOk : len <= 320 ? styles.smsCounterWarn : styles.smsCounterError

  return (
    <span className={`${styles.smsCounter} ${cssClass}`}>
      {len} chars · {segments} SMS segment{segments !== 1 ? 's' : ''}
      {len > 160 && len <= 320 && ' ⚠'}
      {len > 320 && ' ✗ high cost'}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Single template card
// ---------------------------------------------------------------------------

interface TemplateCardProps {
  template: NotificationTemplate
  onSaved: (updated: NotificationTemplate) => void
}

function TemplateCard({ template, onSaved }: TemplateCardProps): JSX.Element {
  const [body, setBody] = useState(template.template_body)
  const [subject, setSubject] = useState(template.subject ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isSms = template.channel === 'sms' || template.channel === 'whatsapp'

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await configApi.upsertNotificationTemplate(
        template.event_type,
        template.channel,
        { template_body: body, subject: subject || undefined },
      )
      onSaved(updated)
      toast.success('Message template saved')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save template.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.templateCard}>
      <div className={styles.templateHeader}>
        <div>
          <span className={styles.templateEventType}>{template.event_type.replace(/_/g, ' ')}</span>
          <span style={{ marginLeft: 'var(--space-2)', fontSize: 'var(--text-xs)', fontWeight: 700, padding: 'var(--space-0-5) var(--space-2)', borderRadius: 'var(--radius-sm)', background: 'var(--color-surface-muted)', color: 'var(--color-ink-4)' }}>
            {template.channel.toUpperCase()}
          </span>
        </div>
      </div>

      {error && <Banner variant="error">{error}</Banner>}

      {template.channel === 'email' && (
        <Field
          label="Subject"
          name={`subject-${template.event_type}-${template.channel}`}
          optional
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
      )}

      {template.channel === 'whatsapp' && body.trim() && (
        <div style={{ marginBottom: 'var(--space-3)' }}>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--color-ink-3)', marginBottom: 'var(--space-2)' }}>WhatsApp preview</div>
          <div className={waStyles.waBackdrop}>
            <div className={waStyles.waBubble}>
              {body}
              <div className={waStyles.waMeta}>
                {formatTime(new Date())} ✓✓
              </div>
            </div>
          </div>
        </div>
      )}

      <Field
        label="Message body"
        name="template_body"
        multiline
        rows={5}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Use {{variable}} for dynamic values e.g. {{customer_name}}, {{container_number}}"
        helper={isSms ? <SmsCounter text={body} /> : undefined}
      />

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button variant="primary" size="sm" loading={saving} disabled={!body.trim()} onClick={() => void handleSave()}>
          Save template
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function NotificationTemplates(): JSX.Element {
  const qc = useQueryClient()

  const { data: templates = [], isLoading: loading, error: loadError } = useQuery({
    queryKey: configKeys.notifications(),
    queryFn: () => configApi.listNotificationTemplates(),
    staleTime: STALE_5_MIN,
  })

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load templates.'
    : null

  // The PUT response carries the saved template, so write it straight into the
  // cache for an immediate frame. api/cacheInvalidation.ts also invalidates
  // configKeys.all for /v1/tenant/notification-templates, which reconciles
  // against the server right after — this just avoids a visible round-trip.
  function handleSaved(updated: NotificationTemplate): void {
    qc.setQueryData<NotificationTemplate[]>(configKeys.notifications(), (prev) =>
      (prev ?? []).map((t) =>
        t.event_type === updated.event_type && t.channel === updated.channel ? updated : t,
      ),
    )
  }

  // Group by event type
  const grouped = templates.reduce<Record<string, NotificationTemplate[]>>((acc, t) => {
    const key = t.event_type
    if (!acc[key]) acc[key] = []
    acc[key].push(t)
    return acc
  }, {})

  return (
    <div>
      <PageHeader
        title="Notification Templates"
        subtitle="Customise SMS, WhatsApp, and Email messages sent to customers."
      />

      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}
      {loading && <LinesSkeleton label="Loading templates" />}

      {!loading && templates.length === 0 && (
        <p style={{ color: 'var(--color-ink-4)', marginTop: 'var(--space-6)' }}>
          No notification templates configured. They will appear here once seeded by the platform admin.
        </p>
      )}

      {Object.entries(grouped).map(([eventType, tpls]) => (
        <div key={eventType} className={styles.section}>
          <p style={{ fontWeight: 700, fontSize: 'var(--text-md)', color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', marginBottom: 'var(--space-2)' }}>
            {eventType.replace(/_/g, ' ')}
          </p>
          {tpls.map((t) => (
            <TemplateCard
              key={`${t.event_type}-${t.channel}`}
              template={t}
              onSaved={handleSaved}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
