import { describe, expect, it } from 'vitest'
import { deriveBrandShades, isValidHexColor } from './deriveBrandShades'

describe('isValidHexColor', () => {
  it('accepts 6-digit hex with or without uppercase', () => {
    expect(isValidHexColor('#1a5276')).toBe(true)
    expect(isValidHexColor('#1A5276')).toBe(true)
  })

  it('rejects malformed input', () => {
    expect(isValidHexColor('1a5276')).toBe(false)
    expect(isValidHexColor('#1a527')).toBe(false)
    expect(isValidHexColor('blue')).toBe(false)
    expect(isValidHexColor('')).toBe(false)
  })
})

describe('deriveBrandShades', () => {
  it('returns valid hex codes for every shade', () => {
    const shades = deriveBrandShades('#1a5276')
    for (const value of Object.values(shades)) {
      expect(isValidHexColor(value)).toBe(true)
    }
  })

  it('keeps base unchanged and darkens deep/strong relative to base', () => {
    const base = '#1a5276'
    const shades = deriveBrandShades(base)
    expect(shades.base).toBe(base)

    const luminance = (hex: string): number => {
      const int = parseInt(hex.slice(1), 16)
      return (int >> 16 & 255) + (int >> 8 & 255) + (int & 255)
    }

    expect(luminance(shades.deep)).toBeLessThan(luminance(base))
    expect(luminance(shades.strong)).toBeLessThan(luminance(base))
    expect(luminance(shades.deep)).toBeLessThan(luminance(shades.strong))
  })

  it('lightens soft/tint relative to base, with tint lighter than soft', () => {
    const base = '#1a5276'
    const shades = deriveBrandShades(base)

    const luminance = (hex: string): number => {
      const int = parseInt(hex.slice(1), 16)
      return (int >> 16 & 255) + (int >> 8 & 255) + (int & 255)
    }

    expect(luminance(shades.soft)).toBeGreaterThan(luminance(base))
    expect(luminance(shades.tint)).toBeGreaterThan(luminance(shades.soft))
  })

  it('throws on an invalid hex color', () => {
    expect(() => deriveBrandShades('not-a-color')).toThrow()
  })

  it('derives DARK soft/tint in dark mode so row highlights are not near-white', () => {
    const base = '#1a5276'
    const luminance = (hex: string): number => {
      const int = parseInt(hex.slice(1), 16)
      return ((int >> 16) & 255) + ((int >> 8) & 255) + (int & 255)
    }
    const dark = deriveBrandShades(base, 'dark')
    const light = deriveBrandShades(base, 'light')

    // Dark soft/tint are much darker than base and far darker than the light
    // variants (which are near-white) — no blinding band on a dark table.
    expect(luminance(dark.soft)).toBeLessThan(luminance(base))
    expect(luminance(dark.tint)).toBeLessThan(luminance(base))
    expect(luminance(dark.soft)).toBeLessThan(luminance(light.soft))
    expect(luminance(dark.tint)).toBeLessThan(luminance(light.tint))
    // base/deep/strong are scheme-independent.
    expect(dark.base).toBe(light.base)
    expect(dark.deep).toBe(light.deep)
    expect(dark.strong).toBe(light.strong)
  })
})
