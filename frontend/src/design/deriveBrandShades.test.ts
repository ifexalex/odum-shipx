import { describe, expect, it } from 'vitest'
import {
  contrastRatio,
  deriveBrandShades,
  deriveTenantPalette,
  isValidHexColor,
} from './deriveBrandShades'

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
      return ((int >> 16) & 255) + ((int >> 8) & 255) + (int & 255)
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
      return ((int >> 16) & 255) + ((int >> 8) & 255) + (int & 255)
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

    expect(luminance(dark.soft)).toBeLessThan(luminance(base))
    expect(luminance(dark.tint)).toBeLessThan(luminance(base))
    expect(luminance(dark.soft)).toBeLessThan(luminance(light.soft))
    expect(luminance(dark.tint)).toBeLessThan(luminance(light.tint))
    expect(dark.base).toBe(light.base)
    expect(dark.deep).toBe(light.deep)
    expect(dark.strong).toBe(light.strong)
  })
})

describe('deriveTenantPalette — WCAG AA contrast sweep', () => {
  const SAMPLE_COLORS = [
    '#1c7922', // ShipX green
    '#1a5276', // Royal navy
    '#0a6ed1', // Bright azure
    '#7c3aed', // Violet
    '#9b1c1c', // Burgundy
    '#d97706', // Amber
    '#facc15', // Bright yellow (must darken base for white text)
    '#93c5fd', // Pastel sky blue (must darken base for white text)
    '#0f766e', // Teal
    '#111111', // Near black
    '#6b7280', // Neutral grey
    '#f5f5f5', // Near white (extreme edge case)
  ]

  it.each(SAMPLE_COLORS)(
    'guarantees WCAG AA (>= 4.5:1) across every token pair in light & dark modes for %s',
    (hex) => {
      for (const scheme of ['light', 'dark'] as const) {
        const p = deriveTenantPalette(hex, scheme)
        for (const value of Object.values(p)) {
          expect(isValidHexColor(value)).toBe(true)
        }

        // Filled buttons & chrome against white (--color-on-brand)
        expect(contrastRatio(p.base, '#ffffff')).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.strong, '#ffffff')).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.deep, '#ffffff')).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.accent, '#ffffff')).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.accentDeep, '#ffffff')).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.accentHover, '#ffffff')).toBeGreaterThanOrEqual(4.5)

        // Branded dark sidebar holds >= 10:1 against white so muted-white labels stay legible
        expect(contrastRatio(p.sidebar, '#ffffff')).toBeGreaterThanOrEqual(10.0)

        // Text tokens against page surfaces
        const surface = scheme === 'dark' ? '#1f2621' : '#f9fafb'
        expect(contrastRatio(p.text, surface)).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.accentText, surface)).toBeGreaterThanOrEqual(4.5)

        // On-soft badge/chip text against soft fills
        expect(contrastRatio(p.onSoft, p.soft)).toBeGreaterThanOrEqual(4.5)
        expect(contrastRatio(p.accentOnSoft, p.accentSoft)).toBeGreaterThanOrEqual(4.5)
      }
    },
  )
})
