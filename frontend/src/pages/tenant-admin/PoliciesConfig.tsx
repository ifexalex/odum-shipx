/**
 * Tenant Admin — Business Policies (/admin/config/policies, Phase 1, TC-01, D4).
 *
 * Lets the tenant admin configure the business rules previously frozen at tenant creation:
 *   - Storage fees (enabled, grace period days, daily fee per carton)
 *   - Refund & claim staff approval limit (USD)
 *   - Default customer credit limit & payment terms (NGN / days)
 *   - CBM dispute auto-escalation (enabled, days)
 *   - Storage pickup reminder days (first & final reminder)
 *
 * Every save takes an effective date (defaulting to tomorrow UTC) and records an
 * append-only history row so historical storage fees are never repriced.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configKeys } from '../../api/keys'
import {
  configApi,
  type PolicyHistoryEntry,
  type PolicyKey,
  type TenantPoliciesResponse,
} from '../../api/tenantManagement'
import {
  Action,
  Badge,
  Banner,
  Card,
  CheckboxField,
  DateField,
  EmptyState,
  Field,
  PageSkeleton,
  Table,
} from '../../design/components'
import { toast } from '../../design/toast'
import { formatDate, formatDateTime, formatNgn } from '../../lib/format'
import { STALE_30S } from '../../lib/queryClient'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'

const POLICY_LABELS: Record<PolicyKey, string> = {
  storage_fee: 'Storage fees',
  refund_threshold_usd: 'Refund & claim approval limit',
  credit_defaults: 'Default customer credit',
  dispute_escalation: 'Dispute auto-escalation',
  reminder_days: 'Storage pickup reminders',
}

function summarizePolicyValue(key: PolicyKey, val: Record<string, unknown> | null): string {
  if (!val) return '—'
  if (key === 'storage_fee') {
    if (!val.enabled) return 'Disabled'
    return `${formatNgn(Number(val.daily_fee_per_carton_ngn ?? 0))}/carton/day after ${val.grace_period_days ?? 14}d grace`
  }
  if (key === 'refund_threshold_usd') {
    return `$${val.staff_limit ?? 50} USD staff limit`
  }
  if (key === 'credit_defaults') {
    return `${formatNgn(Number(val.default_credit_limit_ngn ?? 0))} limit · ${val.default_credit_terms_days ?? 14}d terms`
  }
  if (key === 'dispute_escalation') {
    if (!val.enabled) return 'Disabled'
    return `Auto-escalate after ${val.auto_escalate_days ?? 5}d`
  }
  if (key === 'reminder_days') {
    return `Day ${val.storage_first_reminder ?? 7} & Day ${val.storage_final_reminder ?? 13}`
  }
  return JSON.stringify(val)
}

interface PolicyCardShellProps {
  policyKey: PolicyKey
  title: string
  description: string
  scheduled?: PolicyHistoryEntry
  defaultEffectiveDate: string
  saving: boolean
  onSave: (effectiveDate: string) => void
  children: JSX.Element
}

function PolicyCardShell({
  policyKey,
  title,
  description,
  scheduled,
  defaultEffectiveDate,
  saving,
  onSave,
  children,
}: PolicyCardShellProps): JSX.Element {
  const [effectiveDate, setEffectiveDate] = useState(defaultEffectiveDate)

  return (
    <Card padding="default">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-3)' }}>
        <div>
          <SectionHead title={title} />
          <p style={{ margin: 'var(--space-1) 0 0', fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>
            {description}
          </p>
        </div>
        {scheduled && (
          <Badge variant="info">
            Scheduled for {formatDate(scheduled.effective_date)}
          </Badge>
        )}
      </div>

      {scheduled && (
        <div style={{ marginTop: 'var(--space-3)' }}>
          <Banner variant="info" title={`Upcoming change (${formatDate(scheduled.effective_date)})`}>
            {summarizePolicyValue(policyKey, scheduled.new_value)} — set by {scheduled.changed_by_name ?? 'Admin'}.
          </Banner>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
        {children}
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 'var(--space-3)',
          marginTop: 'var(--space-4)',
          paddingTop: 'var(--space-3)',
          borderTop: '1px solid var(--color-line-soft)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 210 }}>
          <DateField
            label="Takes effect on"
            name={`${policyKey}_effective_date`}
            value={effectiveDate}
            onChange={(e) => setEffectiveDate(e.target.value)}
            helper="Defaults to tomorrow so past charges are never repriced."
          />
        </div>
        <Action variant="primary" loading={saving} onClick={() => onSave(effectiveDate)}>
          Save {title.toLowerCase()}
        </Action>
      </div>
    </Card>
  )
}

export function PoliciesConfig(): JSX.Element {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: configKeys.policies(),
    queryFn: () => configApi.getPolicies(),
    staleTime: STALE_30S,
  })

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Policies" meta="Storage fees, approval limits, default credit terms, escalation and reminders." />
        <PageSkeleton kind="form" label="Loading policies" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div>
        <PageHeader title="Policies" meta="Storage fees, approval limits, default credit terms, escalation and reminders." />
        <Banner variant="error">{error instanceof ApiError ? error.message : 'Could not load tenant policies.'}</Banner>
      </div>
    )
  }

  return (
    <PoliciesConfigForm
      key={data.history[0]?.id ?? 'initial'}
      initial={data}
      onUpdated={(updated) => qc.setQueryData(configKeys.policies(), updated)}
    />
  )
}

function PoliciesConfigForm({
  initial,
  onUpdated,
}: {
  initial: TenantPoliciesResponse
  onUpdated: (updated: TenantPoliciesResponse) => void
}): JSX.Element {
  const [savingKey, setSavingKey] = useState<PolicyKey | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Storage fee
  const [sfEnabled, setSfEnabled] = useState(initial.policies.storage_fee.enabled)
  const [sfGrace, setSfGrace] = useState(String(initial.policies.storage_fee.grace_period_days))
  const [sfDaily, setSfDaily] = useState(String(initial.policies.storage_fee.daily_fee_per_carton_ngn))

  // Refund & claim staff threshold
  const [refundLimitUsd, setRefundLimitUsd] = useState(String(initial.policies.refund_threshold_usd.staff_limit))

  // Default credit terms
  const [creditLimitNgn, setCreditLimitNgn] = useState(String(initial.policies.credit_defaults.default_credit_limit_ngn))
  const [creditTermsDays, setCreditTermsDays] = useState(String(initial.policies.credit_defaults.default_credit_terms_days))

  // Dispute escalation
  const [dispEnabled, setDispEnabled] = useState(initial.policies.dispute_escalation.enabled)
  const [dispDays, setDispDays] = useState(String(initial.policies.dispute_escalation.auto_escalate_days))

  // Reminder days
  const [remFirst, setRemFirst] = useState(String(initial.policies.reminder_days.storage_first_reminder))
  const [remFinal, setRemFinal] = useState(String(initial.policies.reminder_days.storage_final_reminder))

  async function savePolicy(
    key: PolicyKey,
    value: Record<string, unknown>,
    effectiveDate: string,
  ): Promise<void> {
    setSavingKey(key)
    setSaveError(null)
    try {
      const updated = await configApi.updatePolicy({
        policy_key: key,
        value,
        effective_date: effectiveDate || undefined,
      })
      onUpdated(updated)
      toast.success(`${POLICY_LABELS[key]} saved`, `Effective ${formatDate(effectiveDate || updated.default_effective_date)}`)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not save policy.')
    } finally {
      setSavingKey(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      <PageHeader
        title="Policies"
        meta="Business rules governing customer fees, staff approval limits, credit defaults, and reminders. Every change is audited with an effective date."
      />

      {saveError && <Banner variant="error">{saveError}</Banner>}

      <PolicyCardShell
        policyKey="storage_fee"
        title="Storage fees"
        description="Daily fee accrued per unreleased carton once the free storage grace period expires."
        scheduled={initial.scheduled.storage_fee}
        defaultEffectiveDate={initial.default_effective_date}
        saving={savingKey === 'storage_fee'}
        onSave={(eff) =>
          void savePolicy(
            'storage_fee',
            {
              enabled: sfEnabled,
              grace_period_days: Number(sfGrace),
              daily_fee_per_carton_ngn: Number(sfDaily),
            },
            eff,
          )
        }
      >
        <>
          <CheckboxField
            label="Charge daily storage fees after grace period"
            checked={sfEnabled}
            onChange={setSfEnabled}
          />
          <div className={styles.profileGrid}>
            <Field
              label="Free grace period (days)"
              name="storage_grace_days"
              type="number"
              value={sfGrace}
              onChange={(e) => setSfGrace(e.target.value)}
            />
            <Field
              label="Daily fee per carton (NGN)"
              name="storage_daily_ngn"
              type="number"
              value={sfDaily}
              onChange={(e) => setSfDaily(e.target.value)}
            />
          </div>
        </>
      </PolicyCardShell>

      <PolicyCardShell
        policyKey="refund_threshold_usd"
        title="Refund & claim approval limit"
        description="Maximum USD equivalent Nigeria office staff can approve on refunds or damage claims before escalating to a tenant admin."
        scheduled={initial.scheduled.refund_threshold_usd}
        defaultEffectiveDate={initial.default_effective_date}
        saving={savingKey === 'refund_threshold_usd'}
        onSave={(eff) =>
          void savePolicy('refund_threshold_usd', { staff_limit: Number(refundLimitUsd) }, eff)
        }
      >
        <Field
          label="Staff approval limit (USD)"
          name="refund_staff_limit_usd"
          type="number"
          value={refundLimitUsd}
          onChange={(e) => setRefundLimitUsd(e.target.value)}
          helper="Items above this amount appear in the Approvals inbox."
        />
      </PolicyCardShell>

      <PolicyCardShell
        policyKey="credit_defaults"
        title="Default customer credit"
        description="Fallback credit ceiling and payment window for customers without custom credit terms on their profile."
        scheduled={initial.scheduled.credit_defaults}
        defaultEffectiveDate={initial.default_effective_date}
        saving={savingKey === 'credit_defaults'}
        onSave={(eff) =>
          void savePolicy(
            'credit_defaults',
            {
              default_credit_limit_ngn: Number(creditLimitNgn),
              default_credit_terms_days: Number(creditTermsDays),
            },
            eff,
          )
        }
      >
        <div className={styles.profileGrid}>
          <Field
            label="Default credit limit (NGN)"
            name="default_credit_limit_ngn"
            type="number"
            value={creditLimitNgn}
            onChange={(e) => setCreditLimitNgn(e.target.value)}
            helper="Set to 0 to flag every credit release unless a customer has a custom limit."
          />
          <Field
            label="Default payment terms (days)"
            name="default_credit_terms_days"
            type="number"
            value={creditTermsDays}
            onChange={(e) => setCreditTermsDays(e.target.value)}
          />
        </div>
      </PolicyCardShell>

      <PolicyCardShell
        policyKey="dispute_escalation"
        title="Dispute auto-escalation"
        description="Automatically escalate unactioned CBM disputes to China office staff and tenant admins."
        scheduled={initial.scheduled.dispute_escalation}
        defaultEffectiveDate={initial.default_effective_date}
        saving={savingKey === 'dispute_escalation'}
        onSave={(eff) =>
          void savePolicy(
            'dispute_escalation',
            { enabled: dispEnabled, auto_escalate_days: Number(dispDays) },
            eff,
          )
        }
      >
        <>
          <CheckboxField
            label="Enable automatic dispute escalation"
            checked={dispEnabled}
            onChange={setDispEnabled}
          />
          <Field
            label="Auto-escalate after (days)"
            name="dispute_auto_escalate_days"
            type="number"
            value={dispDays}
            onChange={(e) => setDispDays(e.target.value)}
          />
        </>
      </PolicyCardShell>

      <PolicyCardShell
        policyKey="reminder_days"
        title="Storage pickup reminders"
        description="Days after release-note issuance on which customers receive first and final pickup reminders."
        scheduled={initial.scheduled.reminder_days}
        defaultEffectiveDate={initial.default_effective_date}
        saving={savingKey === 'reminder_days'}
        onSave={(eff) =>
          void savePolicy(
            'reminder_days',
            {
              storage_first_reminder: Number(remFirst),
              storage_final_reminder: Number(remFinal),
            },
            eff,
          )
        }
      >
        <div className={styles.profileGrid}>
          <Field
            label="First reminder (day)"
            name="storage_first_reminder"
            type="number"
            value={remFirst}
            onChange={(e) => setRemFirst(e.target.value)}
          />
          <Field
            label="Final reminder (day)"
            name="storage_final_reminder"
            type="number"
            value={remFinal}
            onChange={(e) => setRemFinal(e.target.value)}
          />
        </div>
      </PolicyCardShell>

      <Card padding="default">
        <SectionHead title="Policy change history" />
        <div style={{ marginTop: 'var(--space-3)' }}>
          <Table
            columns={[
              { title: 'Policy' },
              { title: 'Previous' },
              { title: 'New value' },
              { title: 'Effective' },
              { title: 'Changed by' },
            ]}
            rows={initial.history.map((entry) => ({
              cells: [
                <strong key="p">{POLICY_LABELS[entry.policy_key] ?? entry.policy_key}</strong>,
                <span key="old" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {summarizePolicyValue(entry.policy_key, entry.old_value)}
                </span>,
                <span key="new" style={{ fontSize: 'var(--text-xs)' }}>
                  {summarizePolicyValue(entry.policy_key, entry.new_value)}
                </span>,
                <span key="eff" style={{ fontSize: 'var(--text-xs)' }}>
                  {formatDate(entry.effective_date)}
                </span>,
                <div key="by" style={{ fontSize: 'var(--text-xs)' }}>
                  <div>{entry.changed_by_name ?? 'Admin'}</div>
                  <div style={{ color: 'var(--color-ink-4)' }}>{formatDateTime(entry.created_at)}</div>
                </div>,
              ],
            }))}
            emptyState={<EmptyState compact title="No policy changes recorded yet" />}
          />
        </div>
      </Card>
    </div>
  )
}
