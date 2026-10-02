// Derives the deep/strong/soft/tint shades a tenant's single primary_color
// needs to drive ThemeProvider, so tenants only ever supply one hex value
// instead of hand-picking 5 coordinated shades (see 02_design_tokens_and_theming.md).

export interface BrandShades {
  base: string
  deep: string
  strong: string
  soft: string
  tint: string
}

interface Hsl {
  h: number
  s: number
  l: number
}

const HEX_PATTERN = /^#([0-9a-f]{6})$/i

export function isValidHexColor(value: string): boolean {
  return HEX_PATTERN.test(value)
}

function hexToHsl(hex: string): Hsl {
  const match = HEX_PATTERN.exec(hex)
  if (!match) throw new Error(`Invalid hex color: ${hex}`)
  const int = parseInt(match[1]!, 16)
  const r = ((int >> 16) & 255) / 255
  const g = ((int >> 8) & 255) / 255
  const b = (int & 255) / 255

  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  const delta = max - min

  if (delta === 0) return { h: 0, s: 0, l }

  const s = delta / (1 - Math.abs(2 * l - 1))
  let h: number
  switch (max) {
    case r:
      h = ((g - b) / delta) % 6
      break
    case g:
      h = (b - r) / delta + 2
      break
    default:
      h = (r - g) / delta + 4
  }
  h *= 60
  if (h < 0) h += 360

  return { h, s, l }
}

function hslToHex({ h, s, l }: Hsl): string {
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2

  let r = 0
  let g = 0
  let b = 0
  if (h < 60) [r, g, b] = [c, x, 0]
  else if (h < 120) [r, g, b] = [x, c, 0]
  else if (h < 180) [r, g, b] = [0, c, x]
  else if (h < 240) [r, g, b] = [0, x, c]
  else if (h < 300) [r, g, b] = [x, 0, c]
  else [r, g, b] = [c, 0, x]

  const toHex = (v: number): string =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, '0')

  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value))

export type ColorScheme = 'light' | 'dark'

export function deriveBrandShades(baseHex: string, scheme: ColorScheme = 'light'): BrandShades {
  if (!isValidHexColor(baseHex)) throw new Error(`Invalid hex color: ${baseHex}`)
  const hsl = hexToHsl(baseHex)

  // `soft` (selected-row bg) and `tint` (hover-row bg) are near-white in light
  // mode. In dark mode that reads as a blinding white band on a dark table, so
  // they become dark, lightly-saturated versions of the brand hue instead.
  // base/deep/strong stay as-is — they back solid buttons with white text,
  // which works in both schemes.
  const soft =
    scheme === 'dark'
      ? hslToHex({ h: hsl.h, s: clamp01(hsl.s * 0.5), l: 0.17 })
      : hslToHex({ ...hsl, s: clamp01(hsl.s * 0.4), l: clamp01(hsl.l + 0.55) })
  const tint =
    scheme === 'dark'
      ? hslToHex({ h: hsl.h, s: clamp01(hsl.s * 0.4), l: 0.11 })
      : hslToHex({ ...hsl, s: clamp01(hsl.s * 0.25), l: clamp01(hsl.l + 0.7) })

  return {
    base: baseHex,
    deep: hslToHex({ ...hsl, l: clamp01(hsl.l - 0.2) }),
    strong: hslToHex({ ...hsl, l: clamp01(hsl.l - 0.1) }),
    soft,
    tint,
  }
}
