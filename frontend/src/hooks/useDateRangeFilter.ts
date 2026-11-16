import { useState } from 'react'
import { isoDateOffset } from '../lib/format'

export interface DateRangeFilterState {
  /** Preset "last N days", or null for "All time" — drives <DateRangeFilter>. */
  daysBack: number | null
  /** Exact custom dates (YYYY-MM-DD) — take precedence over the preset once set. */
  dateFrom: string
  dateTo: string
  /** Resolved query params: custom date wins over the preset when both would apply. */
  createdAfter: string | undefined
  createdBefore: string | undefined
  /** Picking a preset clears any custom dates, and vice versa, so the two
   * controls can never silently fight over which one is "active". */
  handlePreset: (days: number | null) => void
  handleCustomFrom: (value: string) => void
  handleCustomTo: (value: string) => void
  /** True if any date filter (preset or custom) is currently applied. */
  isActive: boolean
  clear: () => void
}

/**
 * useDateRangeFilter — the preset/custom-date-range logic shared by every
 * list page's "When" filter (ActivityLog, ContainerList, BillingList,
 * ClaimList, NotificationLog, TenantReports). Extracted after the same
 * preset+custom pairing was hand-rolled per page; each page still renders
 * its own <DateRangeFilter> + "From (custom)"/"To (custom)" inputs using
 * this hook's state, since each page's surrounding filter-bar markup differs.
 */
export function useDateRangeFilter(): DateRangeFilterState {
  const [daysBack, setDaysBack] = useState<number | null>(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  // Resolved when the preset is chosen, not during render. Date.now() is impure,
  // so computing it per render also meant the window silently slid forward as
  // the page sat open — two requests with the same "Last 7 days" selected could
  // ask for different ranges. Pinning it at selection fixes both.
  const [presetFrom, setPresetFrom] = useState<string | undefined>(undefined)

  const createdAfter = dateFrom || presetFrom
  const createdBefore = dateTo || undefined

  function handlePreset(days: number | null): void {
    setDaysBack(days)
    setPresetFrom(days ? isoDateOffset(-days) : undefined)
    setDateFrom('')
    setDateTo('')
  }
  function handleCustomFrom(value: string): void {
    setDateFrom(value)
    setDaysBack(null)
    setPresetFrom(undefined)
  }
  function handleCustomTo(value: string): void {
    setDateTo(value)
    setDaysBack(null)
    setPresetFrom(undefined)
  }
  function clear(): void {
    setDaysBack(null)
    setPresetFrom(undefined)
    setDateFrom('')
    setDateTo('')
  }

  return {
    daysBack,
    dateFrom,
    dateTo,
    createdAfter,
    createdBefore,
    handlePreset,
    handleCustomFrom,
    handleCustomTo,
    isActive: !!(daysBack || dateFrom || dateTo),
    clear,
  }
}
