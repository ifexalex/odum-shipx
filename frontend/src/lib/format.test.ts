import { describe, expect, it } from 'vitest'
import { formatNgnCompact } from './format'

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
