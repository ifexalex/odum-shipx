import { describe, expect, it } from 'vitest'
import {
  formatCbm,
  formatCount,
  formatDate,
  formatDateTime,
  formatNgn,
  formatNgnCompact,
  formatNumber,
  formatTime,
  formatUsd,
  isoDateOffset,
  todayIso,
} from './format'

describe('formatNgnCompact', () => {
  it('collapses millions to ₦X.XXM so large figures fit a stat card', () => {
    expect(formatNgnCompact(28_658_693.94)).toBe('₦28.66M')
    expect(formatNgnCompact('1000000')).toBe('₦1.00M')
  })

  it('collapses large thousands to ₦XXXk', () => {
    expect(formatNgnCompact(250_000)).toBe('₦250k')
    expect(formatNgnCompact(10_000)).toBe('₦10k')
  })

  it('renders small amounts in full', () => {
    expect(formatNgnCompact(9_999)).toBe('₦9,999')
    expect(formatNgnCompact(500)).toBe('₦500')
  })

  it('handles zero, null, undefined and non-finite input as ₦0', () => {
    expect(formatNgnCompact(0)).toBe('₦0')
    expect(formatNgnCompact(null)).toBe('₦0')
    expect(formatNgnCompact(undefined)).toBe('₦0')
    expect(formatNgnCompact('not a number')).toBe('₦0')
  })

  it('keeps the sign for negative amounts (overpaid/credit)', () => {
    expect(formatNgnCompact(-2_500_000)).toBe('-₦2.50M')
  })
})

describe('formatNgn', () => {
  it('writes a whole amount without kobo and with grouping', () => {
    expect(formatNgn(174375)).toBe('₦174,375')
    expect(formatNgn('174375.00')).toBe('₦174,375')
    expect(formatNgn('0')).toBe('₦0')
  })

  it('writes kobo with two digits, never one', () => {
    expect(formatNgn('174375.5')).toBe('₦174,375.50')
    expect(formatNgn(0.05)).toBe('₦0.05')
    expect(formatNgn('1234.56')).toBe('₦1,234.56')
  })

  it('does not invent kobo from float noise', () => {
    expect(formatNgn(0.1 + 0.2)).toBe('₦0.30')
    expect(formatNgn(100.00000001)).toBe('₦100')
  })

  it('keeps the sign', () => {
    expect(formatNgn(-1200)).toBe('-₦1,200')
    expect(formatNgn('-12.5')).toBe('-₦12.50')
  })

  it('shows a dash, not NaN, when the amount is missing or unreadable', () => {
    expect(formatNgn(null)).toBe('—')
    expect(formatNgn(undefined)).toBe('—')
    expect(formatNgn('')).toBe('—')
    expect(formatNgn('abc')).toBe('—')
  })

  it('does not follow the browser locale', () => {
    // A German or Indian locale would group as 174.375 or 1,74,375.
    const original = navigator.language
    Object.defineProperty(navigator, 'language', { value: 'de-DE', configurable: true })
    expect(formatNgn(174375.5)).toBe('₦174,375.50')
    Object.defineProperty(navigator, 'language', { value: original, configurable: true })
  })
})

describe('formatUsd, formatCbm, formatNumber, formatCount', () => {
  it('formatUsd always shows cents', () => {
    expect(formatUsd('112.5')).toBe('$112.50')
    expect(formatUsd(1500)).toBe('$1,500.00')
    expect(formatUsd(-3)).toBe('-$3.00')
    expect(formatUsd(null)).toBe('—')
  })

  it('formatCbm shows three decimals', () => {
    expect(formatCbm('2.5')).toBe('2.500')
    expect(formatCbm(41.2)).toBe('41.200')
    expect(formatCbm(undefined)).toBe('—')
  })

  it('formatNumber groups and trims to the decimals asked for', () => {
    expect(formatNumber(1550)).toBe('1,550')
    expect(formatNumber('1550.456')).toBe('1,550.46')
    expect(formatNumber(1550.456, 0)).toBe('1,550')
    expect(formatNumber(12.5, 3)).toBe('12.5')
  })

  it('formatCount is a grouped whole number', () => {
    expect(formatCount(12480)).toBe('12,480')
    expect(formatCount('7')).toBe('7')
    expect(formatCount(null)).toBe('—')
  })
})

describe('formatDate (Lagos time)', () => {
  it('writes a day-month-year date', () => {
    expect(formatDate('2026-11-10T10:00:00Z')).toBe('10 Nov 2026')
    expect(formatDate('2026-11-10T10:00:00Z', 'short')).toBe('10 Nov')
    expect(formatDate('2026-11-10T10:00:00Z', 'long')).toBe('10 November 2026')
  })

  it('converts a timestamp to its Lagos date (an evening UTC event is the next day in Lagos)', () => {
    expect(formatDate('2026-11-10T23:30:00Z')).toBe('11 Nov 2026')
    expect(formatDate('2026-11-10T22:59:00Z')).toBe('10 Nov 2026')
  })

  it('takes a plain calendar date as written, in every zone', () => {
    expect(formatDate('2026-12-01')).toBe('1 Dec 2026')
    expect(formatDate('2026-01-01')).toBe('1 Jan 2026')
    expect(formatDate('2026-12-31', 'short')).toBe('31 Dec')
  })

  it('shows a dash for a missing or unreadable date', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('')).toBe('—')
    expect(formatDate('not a date')).toBe('—')
  })

  it('accepts a Date', () => {
    expect(formatDate(new Date('2026-03-05T08:00:00Z'))).toBe('5 Mar 2026')
  })
})

describe('formatDateTime and formatTime (Lagos time)', () => {
  it('names the zone', () => {
    expect(formatDateTime('2026-11-10T10:04:00Z')).toBe('10 Nov 2026, 11:04 WAT')
    expect(formatTime('2026-11-10T10:04:00Z')).toBe('11:04 WAT')
  })

  it('uses a 24-hour clock, with midnight as 00:xx', () => {
    expect(formatDateTime('2026-11-10T23:05:00Z')).toBe('11 Nov 2026, 00:05 WAT')
    expect(formatTime('2026-11-10T14:30:00Z')).toBe('15:30 WAT')
  })

  it('can leave the year out for a dense table of recent events', () => {
    expect(formatDateTime('2026-11-10T10:04:00Z', { year: false })).toBe('10 Nov, 11:04 WAT')
  })

  it('shows a plain date as a date, since it has no time', () => {
    expect(formatDateTime('2026-12-01')).toBe('1 Dec 2026')
  })

  it('shows a dash for a missing or unreadable moment', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('x')).toBe('—')
    expect(formatTime(undefined)).toBe('—')
  })
})

describe('todayIso and isoDateOffset (Lagos dates)', () => {
  it('is the Lagos date, which is ahead of UTC for the last hour of the UTC day', () => {
    expect(todayIso(new Date('2026-11-10T22:30:00Z'))).toBe('2026-11-10')
    expect(todayIso(new Date('2026-11-10T23:30:00Z'))).toBe('2026-11-11') // 00:30 on the 11th in Lagos
  })

  it('counts days from the Lagos date', () => {
    const now = new Date('2026-11-10T23:30:00Z') // 11 Nov in Lagos
    expect(isoDateOffset(0, now)).toBe('2026-11-11')
    expect(isoDateOffset(-30, now)).toBe('2026-10-12')
    expect(isoDateOffset(7, now)).toBe('2026-11-18')
  })

  it('crosses month and year ends', () => {
    expect(isoDateOffset(1, new Date('2026-12-31T12:00:00Z'))).toBe('2027-01-01')
    expect(isoDateOffset(-1, new Date('2026-03-01T12:00:00Z'))).toBe('2026-02-28')
  })
})

// Drift guard for FE-03. The point of the helpers is that no page formats for itself: a bare toLocaleString() follows the
// viewer's browser, and slicing an ISO string shows a raw UTC date. One of either brings the problem back.
const SOURCES = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe('nothing formats numbers or dates by hand (FE-03)', () => {
  // format.ts is the one place that may do this (the glob names it relative to this folder).
  const files = Object.entries(SOURCES).filter(([path]) => !path.includes('.test.') && path !== './format.ts')
  const offenders = (pattern: RegExp): string[] =>
    files.flatMap(([path, text]) =>
      text.split('\n').flatMap((line, index) => (pattern.test(line) && !line.trim().startsWith('//') && !line.trim().startsWith('*') ? [`${path.replace('..', 'src')}:${index + 1}`] : [])),
    )

  it('no toLocaleString, toLocaleDateString or toLocaleTimeString', () => {
    expect(offenders(/\.toLocale(Date|Time)?String\(/)).toEqual([])
  })

  it('no slicing an ISO string to get a date', () => {
    expect(offenders(/\.slice\(0, ?10\)/)).toEqual([])
  })
})

