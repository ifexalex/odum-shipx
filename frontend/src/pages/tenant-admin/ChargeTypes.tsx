/**
 * 4.4 — Charge Types (Section 4 of the prototype, tenant-config-screens.jsx).
 *
 * Tenant-level catalogue of reusable misc-charge presets (name, default
 * amount, description). Used by BillingDetail's AddChargeModal to pre-fill
 * charges. tenant_admin only (route-guarded).
 */
import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configApi, type ChargeType } from '../../api/tenantManagement'
import { configKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Badge, Banner, Button, Card, Field, Mono, Table, DialogGuard } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'
import { formatNgn } from '../../lib/format'

interface ChargeTypeModalProps {
  existing: ChargeType | null
  onCancel: () => void
  onSuccess: () => void
}

function ChargeTypeModal({ existing, onCancel, onSuccess }: ChargeTypeModalProps): JSX.Element {
  const [name, setName] = useState(existing?.name ?? '')
  const [amount, setAmount] = useState(existing ? String(Number(existing.amount_ngn)) : '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = name.trim().length > 0 && Number(amount) > 0 && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      if (existing) {
        await configApi.updateChargeType(existing.id, {
          name,
          amount_ngn: amount,
          description: description || undefined,
        })
      } else {
        await configApi.createChargeType({
          name,
          amount_ngn: amount,
          description: description || undefined,
        })
      }
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save charge type.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(11,47,13,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 200,
        padding: 'var(--space-4)',
      }}
      onClick={onCancel}
    >
      <DialogGuard onClose={onCancel} />
      <div
        style={{
          background: 'var(--color-surface)',
          borderRadius: 14,
          padding: 'var(--space-6)',
          width: '100%',
          maxWidth: 480,
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 style={{ margin: 0, fontSize: 'var(--text-lg)', fontWeight: 700 }}>
          {existing ? 'Edit charge type' : 'New charge type'}
        </h3>
        {error && (
          <Banner variant="error" title="Save failed">
            {error}
          </Banner>
        )}
        <Field
          label="Name"
          name="charge_type_name"
          required
          placeholder="e.g. Customs Examination"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label="Default amount (₦)"
          name="charge_type_amount"
          required
          type="number"
          placeholder="e.g. 15000"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          helper="Pre-fills the amount when staff add this charge to a billing — editable per use."
        />
        <Field
          label="Description"
          name="charge_type_description"
          optional
          multiline
          placeholder="When should staff apply this charge?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
          <Button variant="ghost" size="lg" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="lg"
            icon="check"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {existing ? 'Save changes' : 'Create charge type'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ChargeTypes(): JSX.Element {
  const [modal, setModal] = useState<{ open: boolean; existing: ChargeType | null }>({
    open: false,
    existing: null,
  })
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: chargeTypes = [], isLoading: loading, error: loadError } = useQuery({
    queryKey: configKeys.chargeTypes(),
    queryFn: () => configApi.listChargeTypes(),
    staleTime: STALE_5_MIN,
  })

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load charge types.'
      : null)

  // No manual reload after the write: api/cacheInvalidation.ts invalidates
  // configKeys.all for any successful non-GET on /v1/tenant/charge-types, and
  // this query lives under that root.
  async function handleDeactivate(id: string): Promise<void> {
    setDeactivatingId(id)
    setActionError(null)
    try {
      await configApi.deactivateChargeType(id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not deactivate charge type.')
    } finally {
      setDeactivatingId(null)
    }
  }

  useTopBarSlot({
    subtitle:
      'Reusable presets for miscellaneous billing charges — customs examination, port handling, and similar.',
    actions: (
      <Button
        variant="primary"
        icon="plus"
        onClick={() => setModal({ open: true, existing: null })}
      >
        New charge type
      </Button>
    ),
  })

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Error">
            {error}
          </Banner>
        </div>
      )}

      <Card padding="none">
        <Table
          columns={[
            { title: 'Name' },
            { title: 'Default amount (₦)', align: 'right' },
            { title: 'Times used', align: 'right' },
            { title: 'Description' },
            { title: 'Status' },
            { title: '', width: '160px' },
          ]}
          rows={chargeTypes.map((t) => ({
            cells: [
              <span key="name" style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                {t.name}
              </span>,
              <Mono key="amt">{formatNgn(t.amount_ngn)}</Mono>,
              <span
                key="usage"
                title="Billing charges added from this type"
                style={{
                  fontSize: 'var(--text-xs)',
                  color: t.usage_count ? 'var(--color-ink-2)' : 'var(--color-ink-3)',
                }}
              >
                {t.usage_count ?? 0}×
              </span>,
              <span key="desc" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                {t.description ?? '—'}
              </span>,
              <Badge key="status" variant={t.is_active ? 'success' : 'neutral'}>
                {t.is_active ? 'Active' : 'Inactive'}
              </Badge>,
              <span key="actions" style={{ display: 'inline-flex', gap: 'var(--space-2)' }}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setModal({ open: true, existing: t })}
                >
                  Edit
                </Button>
                {t.is_active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={deactivatingId === t.id}
                    onClick={() => void handleDeactivate(t.id)}
                  >
                    Deactivate
                  </Button>
                )}
              </span>,
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>
              {loading ? 'Loading charge types…' : 'No charge types yet — create the first one.'}
            </span>
          }
        />
      </Card>

      {modal.open && (
        <ChargeTypeModal
          existing={modal.existing}
          onCancel={() => setModal({ open: false, existing: null })}
          onSuccess={() => setModal({ open: false, existing: null })}
        />
      )}
    </div>
  )
}
