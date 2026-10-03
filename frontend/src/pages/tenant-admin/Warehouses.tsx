/**
 * Warehouses — tenant config.
 *
 * A shipping company can run multiple destination warehouses (branches) that a
 * customer's goods arrive at. This page lets a tenant_admin add/edit them, set
 * one as the default, and deactivate ones no longer in use. The list feeds the
 * arrival-warehouse picker when creating a packing list, and the release-note /
 * pickup letterhead. tenant_admin only (route-guarded).
 */
import { useCallback, useEffect, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { warehousesApi, type CreateWarehouseInput, type Warehouse } from '../../api/warehouses'
import { Badge, Banner, Button, Card, Field, Table } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './admin.module.css'

interface WarehouseModalProps {
  existing: Warehouse | null
  onCancel: () => void
  onSuccess: () => void
}

function WarehouseModal({ existing, onCancel, onSuccess }: WarehouseModalProps): JSX.Element {
  const isEdit = existing !== null
  const [name, setName] = useState(existing?.name ?? '')
  const [city, setCity] = useState(existing?.city ?? '')
  const [state, setState] = useState(existing?.state ?? '')
  const [address, setAddress] = useState(existing?.address ?? '')
  const [phone, setPhone] = useState(existing?.phone ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = name.trim().length > 0 && !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    const body: CreateWarehouseInput = {
      name: name.trim(),
      city: city.trim() || undefined,
      state: state.trim() || undefined,
      address: address.trim() || undefined,
      phone: phone.trim() || undefined,
    }
    try {
      if (isEdit && existing) {
        await warehousesApi.update(existing.id, body)
      } else {
        await warehousesApi.create(body)
      }
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save warehouse.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>{isEdit ? `Edit ${existing.name}` : 'New warehouse'}</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Save failed">
              {error}
            </Banner>
          </div>
        )}
        <Field
          label="Name"
          name="warehouse_name"
          required
          placeholder="e.g. Lagos — Trade Fair"
          value={name}
          onChange={(e) => setName(e.target.value)}
          helper="Shown in the arrival-warehouse picker and on release-note letterheads."
        />
        <div className={styles.grid2}>
          <Field
            label="City"
            name="warehouse_city"
            optional
            placeholder="e.g. Lagos"
            value={city}
            onChange={(e) => setCity(e.target.value)}
          />
          <Field
            label="State"
            name="warehouse_state"
            optional
            placeholder="e.g. Lagos"
            value={state}
            onChange={(e) => setState(e.target.value)}
          />
        </div>
        <Field
          label="Address"
          name="warehouse_address"
          optional
          placeholder="Street address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
        />
        <Field
          label="Phone"
          name="warehouse_phone"
          optional
          placeholder="e.g. 08012345678"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
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
            {isEdit ? 'Save changes' : 'Add warehouse'}
          </Button>
        </div>
      </div>
    </div>
  )
}

export function Warehouses(): JSX.Element {
  const navigate = useNavigate()
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modal, setModal] = useState<{ open: boolean; existing: Warehouse | null }>({
    open: false,
    existing: null,
  })
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setWarehouses(await warehousesApi.list())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load warehouses.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function handleSetDefault(id: string): Promise<void> {
    setBusyId(id)
    setError(null)
    try {
      await warehousesApi.setDefault(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not set default warehouse.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleRemove(id: string): Promise<void> {
    setBusyId(id)
    setError(null)
    try {
      await warehousesApi.deactivate(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not remove warehouse.')
    } finally {
      setBusyId(null)
    }
  }

  useTopBarSlot({
    subtitle:
      'Destination warehouses your customers’ goods arrive at — the arrival-warehouse picker and release-note letterheads draw from this list.',
    actions: (
      <Button variant="primary" icon="plus" onClick={() => setModal({ open: true, existing: null })}>
        Add warehouse
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
            { title: 'Location' },
            { title: 'Phone' },
            { title: 'Status' },
            { title: '', width: '210px' },
          ]}
          rows={warehouses.map((w) => ({
            cells: [
              <span key="name" style={{ fontWeight: 600, fontSize: 13 }}>
                {w.name}
              </span>,
              <span key="loc" style={{ color: 'var(--color-ink-2)', fontSize: 13 }}>
                {[w.city, w.state].filter(Boolean).join(', ') || '—'}
              </span>,
              <span key="phone" style={{ color: 'var(--color-ink-2)', fontSize: 13 }}>
                {w.phone || '—'}
              </span>,
              w.is_default ? (
                <Badge key="st" variant="success">
                  Default
                </Badge>
              ) : (
                <Badge key="st" variant="neutral">
                  Active
                </Badge>
              ),
              <span key="action" style={{ display: 'inline-flex', gap: 6 }}>
                {!w.is_default && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={busyId === w.id}
                    onClick={() => void handleSetDefault(w.id)}
                  >
                    Set default
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => setModal({ open: true, existing: w })}>
                  Edit
                </Button>
                {!w.is_default && (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={busyId === w.id}
                    onClick={() => void handleRemove(w.id)}
                  >
                    Remove
                  </Button>
                )}
              </span>,
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {loading ? 'Loading warehouses…' : 'No warehouses configured.'}
            </span>
          }
        />
      </Card>

      <div style={{ marginTop: 24 }}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/admin/config')}>
          Back to configuration
        </Button>
      </div>

      {modal.open && (
        <WarehouseModal
          existing={modal.existing}
          onCancel={() => setModal({ open: false, existing: null })}
          onSuccess={() => {
            setModal({ open: false, existing: null })
            void load()
          }}
        />
      )}
    </div>
  )
}
