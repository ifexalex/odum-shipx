import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { useColorScheme } from './colorScheme'
import { deriveBrandShades, isValidHexColor } from './deriveBrandShades'

export interface ThemeProviderProps {
  /** Maps from `tenant.branding_config.primary_color` — pass `null`/`undefined` for the canonical palette. */
  primaryColor?: string | null
  /** Layout passthrough for the scoping div (e.g. `{height: '100%'}` inside the app shell's height chain). */
  style?: CSSProperties
  children: ReactNode
}

const PRIMARY_VARS = [
  '--color-primary',
  '--color-primary-deep',
  '--color-primary-strong',
  '--color-primary-soft',
  '--color-primary-tint',
] as const

// Applies a tenant's primary_color as a scoped CSS custom property override.
// Scoped to this element (not :root) so the login screen, Platform Admin
// shell, and any concurrently-rendered canonical-brand surface are
// unaffected. The component only accepts primaryColor — status colors
// (success/warning/error/info) are not a parameter here, so there is no code
// path that can override them.
export function ThemeProvider({ primaryColor, style, children }: ThemeProviderProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  // Re-derive when the light/dark scheme flips — the soft/tint (row bg) shades
  // differ by scheme, so a derived light tint must not leak into dark mode.
  const { resolved } = useColorScheme()

  useEffect(() => {
    const el = ref.current
    if (!el) return

    if (primaryColor && isValidHexColor(primaryColor)) {
      const shades = deriveBrandShades(primaryColor, resolved)
      el.style.setProperty('--color-primary', shades.base)
      el.style.setProperty('--color-primary-deep', shades.deep)
      el.style.setProperty('--color-primary-strong', shades.strong)
      el.style.setProperty('--color-primary-soft', shades.soft)
      el.style.setProperty('--color-primary-tint', shades.tint)
    } else {
      for (const cssVar of PRIMARY_VARS) el.style.removeProperty(cssVar)
    }
  }, [primaryColor, resolved])

  return (
    <div ref={ref} data-tenant-theme style={style}>
      {children}
    </div>
  )
}
