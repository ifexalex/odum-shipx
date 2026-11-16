/**
 * Warehouses — tenant config.
 *
 * A shipping company can run multiple destination warehouses (branches) that a
 * customer's goods arrive at. This page lets a tenant_admin add/edit them, set
 * one as the default, and deactivate ones no longer in use. The list feeds the
 * arrival-warehouse picker when creating a packing list, and the release-note /
 * pickup letterhead. tenant_admin only (route-guarded).
 */
import { useCallback, useRef, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { warehousesApi, type CreateWarehouseInput, type Warehouse } from '../../api/warehouses'
import { useSetDefaultWarehouse, useWarehouses } from '../../hooks/useWarehouses'
import {
  Badge,
  Banner,
  Button,
  Card,
  Check,
  CountrySelect,
  Field,
  PhoneField,
  StateSelect,
  Table,
  DialogGuard,
} from '../../design/components'
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
  // Anchors the state picker (migration 057). Defaults to the platform's
  // destination market for a new branch.
  const [country, setCountry] = useState(existing?.country ?? 'Nigeria')
  const [address, setAddress] = useState(existing?.address ?? '')
  const [phone, setPhone] = useState(existing?.phone ?? '')
  // Create-only. Promoting an existing warehouse is the dedicated "Set default"
  // row action, which moves the flag atomically; offering it here too would be
  // two routes to one outcome with different semantics.
  const [makeDefault, setMakeDefault] = useState(false)
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
      country: country.trim() || undefined,
      address: address.trim() || undefined,
      phone: phone.trim() || undefined,
      ...(isEdit ? {} : { is_default: makeDefault }),
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
      <DialogGuard onClose={onCancel} />
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
          <CountrySelect
            label="Country"
            name="warehouse_country"
            value={country}
            onChange={(next) => {
              setCountry(next)
              // The state list is country-specific, so a state chosen for the
              // previous country would be wrong (and unselectable) for the new
              // one. Clear it rather than submit a mismatched pair.
              setState('')
            }}
          />
          <StateSelect
            country={country}
            name="warehouse_state"
            optional
            value={state}
            onChange={setState}
          />
        </div>
        <div className={styles.grid2}>
          <Field
            label="City"
            name="warehouse_city"
            optional
            placeholder="e.g. Onitsha"
            value={city}
            onChange={(e) => setCity(e.target.value)}
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
        <PhoneField
          label="Phone"
          name="warehouse_phone"
          optional
          value={phone}
          onChange={setPhone}
        />
        {!isEdit && (
          <label
            style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, cursor: 'pointer' }}
          >
            <Check checked={makeDefault} onChange={setMakeDefault} disabled={submitting} />
            <span style={{ fontSize: 13 }}>
              Make this the default warehouse
              <span style={{ color: 'var(--color-ink-3)', display: 'block', fontSize: 12 }}>
                Pre-selected on new packing lists and used on release-note letterheads.
              </span>
            </span>
          </label>
        )}
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
  const [actionError, setActionError] = useState<string | null>(null)
  const [modal, setModal] = useState<{ open: boolean; existing: Warehouse | null }>({
    open: false,
    existing: null,
  })
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // The error banner renders at the top of the page, above the table. An action
  // taken on a row further down could therefore fail with its only feedback
  // scrolled out of view — reported as "I click it and nothing happens". Scroll
  // the banner into view whenever one appears so a failure is never silent.
  const bannerRef = useRef<HTMLDivElement | null>(null)

  const fail = useCallback((message: string) => {
    setActionError(message)
    // After paint, so the banner exists to scroll to.
    requestAnimationFrame(() => {
      bannerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [])

  // 7.150 flagged this page specifically: it hand-rolled a loader calling
  // warehousesApi.list() directly while `useWarehouses` already existed and
  // read the very same warehouseKeys.all slot.
  const { data: warehouses = [], isLoading: loading, error: loadError } = useWarehouses()

  // `handleSetDefault` previously called warehousesApi.setDefault directly,
  // duplicating this mutation hook — the other half of what 7.150 flagged here.
  const setDefaultWarehouse = useSetDefaultWarehouse()

  // A load failure renders the banner without the scroll-into-view that `fail`
  // does. That scroll exists for a row action failing below the fold; when the
  // list itself could not load there are no rows to be scrolled away from.
  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load warehouses.'
      : null)

  async function handleSetDefault(id: string): Promise<void> {
    setBusyId(id)
    setActionError(null)
    setNotice(null)
    try {
      const updated = await setDefaultWarehouse.mutateAsync(id)
      // Confirm explicitly. The only previous signal was the row's badge
      // changing, which is easy to miss and indistinguishable from nothing
      // having happened.
      setNotice(`${updated.name} is now the default warehouse.`)
    } catch (err) {
      fail(err instanceof ApiError ? err.message : 'Could not set default warehouse.')
    } finally {
      setBusyId(null)
    }
  }

  /**
   * Delete a warehouse for real.
   *
   * The backend refuses with rule_id WAREHOUSE_IN_USE when a release note,
   * pickup record, payment record or packing list references it — those records
   * must keep the warehouse they were issued against. Rather than dead-ending,
   * offer to retire it instead, which hides it from pickers and (since migration
   * 056) frees its name.
   */
  async function handleRemove(warehouse: Warehouse): Promise<void> {
    if (!window.confirm(`Permanently delete “${warehouse.name}”? This cannot be undone.`)) return
    setBusyId(warehouse.id)
    setActionError(null)
    setNotice(null)
    try {
      await warehousesApi.remove(warehouse.id)
      setNotice(`${warehouse.name} was deleted.`)
    } catch (err) {
      if (err instanceof ApiError && err.ruleId === 'WAREHOUSE_IN_USE') {
        const retire = window.confirm(
          `${err.message}\n\nRetire “${warehouse.name}” instead?`,
        )
        if (retire) {
          try {
            await warehousesApi.deactivate(warehouse.id)
            setNotice(`${warehouse.name} was retired. Its name is free to reuse.`)
          } catch (retireErr) {
            fail(
              retireErr instanceof ApiError ? retireErr.message : 'Could not retire warehouse.',
            )
          }
        }
      } else {
        fail(err instanceof ApiError ? err.message : 'Could not delete warehouse.')
      }
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
      <div ref={bannerRef}>
        {error && (
          <div className={styles.banner}>
            <Banner variant="error" title="Error">
              {error}
            </Banner>
          </div>
        )}
        {notice && !error && (
          <div className={styles.banner}>
            <Banner variant="success" title="Done">
              {notice}
            </Banner>
          </div>
        )}
      </div>

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
                    onClick={() => void handleRemove(w)}
                  >
                    Delete
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
          }}
        />
      )}
    </div>
  )
}
