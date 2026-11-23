import { useState, type FormEvent, type JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useIdempotencyKey } from '../../api/useIdempotencyKey'
import { containersApi } from '../../api/tracking'
import { containerCapacitiesApi } from '../../api/tenantManagement'
import { containerCapacityKeys } from '../../api/keys'
import { ApiError } from '../../api/client'
import { safeNextPath } from '../../auth/returnPath'
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
  // Set when another form sent the user here for a container it needs (FD-25: the packing-list wizard); they go back
  // to it afterwards instead of to the new container. Only ever an in-app path.
  const [searchParams] = useSearchParams()
  const returnTo = safeNextPath(searchParams.get('return'))
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
  const [showOptionalDetails, setShowOptionalDetails] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const trimmedNumber = containerNumber.trim()
  const isoValid = /^[A-Z]{4}\d{7}$/.test(trimmedNumber)
  const containerNumberHelper =
    trimmedNumber.length === 0
      ? 'Standard ISO 6346 format: 4 letters + 7 digits (e.g. MSCU1234567).'
      : isoValid
        ? 'Valid ISO 6346 format.'
        : 'Does not match standard 4-letter + 7-digit ISO 6346 format — verify before saving.'

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
      regenerate()
      if (returnTo) {
        toast.success('Container created', `${container.container_number} is ready to choose.`)
        navigate(returnTo)
      } else {
        toast.success('Container created', container.container_number)
        navigate(`/containers/${container.id}`)
      }
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
        meta={
          returnTo
            ? "Set up the container, and you'll go back to your packing list to choose it."
            : "Set up the container. You'll attach customer packing lists once it exists."
        }
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
            helper={containerNumberHelper}
            value={containerNumber}
            onChange={(event) => setContainerNumber(event.target.value.toUpperCase())}
          />
          <div style={{ marginBottom: 'var(--space-4)' }}>
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

          <SectionHead title="Route & schedule" />
          <div className={styles.spacerSm} />
          <div className={styles.grid2}>
            <Field
              label="Origin"
              name="origin"
              required
              placeholder="e.g. Guangzhou, Shenzhen, China"
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
            />
            <Field
              label="Destination"
              name="destination"
              required
              placeholder="e.g. Lagos, Nigeria"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            />
          </div>
          <DateField
            label="Estimated arrival date"
            name="estimatedArrivalDate"
            optional
            value={estimatedArrivalDate}
            onChange={(event) => setEstimatedArrivalDate(event.target.value)}
          />

          <div style={{ marginTop: 'var(--space-4)', marginBottom: 'var(--space-3)' }}>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={showOptionalDetails ? 'chevup' : 'chevdown'}
              onClick={() => setShowOptionalDetails((open) => !open)}
            >
              {showOptionalDetails
                ? 'Hide optional vessel, seal & notes'
                : 'Add optional vessel, seal & notes'}
            </Button>
          </div>

          {showOptionalDetails && (
            <>
              <div className={styles.grid2}>
                <Field
                  label="Seal number"
                  name="sealNumber"
                  optional
                  placeholder="e.g. SHX-04891"
                  helper="Added at packing time"
                  value={sealNumber}
                  onChange={(event) => setSealNumber(event.target.value)}
                />
                <Field
                  label="Parcel number"
                  name="parcelNumber"
                  optional
                  placeholder="e.g. SHX-04891"
                  helper="Optional — added at packing time"
                  value={parcelNumber}
                  onChange={(event) => setParcelNumber(event.target.value)}
                />
              </div>
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
              <Field
                label="Internal notes"
                name="notes"
                optional
                multiline
                placeholder="Anything special about this container…"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </>
          )}
        </Card>

        <div className={styles.actions}>
          <Button type="button" variant="ghost" icon="arrowleft" onClick={() => navigate(returnTo ?? '/containers')}>
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
