/**
 * Shared display formatters.
 *
 * Kept in one place so figures render identically wherever they appear — a
 * stat card on the dashboard and the same metric on its domain list page must
 * not drift (e.g. one showing `₦28,658,693.94` and clipping, the other
 * `₦28.66M`).
 */

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
  return `${sign}₦${abs.toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
}
