/**
 * Container capacities — tenant config.
 *
 * Shows the ten built-in capacity presets (read-only) plus any custom presets
 * the tenant has added, and lets a tenant_admin add/remove custom ones. The
 * presets populate the create-container capacity picker and drive each
 * container's utilization bar. tenant_admin only (route-guarded).
 */
import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { containerCapacitiesApi, type ContainerCapacity } from '../../api/tenantManagement'
import { containerCapacityKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Badge, Banner, Button, Card, Field, Mono, Table, DialogGuard } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'

interface CapacityModalProps {
  /** null → create; a preset → edit. Defaults only allow editing recommended. */
  existing: ContainerCapacity | null
  onCancel: () => void
  onSuccess: () => void
}

function CapacityModal({ existing, onCancel, onSuccess }: CapacityModalProps): JSX.Element {
  const isEdit = existing !== null
  // A default preset's name + capacity are physical constants — only its
  // recommended load is tunable.
  const lockNameCapacity = isEdit && existing.is_custom === false
  const [name, setName] = useState(existing?.name ?? '')
  const [capacity, setCapacity] = useState(existing ? String(existing.capacity_cbm) : '')
  const [recommended, setRecommended] = useState(
    existing?.recommended_cbm != null ? String(existing.recommended_cbm) : '',
  )
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const capacityNum = Number(capacity)
  const recommendedNum = recommended ? Number(recommended) : null
  const recommendedTooHigh = recommendedNum !== null && capacityNum > 0 && recommendedNum > capacityNum
  const canSubmit =
    name.trim().length > 0 &&
    capacityNum > 0 &&
    (recommendedNum === null || recommendedNum > 0) &&
    !recommendedTooHigh &&
    !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      if (isEdit && existing) {
        await containerCapacitiesApi.update(existing.id, {
          // Clearing the field on a default reverts it to the built-in value.
          recommended_cbm: recommendedNum,
          ...(existing.is_custom
            ? { name: name.trim(), capacity_cbm: capacityNum }
            : {}),
        })
      } else {
        await containerCapacitiesApi.create({
          name: name.trim(),
          capacity_cbm: capacityNum,
          ...(recommendedNum !== null ? { recommended_cbm: recommendedNum } : {}),
        })
      }
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save capacity.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>
          {isEdit ? `Edit ${existing.name}` : 'New container capacity'}
        </h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Save failed">
              {error}
            </Banner>
          </div>
        )}
        <Field
          label="Name"
          name="capacity_name"
          required
          disabled={lockNameCapacity}
          placeholder="e.g. 53' Megabox"
          value={name}
          onChange={(e) => setName(e.target.value)}
          helper={lockNameCapacity ? "A default preset's name can't be changed." : undefined}
        />
        <Field
          label="Usable capacity (CBM)"
          name="capacity_cbm"
          required
          disabled={lockNameCapacity}
          type="number"
          placeholder="e.g. 76"
          value={capacity}
          onChange={(e) => setCapacity(e.target.value)}
          helper={
            lockNameCapacity
              ? "A default's physical capacity is fixed — only its recommended load is editable."
              : 'Internal usable volume in cubic metres.'
          }
        />
        <Field
          label="Recommended load (CBM)"
          name="recommended_cbm"
          optional
          type="number"
          placeholder="e.g. 70"
          value={recommended}
          onChange={(e) => setRecommended(e.target.value)}
          error={recommendedTooHigh ? 'Recommended load cannot exceed capacity.' : undefined}
          helper="Practical fill target shown on the container's utilization bar."
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={isEdit ? 'check' : 'plus'}
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {isEdit ? 'Save changes' : 'Add capacity'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ContainerCapacities(): JSX.Element {
  const [modal, setModal] = useState<{ open: boolean; existing: ContainerCapacity | null }>({
    open: false,
    existing: null,
  })
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // containerCapacityKeys.list() is the slot CreateContainer.tsx already reads,
  // so the two screens now share one cached list instead of fetching separately.
  const { data: capacities = [], isLoading: loading, error: loadError } = useQuery({
    queryKey: containerCapacityKeys.list(),
    queryFn: () => containerCapacitiesApi.list(),
    staleTime: STALE_5_MIN,
  })

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load container capacities.'
      : null)

  // No manual reload: api/cacheInvalidation.ts invalidates
  // containerCapacityKeys.all on any successful non-GET to
  // /v1/tenant/container-capacities.
  async function handleRemove(id: string): Promise<void> {
    setRemovingId(id)
    setActionError(null)
    try {
      await containerCapacitiesApi.remove(id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not remove capacity.')
    } finally {
      setRemovingId(null)
    }
  }

  useTopBarSlot({
    subtitle:
      'Capacity presets for new containers — pick one when creating a container to drive its utilization bar.',
    actions: (
      <Button variant="primary" icon="plus" onClick={() => setModal({ open: true, existing: null })}>
        Add capacity
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

      <Card padding={0}>
        <Table
          columns={[
            { title: 'Name' },
            { title: 'Capacity (CBM)', align: 'right' },
            { title: 'Recommended (CBM)', align: 'right' },
            { title: 'Source' },
            { title: '', width: '150px' },
          ]}
          rows={capacities.map((c) => ({
            cells: [
              <span key="name" style={{ fontWeight: 600, fontSize: 13 }}>
                {c.name}
              </span>,
              <Mono key="cap">{c.capacity_cbm}</Mono>,
              <Mono key="rec">{c.recommended_cbm ?? '—'}</Mono>,
              <Badge key="src" variant={c.is_custom ? 'info' : 'neutral'}>
                {c.is_custom ? 'Custom' : 'Default'}
              </Badge>,
              <span key="action" style={{ display: 'inline-flex', gap: 6 }}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setModal({ open: true, existing: c })}
                >
                  Edit
                </Button>
                {c.is_custom && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={removingId === c.id}
                    onClick={() => void handleRemove(c.id)}
                  >
                    Remove
                  </Button>
                )}
              </span>,
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {loading ? 'Loading capacities…' : 'No capacities configured.'}
            </span>
          }
        />
      </Card>

      {modal.open && (
        <CapacityModal
          existing={modal.existing}
          onCancel={() => setModal({ open: false, existing: null })}
          onSuccess={() => setModal({ open: false, existing: null })}
        />
      )}
    </div>
  )
}
