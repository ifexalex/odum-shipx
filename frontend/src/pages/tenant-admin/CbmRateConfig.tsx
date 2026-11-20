import { useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configKeys } from '../../api/keys'
import { configApi, type CbmRateConfig, type CbmRateCurrency, type CbmRateMode } from '../../api/tenantManagement'
import { useCbmRate } from '../../hooks/useConfig'
import { useSeedOnce } from '../../hooks/useSeedOnce'
import { Banner, Button, Card, Kvp, Mono, Field } from '../../design/components'
import { RateHistoryTable } from './DollarRateConfig'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'
import { toast } from '../../design/toast'

function symbol(currency: CbmRateCurrency): string {
  return currency === 'ngn' ? '₦' : '$'
}

function formatRateLine(config: CbmRateConfig): string {
  const s = symbol(config.currency)
  if (config.rate_mode === 'flat') {
    return `${s}${config.carton_rate.toFixed(2)} per CBM`
  }
  return `Cartons ${s}${config.carton_rate.toFixed(2)} · Bags ${s}${config.bag_rate.toFixed(2)} · Bales ${s}${config.bale_rate.toFixed(2)}`
}

export function CbmRateConfig(): JSX.Element {
  const qc = useQueryClient()
  const rate = useCbmRate({ freshOnOpen: true })
  const current: CbmRateConfig | null = rate.isFetchedAfterMount ? (rate.data ?? null) : null
  const loading = !rate.isFetchedAfterMount
  const [currency, setCurrency] = useState<CbmRateCurrency>('usd')
  const [rateMode, setRateMode] = useState<CbmRateMode>('flat')
  const [cartonRate, setCartonRate] = useState('')
  const [bagRate, setBagRate] = useState('')
  const [baleRate, setBaleRate] = useState('')
  const [minCbm, setMinCbm] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function fillForm(data: CbmRateConfig): void {
    setCurrency(data.currency)
    setRateMode(data.rate_mode)
    setCartonRate(String(data.carton_rate))
    setBagRate(String(data.bag_rate))
    setBaleRate(String(data.bale_rate))
    setMinCbm(String(data.min_cbm_per_item))
  }
  useSeedOnce(rate, fillForm)

  const loadError = rate.error ? (rate.error instanceof ApiError ? rate.error.message : 'Could not load CBM rate.') : null
  const error = saveError ?? loadError

  async function handleSave(): Promise<void> {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await configApi.updateCbmRate({
        currency,
        rate_mode: rateMode,
        carton_rate: Number(cartonRate),
        // The backend forces these equal to carton_rate in flat mode
        // regardless of what's sent — sending them anyway keeps the form's
        // own state consistent with what actually gets persisted.
        bag_rate: rateMode === 'flat' ? Number(cartonRate) : Number(bagRate),
        bale_rate: rateMode === 'flat' ? Number(cartonRate) : Number(baleRate),
        min_cbm_per_item: Number(minCbm) > 0 ? Number(minCbm) : undefined,
      })
      // Show the saved value at once; the write also invalidates every config query (api/cacheInvalidation.ts).
      qc.setQueryData(configKeys.cbm(), updated)
      fillForm(updated)
      toast.success('CBM rate updated', 'New invoices use it.')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not update CBM rate.')
    } finally {
      setSaving(false)
    }
  }

  const canSubmit = rateMode === 'flat'
    ? cartonRate !== '' && Number(cartonRate) > 0
    : [cartonRate, bagRate, baleRate].every((v) => v !== '' && Number(v) > 0)

  return (
    <div>
      <PageHeader
        title="CBM rate"
        meta="Freight charge per cubic metre, applied to customer billing."
      />

      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}

      {!loading && current && (
        <>
          <SectionHead title="Current rate" />
          <Card padding="default">
            <Kvp label="Currency" value={<Mono>{current.currency.toUpperCase()}</Mono>} />
            <Kvp label="Mode" value={<Mono>{current.rate_mode === 'flat' ? 'Single rate' : 'By package type'}</Mono>} />
            <Kvp label="Rate" value={<Mono color="var(--color-primary)">{formatRateLine(current)}</Mono>} divider={false} />
          </Card>

          <SectionHead title="Update rate" />
          <div className={styles.formCard}>
            <div>
              <label style={{ fontWeight: 600, fontSize: 'var(--text-md)', display: 'block', marginBottom: 'var(--space-2)' }}>
                Currency
              </label>
              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <Button variant={currency === 'usd' ? 'primary' : 'ghost'} onClick={() => setCurrency('usd')}>
                  Dollar ($)
                </Button>
                <Button variant={currency === 'ngn' ? 'primary' : 'ghost'} onClick={() => setCurrency('ngn')}>
                  Naira (₦)
                </Button>
              </div>
            </div>

            <div>
              <label style={{ fontWeight: 600, fontSize: 'var(--text-md)', display: 'block', marginBottom: 'var(--space-2)' }}>
                Rate by
              </label>
              <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
                <Button variant={rateMode === 'flat' ? 'primary' : 'ghost'} onClick={() => setRateMode('flat')}>
                  Single rate
                </Button>
                <Button variant={rateMode === 'per_package_type' ? 'primary' : 'ghost'} onClick={() => setRateMode('per_package_type')}>
                  By package type
                </Button>
              </div>
            </div>

            {rateMode === 'flat' ? (
              <Field
                label={`Rate (${symbol(currency)} per CBM)`}
                name="carton_rate"
                type="number"
                value={cartonRate}
                onChange={(e) => setCartonRate(e.target.value)}
                  placeholder="e.g. 45"
                  min="0.01"
                  step="0.01"
                />
            ) : (
              <>
                <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-4)', margin: 0 }}>
                  Any other package type (pallets, mixed, unspecified) bills at the carton rate.
                </p>
                {([
                  ['Cartons', cartonRate, setCartonRate],
                  ['Bags', bagRate, setBagRate],
                  ['Bales', baleRate, setBaleRate],
                ] as const).map(([label, value, setValue]) => (
                  <Field
                    key={label}
                    label={`${label} (${symbol(currency)} per CBM)`}
                    name={`${label.toLowerCase()}_rate`}
                    type="number"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                      placeholder="e.g. 45"
                      min="0.01"
                      step="0.01"
                    />
                ))}
              </>
            )}

            <Field
              label="Minimum CBM per item"
              name="min_cbm"
              type="number"
              value={minCbm}
              onChange={(e) => setMinCbm(e.target.value)}
                placeholder="e.g. 0.1"
                min="0.01"
                step="0.01"
              helper="A line item measuring below this is billed at this floor (handling minimum). Applied when a packing list is saved."
            />

            <div className={styles.formActions}>
              <Button variant="primary" loading={saving} disabled={!canSubmit} onClick={() => void handleSave()}>
                Update rate
              </Button>
            </div>
          </div>
          <RateHistoryTable rateType="cbm_rate" valueKey="carton_rate" prefix={symbol(currency)} />
        </>
      )}
    </div>
  )
}
