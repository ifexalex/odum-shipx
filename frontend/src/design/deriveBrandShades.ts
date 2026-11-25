/**
 * Perceptual tenant palette generator (OKLCH + WCAG 2.1 contrast guard).
 *
 * Tenants pick a single brand hex (`tenant.branding_config.primary_color`),
 * and we derive a full coordinated palette for both light and dark modes:
 *   - Primary scale (base, strong, deep, bright, soft, tint, text, onSoft)
 *   - Branded sidebar chrome (--color-forest-dark)
 *   - Harmonious split-complementary accent scale (avoiding semantic error red)
 *
 * Every filled surface guarantees >= 4.5:1 against white (--color-on-brand
 * stays #ffffff across buttons and dark chrome), and every text/on-soft pair
 * guarantees >= 4.5:1 on both light (#ffffff) and dark (#181d19 / #1f2621)
 * surfaces. Status tokens (success/warning/error/info) are never touched.
 */

export type ColorScheme = 'light' | 'dark'

export interface BrandShades {
  base: string
  deep: string
  strong: string
  soft: string
  tint: string
}

export interface TenantPalette extends BrandShades {
  bright: string
  text: string
  onSoft: string
  sidebar: string
  accent: string
  accentDeep: string
  accentHover: string
  accentSoft: string
  accentOnSoft: string
  accentText: string
}

interface Rgb {
  r: number
  g: number
  b: number
}

interface Oklch {
  L: number
  C: number
  h: number
}

const HEX_PATTERN = /^#([0-9a-f]{6})$/i

const WHITE = '#ffffff'
const LIGHT_SURFACE_MUTED = '#f9fafb'
const DARK_SURFACE_MUTED = '#1f2621'

export function isValidHexColor(value: string): boolean {
  return HEX_PATTERN.test(value)
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function hexToRgb(hex: string): Rgb {
  const match = HEX_PATTERN.exec(hex)
  if (!match) throw new Error(`Invalid hex color: ${hex}`)
  const int = parseInt(match[1]!, 16)
  return {
    r: ((int >> 16) & 255) / 255,
    g: ((int >> 8) & 255) / 255,
    b: (int & 255) / 255,
  }
}

function rgbToHex({ r, g, b }: Rgb): string {
  const toByte = (v: number): string =>
    Math.round(clamp01(v) * 255)
      .toString(16)
      .padStart(2, '0')
  return `#${toByte(r)}${toByte(g)}${toByte(b)}`
}

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function linearToSrgb(c: number): number {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
}

/** WCAG 2.1 relative luminance (0 = black, 1 = white). */
export function relativeLuminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex)
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b)
}

/** WCAG 2.1 contrast ratio between two hex colours (1..21). */
export function contrastRatio(hexA: string, hexB: string): number {
  const l1 = relativeLuminance(hexA)
  const l2 = relativeLuminance(hexB)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}

/** Convert sRGB hex to OKLCH (Björn Ottosson's exact OKLab matrices). */
function hexToOklch(hex: string): Oklch {
  const { r, g, b } = hexToRgb(hex)
  const lr = srgbToLinear(r)
  const lg = srgbToLinear(g)
  const lb = srgbToLinear(b)

  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)

  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const bVal = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s

  const C = Math.hypot(a, bVal)
  let h = (Math.atan2(bVal, a) * 180) / Math.PI
  if (h < 0) h += 360

  return { L, C, h }
}

function oklchToLinearRgb({ L, C, h }: Oklch): Rgb {
  const hRad = (h * Math.PI) / 180
  const a = C * Math.cos(hRad)
  const bVal = C * Math.sin(hRad)

  const l_ = L + 0.3963377774 * a + 0.2158037573 * bVal
  const m_ = L - 0.1055613458 * a - 0.0638541728 * bVal
  const s_ = L - 0.0894841775 * a - 1.291485548 * bVal

  const l = l_ * l_ * l_
  const m = m_ * m_ * m_
  const s = s_ * s_ * s_

  return {
    r: +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    g: -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    b: -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  }
}

function inSrgbGamut({ r, g, b }: Rgb): boolean {
  const eps = 1e-4
  return r >= -eps && r <= 1 + eps && g >= -eps && g <= 1 + eps && b >= -eps && b <= 1 + eps
}

/** Convert OKLCH to in-gamut sRGB hex by reducing chroma while preserving L and hue. */
function oklchToHex({ L, C, h }: Oklch): string {
  const clampedL = clamp01(L)
  let lin = oklchToLinearRgb({ L: clampedL, C, h })
  if (!inSrgbGamut(lin)) {
    let lo = 0
    let hi = C
    for (let i = 0; i < 16; i++) {
      const mid = (lo + hi) / 2
      if (inSrgbGamut(oklchToLinearRgb({ L: clampedL, C: mid, h }))) {
        lo = mid
      } else {
        hi = mid
      }
    }
    lin = oklchToLinearRgb({ L: clampedL, C: lo, h })
  }
  return rgbToHex({
    r: linearToSrgb(clamp01(lin.r)),
    g: linearToSrgb(clamp01(lin.g)),
    b: linearToSrgb(clamp01(lin.b)),
  })
}

/** Darken an OKLCH colour until it reaches `minRatio` contrast against a light background. */
function ensureContrastDarker(color: Oklch, bgHex: string, minRatio: number): string {
  const initial = oklchToHex(color)
  if (contrastRatio(initial, bgHex) >= minRatio) return initial
  let lo = 0.05
  let hi = clamp01(color.L)
  let best = oklchToHex({ ...color, L: lo })
  for (let i = 0; i < 16; i++) {
    const mid = (lo + hi) / 2
    const candidate = oklchToHex({ ...color, L: mid })
    if (contrastRatio(candidate, bgHex) >= minRatio) {
      best = candidate
      lo = mid
    } else {
      hi = mid
    }
  }
  return best
}

/** Lighten an OKLCH colour until it reaches `minRatio` contrast against a dark background. */
function ensureContrastLighter(color: Oklch, bgHex: string, minRatio: number): string {
  const initial = oklchToHex(color)
  if (contrastRatio(initial, bgHex) >= minRatio) return initial
  let lo = clamp01(color.L)
  let hi = 0.96
  let best = oklchToHex({ ...color, L: hi })
  for (let i = 0; i < 16; i++) {
    const mid = (lo + hi) / 2
    const candidate = oklchToHex({ ...color, L: mid })
    if (contrastRatio(candidate, bgHex) >= minRatio) {
      best = candidate
      hi = mid
    } else {
      lo = mid
    }
  }
  return best
}

/**
 * Pick a harmonious accent hue from the brand hue using a split-complementary
 * offset (+150°), nudged away from semantic error red (0°–32°, 340°–360°) so
 * primary accent CTAs never read as destructive danger buttons.
 */
function pickAccentHue(brandHue: number, isAchromatic: boolean): number {
  if (isAchromatic) return 48 // warm amber-copper accent for neutral/grey brands
  let acc = (brandHue + 150) % 360
  if (acc < 35 || acc > 340) {
    // Shift to warm amber-copper (48°) unless the brand itself is already warm amber/orange
    const distToAmber = Math.min(Math.abs(brandHue - 48), 360 - Math.abs(brandHue - 48))
    acc = distToAmber < 40 ? 210 : 48
  }
  return acc
}

/**
 * Derive a full, WCAG-AA-verified tenant palette from a single brand hex.
 *
 * When `baseHex` already achieves >= 4.5:1 against white, `base` is preserved
 * verbatim so dark/medium brand colours stay exact. Bright colours (e.g. gold
 * or pastel) are darkened just enough at the same hue to keep white button
 * text crisp.
 */
export function deriveTenantPalette(baseHex: string, scheme: ColorScheme = 'light'): TenantPalette {
  if (!isValidHexColor(baseHex)) throw new Error(`Invalid hex color: ${baseHex}`)
  const raw = hexToOklch(baseHex)
  const isAchromatic = raw.C < 0.02

  // Primary fill (buttons, active chrome) — guaranteed >= 4.5:1 against white.
  const base = contrastRatio(baseHex, WHITE) >= 4.5 ? baseHex : ensureContrastDarker(raw, WHITE, 4.55)
  const baseOklch = hexToOklch(base)

  const strong = oklchToHex({ ...baseOklch, L: Math.max(0.14, baseOklch.L - 0.07) })
  const deep = oklchToHex({ ...baseOklch, L: Math.max(0.09, baseOklch.L - 0.14) })
  const bright = oklchToHex({
    L: 0.72,
    C: isAchromatic ? 0 : Math.min(0.22, Math.max(raw.C, 0.14)),
    h: raw.h,
  })

  // Soft (selected-row / badge bg) and tint (hover-row bg) flip by scheme.
  const soft =
    scheme === 'dark'
      ? oklchToHex({ L: 0.27, C: isAchromatic ? 0 : Math.min(raw.C * 0.45, 0.06), h: raw.h })
      : oklchToHex({ L: 0.92, C: isAchromatic ? 0 : Math.min(raw.C * 0.45, 0.065), h: raw.h })
  const tint =
    scheme === 'dark'
      ? oklchToHex({ L: 0.2, C: isAchromatic ? 0 : Math.min(raw.C * 0.3, 0.035), h: raw.h })
      : oklchToHex({ L: 0.965, C: isAchromatic ? 0 : Math.min(raw.C * 0.25, 0.03), h: raw.h })

  const text =
    scheme === 'dark'
      ? ensureContrastLighter(
          { L: 0.76, C: isAchromatic ? 0 : Math.min(Math.max(raw.C, 0.12), 0.18), h: raw.h },
          DARK_SURFACE_MUTED,
          4.6,
        )
      : ensureContrastDarker(baseOklch, LIGHT_SURFACE_MUTED, 4.6)

  const onSoft =
    scheme === 'dark'
      ? ensureContrastLighter(
          { L: 0.78, C: isAchromatic ? 0 : Math.min(Math.max(raw.C, 0.12), 0.18), h: raw.h },
          soft,
          4.6,
        )
      : ensureContrastDarker(
          { L: Math.min(baseOklch.L, 0.42), C: isAchromatic ? 0 : Math.min(raw.C, 0.14), h: raw.h },
          soft,
          4.6,
        )

  // Branded dark sidebar chrome (--color-forest-dark) — ultra-dark tint of the
  // tenant's own hue so white + muted-white sidebar labels hold >= 10:1 / 4.5:1.
  const sidebar = ensureContrastDarker(
    { L: 0.22, C: isAchromatic ? 0 : Math.min(raw.C * 0.35, 0.045), h: raw.h },
    WHITE,
    11.0,
  )

  // Harmonious split-complementary accent scale.
  const accHue = pickAccentHue(raw.h, isAchromatic)
  const accChroma = isAchromatic ? 0.12 : Math.min(0.16, Math.max(0.1, raw.C * 0.85))
  const accent = ensureContrastDarker({ L: 0.5, C: accChroma, h: accHue }, WHITE, 4.6)
  const accentOklch = hexToOklch(accent)
  const accentDeep = oklchToHex({ ...accentOklch, L: Math.max(0.16, accentOklch.L - 0.08) })
  const accentHover = ensureContrastDarker(
    { ...accentOklch, L: Math.min(0.62, accentOklch.L + 0.05) },
    WHITE,
    4.55,
  )
  const accentSoft =
    scheme === 'dark'
      ? oklchToHex({ L: 0.27, C: Math.min(accChroma * 0.5, 0.06), h: accHue })
      : oklchToHex({ L: 0.91, C: Math.min(accChroma * 0.55, 0.07), h: accHue })
  const accentOnSoft =
    scheme === 'dark'
      ? ensureContrastLighter({ L: 0.78, C: Math.min(accChroma, 0.15), h: accHue }, accentSoft, 4.6)
      : ensureContrastDarker({ L: 0.4, C: Math.min(accChroma, 0.14), h: accHue }, accentSoft, 4.6)
  const accentText =
    scheme === 'dark'
      ? ensureContrastLighter(
          { L: 0.76, C: Math.min(accChroma, 0.15), h: accHue },
          DARK_SURFACE_MUTED,
          4.6,
        )
      : ensureContrastDarker(accentOklch, LIGHT_SURFACE_MUTED, 4.6)

  return {
    base,
    deep,
    strong,
    bright,
    soft,
    tint,
    text,
    onSoft,
    sidebar,
    accent,
    accentDeep,
    accentHover,
    accentSoft,
    accentOnSoft,
    accentText,
  }
}

/** Backwards-compatible alias returning the 5 core primary shades. */
export function deriveBrandShades(baseHex: string, scheme: ColorScheme = 'light'): BrandShades {
  const { base, deep, strong, soft, tint } = deriveTenantPalette(baseHex, scheme)
  return { base, deep, strong, soft, tint }
}
