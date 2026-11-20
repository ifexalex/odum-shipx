import { useState, type FormEvent, type JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useIdempotencyKey } from '../../api/useIdempotencyKey'
import { containersApi } from '../../api/tracking'
import { containerCapacitiesApi } from '../../api/tenantManagement'
import { containerCapacityKeys } from '../../api/keys'
import { ApiError } from '../../api/client'
import { Banner, Button, Card, Combobox, Field, type ComboboxOption, DateField } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './CreateContainer.module.css'
import { toast } from '../../design/toast'

// Vessel/voyage/shipping-line/seal-number/container-type columns were added to
// the `container` table in migration 030, so this form now captures the full
// set the China mockup (china-screens.jsx CreateContainer) shows. All of them
// are optional server-side — only container_number is required.
export function CreateContainer(): JSX.Element {
  const navigate = useNavigate()
  const { key, regenerate } = useIdempotencyKey()
  const { data: capacities = [] } = useQuery({
    queryKey: containerCapacityKeys.list(),
    queryFn: containerCapacitiesApi.list,
  })
  const [containerNumber, setContainerNumber] = useState('')
  const [capacityId, setCapacityId] = useState('')
  const [sealNumber, setSealNumber] = useState('')
  const [vesselName, setVesselName] = useState('')
  const [voyageNumber, setVoyageNumber] = useState('')
  const [shippingLine, setShippingLine] = useState('')
  const [parcelNumber, setParcelNumber] = useState('')
  const [origin, setOrigin] = useState('China')
  const [destination, setDestination] = useState('Nigeria')
  const [estimatedArrivalDate, setEstimatedArrivalDate] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedCapacity = capacities.find((c) => c.id === capacityId) ?? null
  const capacityOptions: ComboboxOption[] = capacities.map((c) => ({
    value: c.id,
    label: c.name,
    meta: `${c.capacity_cbm} CBM capacity${c.recommended_cbm ? ` · recommended ${c.recommended_cbm} CBM` : ''}${c.is_custom ? ' · custom' : ''}`,
  }))

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const container = await containersApi.create(
        {
          container_number: containerNumber,
          container_type: selectedCapacity?.name || undefined,
          capacity_cbm: selectedCapacity?.capacity_cbm,
          recommended_cbm: selectedCapacity?.recommended_cbm ?? undefined,
          seal_number: sealNumber || undefined,
          vessel_name: vesselName || undefined,
          voyage_number: voyageNumber || undefined,
          shipping_line: shippingLine || undefined,
          parcel_number: parcelNumber || undefined,
          origin,
          destination,
          estimated_arrival_date: estimatedArrivalDate || undefined,
          notes: notes || undefined,
        },
        key,
      )
      toast.success('Container created', container.container_number)
      regenerate()
      navigate(`/containers/${container.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the container.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <PageHeader
        title="Create new container"
        meta="Set up the container. You'll attach customer packing lists once it exists."
      />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't create container">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Card padding="large">
          <SectionHead title="Container details" sub="ISO 6346 format · validated server-side" />
          <div className={styles.spacerLg} />
          <Field
            label="Container number"
            name="containerNumber"
            required
            icon="container"
            placeholder="e.g. MSCU1234567"
            value={containerNumber}
            onChange={(event) => setContainerNumber(event.target.value.toUpperCase())}
          />
          <div className={styles.grid2}>
            <div>
              <label className={styles.capacityLabel} htmlFor="capacitySelect">
                Container capacity<span className={styles.optionalTag}>Optional</span>
              </label>
              <Combobox
                id="capacitySelect"
                ariaLabel="Container capacity"
                options={capacityOptions}
                value={capacityId}
                onChange={setCapacityId}
                placeholder="Search or select a capacity…"
                searchPlaceholder="Search capacities…"
                emptyText="No capacity matches"
              />
              <span className={styles.capacityHelper}>
                {selectedCapacity
                  ? `${selectedCapacity.capacity_cbm} CBM usable · recommended load ${selectedCapacity.recommended_cbm ?? '—'} CBM`
                  : 'Sets the utilization bar. Admins can add custom capacities in Settings → Container capacities.'}
              </span>
            </div>
            <Field
              label="Seal number"
              name="sealNumber"
              optional
              placeholder="e.g. SHX-04891"
              helper="Optional · added at packing time"
              value={sealNumber}
              onChange={(event) => setSealNumber(event.target.value)}
            />
          </div>
          <Field
            label="Parcel number"
            name="parcelNumber"
            optional
            placeholder="e.g. SHX-04891"
            helper="Optional — added at packing time if not known yet"
            value={parcelNumber}
            onChange={(event) => setParcelNumber(event.target.value)}
          />

          <SectionHead title="Vessel & voyage" />
          <div className={styles.spacerSm} />
          <Field
            label="Vessel name"
            name="vesselName"
            optional
            placeholder="e.g. MSC Altair"
            value={vesselName}
            onChange={(event) => setVesselName(event.target.value)}
          />
          <div className={styles.grid2}>
            <Field
              label="Voyage number"
              name="voyageNumber"
              optional
              placeholder="e.g. 248E"
              value={voyageNumber}
              onChange={(event) => setVoyageNumber(event.target.value)}
            />
            <Field
              label="Shipping line"
              name="shippingLine"
              optional
              placeholder="e.g. Mediterranean Shipping Co."
              value={shippingLine}
              onChange={(event) => setShippingLine(event.target.value)}
            />
          </div>

          <SectionHead title="Route" />
          <div className={styles.spacerSm} />
          <div className={styles.grid2}>
            <Field
              label="Origin"
              name="origin"
              required
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
            />
            <Field
              label="Destination"
              name="destination"
              required
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            />
          </div>

          <SectionHead title="Schedule" />
          <div className={styles.spacerSm} />
          <DateField
            label="Estimated arrival date"
            name="estimatedArrivalDate"
            optional
            value={estimatedArrivalDate}
            onChange={(event) => setEstimatedArrivalDate(event.target.value)}
          />

          <Field
            label="Internal notes"
            name="notes"
            optional
            multiline
            placeholder="Anything special about this container…"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </Card>

        <div className={styles.actions}>
          <Button type="button" variant="ghost" icon="arrowleft" onClick={() => navigate('/containers')}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" icon="check" loading={submitting} disabled={!containerNumber}>
            Create container
          </Button>
        </div>
      </form>
    </div>
  )
}
