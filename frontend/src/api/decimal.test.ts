import { describe, expect, it } from 'vitest'
import { formatCbm } from './decimal'

describe('formatCbm', () => {
  it('formats a string-typed DECIMAL field to 3dp', () => {
    expect(formatCbm('0.03')).toBe('0.030')
    expect(formatCbm('8.420000')).toBe('8.420')
  })

  it('returns an em dash for null or undefined', () => {
    expect(formatCbm(null)).toBe('—')
    expect(formatCbm(undefined)).toBe('—')
  })

  it('also accepts a number, for callers computing client-side previews', () => {
    expect(formatCbm(0.03)).toBe('0.030')
  })
})
