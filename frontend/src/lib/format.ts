/**
 * Shared display formatters (audit FE-03).
 *
 * Kept in one place so figures render identically wherever they appear — a
 * stat card on the dashboard and the same metric on its domain list page must
 * not drift (e.g. one showing `₦28,658,693.94` and clipping, the other
 * `₦28.66M`).
 *
 * **No page formats a number or a date itself.** A bare `toLocaleString()` follows the viewer's browser, so two users
 * saw the same amount written two ways, and `iso.slice(0, 10)` showed a raw UTC date. Everything here uses a fixed
 * locale and, for times, a fixed zone: **Lagos time (Africa/Lagos, WAT) for everyone**, the owner's decision of
 * 2026-11-16, so staff in China and Nigeria and customers all read the same time for the same event.
 * `lib/format.test.ts` fails if a page calls `toLocale*String` or slices an ISO date.
 */

/** Numbers group with commas and use a point for decimals, whatever the viewer's browser is set to. */
const NUMBER_LOCALE = 'en-NG'
/** Dates read day-month-year ("10 Nov 2026"), never month-first, whatever the viewer's browser is set to. */
const DATE_LOCALE = 'en-GB'
/** The zone every time is shown in. */
export const DISPLAY_TIME_ZONE = 'Africa/Lagos'
/** What the zone is called on screen. Lagos has no daylight saving, so this never changes. */
export const TIME_ZONE_LABEL = 'WAT'

/** Shown wherever a value is missing or unreadable, instead of "NaN" or "Invalid Date". */
const MISSING = '—'

/**
 * Compact Naira for stat cards and other width-constrained figures.
 *
 * Amounts can reach tens of millions, which overflow a ~210px stat card at the
 * display font size — so millions collapse to `₦X.XXM`, thousands to `₦XXXk`,
 * and smaller values render in full. Use the full `toLocaleString` form only
 * where horizontal space is not constrained (e.g. table cells, invoice lines).
 */
export function formatNgnCompact(value: string | number | null | undefined): string {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n) || n === 0) return '₦0'
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return `${sign}₦${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 10_000) return `${sign}₦${Math.round(abs / 1_000)}k`
  return `${sign}₦${numberFormat(0, 0).format(abs)}`
}

// ---------------------------------------------------------------------------
// Numbers and money
// ---------------------------------------------------------------------------

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const numberFormats = new Map<string, Intl.NumberFormat>()
function numberFormat(minimumFractionDigits: number, maximumFractionDigits: number): Intl.NumberFormat {
  const key = `${minimumFractionDigits}-${maximumFractionDigits}`
  let format = numberFormats.get(key)
  if (!format) {
    format = new Intl.NumberFormat(NUMBER_LOCALE, { minimumFractionDigits, maximumFractionDigits })
    numberFormats.set(key, format)
  }
  return format
}

/**
 * A plain number with grouping and at most `maxFractionDigits` decimals (rates, weights). Missing is "—".
 * Amounts of money go through `formatNgn` / `formatUsd`, which also write the currency.
 */
export function formatNumber(value: string | number | null | undefined, maxFractionDigits = 2): string {
  const n = toNumber(value)
  return n === null ? MISSING : numberFormat(0, maxFractionDigits).format(n)
}

/** A whole count with grouping ("12,480"). Missing is "—". */
export function formatCount(value: string | number | null | undefined): string {
  return formatNumber(value, 0)
}

/**
 * Naira in full: `₦174,375` for a whole amount, `₦174,375.50` when there are kobo (always two decimals then, never
 * `.5`). Missing is "—". Negative is `-₦1,200`; a caller that wants a typographic minus or a leading `+` writes
 * it and passes the absolute value. Money arrives as a Decimal string; the number conversion here is for display only.
 */
export function formatNgn(value: string | number | null | undefined): string {
  const n = toNumber(value)
  if (n === null) return MISSING
  return `${n < 0 ? '-' : ''}₦${formatAmount(Math.abs(n))}`
}

/** US dollars, always with cents: `$112.50`. Missing is "—". */
export function formatUsd(value: string | number | null | undefined): string {
  const n = toNumber(value)
  if (n === null) return MISSING
  return `${n < 0 ? '-' : ''}$${numberFormat(2, 2).format(Math.abs(n))}`
}

/**
 * An amount of money without its currency symbol (a column whose header names the currency): `174,375` for a whole
 * amount, `174,375.50` with kobo. Missing is "—".
 */
export function formatAmount(value: string | number | null | undefined): string {
  const n = toNumber(value)
  if (n === null) return MISSING
  const hasKobo = Math.round(Math.abs(n) * 100) % 100 !== 0
  return numberFormat(hasKobo ? 2 : 0, 2).format(n)
}

/**
 * Cubic metres to three decimals, as invoices price them: `2.500`. Missing is "—". Quantities arrive as Decimal
 * strings on the wire, so components format through this rather than calling `.toFixed()` themselves.
 */
export function formatCbm(value: string | number | null | undefined): string {
  const n = toNumber(value)
  return n === null ? MISSING : n.toFixed(3)
}

// ---------------------------------------------------------------------------
// Dates and times (Lagos time)
// ---------------------------------------------------------------------------

/** A calendar date with no time (`YYYY-MM-DD`): the same day for everyone, so it is never shifted between zones. */
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

type DateInput = string | number | Date | null | undefined

function parseDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const dateFormats = new Map<string, Intl.DateTimeFormat>()
function dateFormat(key: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  let format = dateFormats.get(key)
  if (!format) {
    format = new Intl.DateTimeFormat(DATE_LOCALE, options)
    dateFormats.set(key, format)
  }
  return format
}

export type DateStyle = 'short' | 'medium' | 'long'

const DATE_STYLES: Record<DateStyle, Intl.DateTimeFormatOptions> = {
  short: { day: 'numeric', month: 'short' }, // 10 Nov
  medium: { day: 'numeric', month: 'short', year: 'numeric' }, // 10 Nov 2026
  long: { day: 'numeric', month: 'long', year: 'numeric' }, // 10 November 2026
}

/**
 * A date as "10 Nov 2026" (`short`: "10 Nov", `long`: "10 November 2026"). A timestamp is converted to its Lagos date;
 * a plain `YYYY-MM-DD` (an ETA, a ship date) is taken as written. Missing or unreadable is "—".
 */
export function formatDate(value: DateInput, style: DateStyle = 'medium'): string {
  if (typeof value === 'string') {
    const plain = DATE_ONLY.exec(value)
    if (plain) {
      const day = new Date(Date.UTC(Number(plain[1]), Number(plain[2]) - 1, Number(plain[3])))
      return dateFormat(`${style}-utc`, { ...DATE_STYLES[style], timeZone: 'UTC' }).format(day)
    }
  }
  const date = parseDate(value)
  return date ? dateFormat(style, { ...DATE_STYLES[style], timeZone: DISPLAY_TIME_ZONE }).format(date) : MISSING
}

/** The clock part only, "11:04 WAT". */
export function formatTime(value: DateInput): string {
  const date = parseDate(value)
  if (!date) return MISSING
  const time = dateFormat('time', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: DISPLAY_TIME_ZONE })
  return `${time.format(date)} ${TIME_ZONE_LABEL}`
}

/**
 * A moment as "10 Nov 2026, 11:04 WAT" in Lagos time, the zone named so nobody has to guess (`year: false` drops the
 * year for dense tables of recent events). A plain `YYYY-MM-DD` has no time to show and comes back as a date.
 */
export function formatDateTime(value: DateInput, options: { year?: boolean } = {}): string {
  const withYear = options.year !== false
  if (typeof value === 'string' && DATE_ONLY.test(value)) return formatDate(value, withYear ? 'medium' : 'short')
  const date = parseDate(value)
  if (!date) return MISSING
  const format = dateFormat(withYear ? 'datetime' : 'datetime-no-year', {
    ...DATE_STYLES[withYear ? 'medium' : 'short'],
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: DISPLAY_TIME_ZONE,
  })
  return `${format.format(date)} ${TIME_ZONE_LABEL}`
}

const isoDayFormat = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: DISPLAY_TIME_ZONE,
})

/**
 * Today's date in Lagos as `YYYY-MM-DD`, for a date input's default or a query parameter. Not
 * `new Date().toISOString().slice(0, 10)`: that is the UTC date, which is still yesterday in Lagos for the first hour
 * of the day.
 */
export function todayIso(now: Date = new Date()): string {
  return isoDayFormat.format(now)
}

/** The Lagos date `days` from today (negative for the past) as `YYYY-MM-DD`: "last 30 days" presets and ETA windows. */
export function isoDateOffset(days: number, now: Date = new Date()): string {
  const [year, month, day] = todayIso(now).split('-').map(Number) as [number, number, number]
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10)
}

