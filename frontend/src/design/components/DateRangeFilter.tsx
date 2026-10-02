/**
 * DateRangeFilter — a button that opens a preset-list popover for filtering a
 * list by "created within the last N days". Used by pages whose list API
 * supports `created_after`/`created_before` (see services/tracking/handler.py
 * GET /v1/containers for the container list's version of this contract).
 *
 * Deliberately opt-in: `value={null}` (the default) means "no date filter" —
 * callers must never default this to a preset, since silently scoping a list
 * to the last 30 days can hide the majority of a tenant's records.
 *
 * Usage:
 *   const [days, setDays] = useState<number | null>(null)
 *   <DateRangeFilter value={days} onChange={setDays} />
 */
import { useState, type JSX } from 'react'
import { Button } from './Button'
import type { IconName } from './Icon'
import { Icon } from './Icon'
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
  /** Currently selected preset's `days`, or null for "All time". */
  value: number | null
  onChange: (days: number | null) => void
  presets?: DateRangePreset[]
  icon?: IconName
}

export function DateRangeFilter({
  value,
  onChange,
  presets = DEFAULT_DATE_RANGE_PRESETS,
  icon = 'calendar',
}: DateRangeFilterProps): JSX.Element {
  const [open, setOpen] = useState(false)
  const active = presets.find((p) => p.days === value) ?? presets[presets.length - 1]!

  return (
    <div className={styles.root}>
      <Button variant="secondary" icon={icon} onClick={() => setOpen((o) => !o)}>
        {active.label}
      </Button>

      {open && (
        <>
          <div className={styles.overlay} onClick={() => setOpen(false)} />
          <div className={styles.dropdown} role="listbox" aria-label="Date range">
            {presets.map((preset) => {
              const isActive = preset.days === value
              return (
                <button
                  key={preset.label}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  className={[styles.dropdownItem, isActive ? styles.dropdownItemActive : ''].join(' ')}
                  onClick={() => {
                    onChange(preset.days)
                    setOpen(false)
                  }}
                >
                  <span className={styles.checkSlot}>
                    {isActive && <Icon name="check" size={13} color="var(--color-primary)" />}
                  </span>
                  {preset.label}
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
