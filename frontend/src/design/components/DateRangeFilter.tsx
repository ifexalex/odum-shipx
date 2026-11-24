/**
 * DateRangeFilter — the one date control in a list's filter bar (FD-11): a button that opens a popover with presets
 * ("Last 7 days", "All time") and, when given the `range` from `useDateRangeFilter`, a custom From–To range in the
 * same popover. The button reads what is applied ("Last 30 days", "12 Nov – 19 Nov 2026", "Since 12 Nov 2026").
 *
 * Deliberately opt-in: no filter ("All time") is the default — silently scoping a list to the last 30 days can hide
 * most of a tenant's records.
 *
 *   const range = useDateRangeFilter()
 *   <DateRangeFilter label="Billed" range={range} />
 */
import { useState, type JSX } from 'react'
import type { DateRangeFilterState } from '../../hooks/useDateRangeFilter'
import { formatDate } from '../../lib/format'
import { Button } from './Button'
import { DateField } from './DateField'
import { Icon, type IconName } from './Icon'
import { Pressable } from './Pressable'
import styles from './DateRangeFilter.module.css'

export interface DateRangePreset {
  label: string
  /** Days to look back from now, or null for "All time" (no filter). */
  days: number | null
}

export const DEFAULT_DATE_RANGE_PRESETS: DateRangePreset[] = [
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'All time', days: null },
]

export interface DateRangeFilterProps {
  /** The state from `useDateRangeFilter`: presets and a custom range. */
  range?: DateRangeFilterState
  /** Preset-only use, without a custom range. */
  value?: number | null
  onChange?: (days: number | null) => void
  /** What the dates are of ("Created", "Billed"): names the control and the custom fields. */
  label?: string
  presets?: DateRangePreset[]
  icon?: IconName
}

function customLabel(from: string, to: string): string {
  if (from && to) return `${formatDate(from, 'short')} – ${formatDate(to)}`
  if (from) return `Since ${formatDate(from)}`
  return `Until ${formatDate(to)}`
}

export function DateRangeFilter({
  range,
  value,
  onChange,
  label = 'Date',
  presets = DEFAULT_DATE_RANGE_PRESETS,
  icon = 'calendar',
}: DateRangeFilterProps): JSX.Element {
  const [open, setOpen] = useState(false)
  const days = range ? range.daysBack : (value ?? null)
  const pick = (next: number | null): void => (range ? range.handlePreset(next) : onChange?.(next))
  const custom = Boolean(range && (range.dateFrom || range.dateTo))
  const active = presets.find((p) => p.days === days) ?? presets[presets.length - 1]!
  const buttonLabel = custom && range ? customLabel(range.dateFrom, range.dateTo) : active.label

  return (
    <div className={styles.root}>
      <Button variant="secondary" icon={icon} aria-haspopup="dialog" aria-expanded={open} aria-label={`${label}: ${buttonLabel}`} onClick={() => setOpen((o) => !o)}>
        {buttonLabel}
      </Button>

      {open && (
        <>
          <div className={styles.overlay} onClick={() => setOpen(false)} />
          <div className={styles.dropdown} role="dialog" aria-label={`${label} range`}>
            <div role="listbox" aria-label="Presets">
              {presets.map((preset) => {
                const isActive = !custom && preset.days === days
                return (
                  <Pressable
                    key={preset.label}
                    role="option"
                    aria-selected={isActive}
                    className={[styles.dropdownItem, isActive ? styles.dropdownItemActive : ''].join(' ')}
                    onClick={() => {
                      pick(preset.days)
                      setOpen(false)
                    }}
                  >
                    <span className={styles.checkSlot}>{isActive && <Icon name="check" size={13} color="var(--color-primary)" />}</span>
                    {preset.label}
                  </Pressable>
                )
              })}
            </div>
            {range && (
              <div className={styles.custom}>
                <div className={styles.customTitle}>Custom range</div>
                <DateField label="From" name={`${label.toLowerCase()}_from`} value={range.dateFrom} max={range.dateTo || undefined} onChange={(e) => range.handleCustomFrom(e.target.value)} />
                <DateField label="To" name={`${label.toLowerCase()}_to`} value={range.dateTo} min={range.dateFrom || undefined} onChange={(e) => range.handleCustomTo(e.target.value)} />
                <div className={styles.customActions}>
                  {range.isActive && (
                    <Button variant="ghost" size="sm" onClick={() => range.clear()}>
                      Clear
                    </Button>
                  )}
                  <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>
                    Done
                  </Button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
