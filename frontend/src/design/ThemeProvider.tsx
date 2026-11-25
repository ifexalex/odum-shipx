import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { useColorScheme } from './colorScheme'
import { deriveTenantPalette, isValidHexColor } from './deriveBrandShades'
import { ThemePortalContext } from './themePortal'

export interface ThemeProviderProps {
  /** Maps from `tenant.branding_config.primary_color` — pass `null`/`undefined` for the canonical palette. */
  primaryColor?: string | null
  /** Layout passthrough for the scoping div (e.g. `{height: '100%'}` inside the app shell's height chain). */
  style?: CSSProperties
  children: ReactNode
}

const TENANT_VARS = [
  '--color-primary',
  '--color-primary-deep',
  '--color-primary-strong',
  '--color-primary-bright',
  '--color-primary-soft',
  '--color-primary-tint',
  '--color-primary-text',
  '--color-primary-on-soft',
  '--color-forest-dark',
  '--color-accent',
  '--color-accent-deep',
  '--color-accent-hover',
  '--color-accent-soft',
  '--color-accent-on-soft',
  '--color-accent-text',
] as const

// Applies a tenant's primary_color as a scoped CSS custom property override.
// Scoped to this element (not :root) so the login screen, Platform Admin
// shell, and any concurrently-rendered canonical-brand surface are
// unaffected. Status colors (success/warning/error/info) are never set here.
export function ThemeProvider({ primaryColor, style, children }: ThemeProviderProps): JSX.Element {
  const [scopeEl, setScopeEl] = useState<HTMLDivElement | null>(null)
  // Re-derive when the light/dark scheme flips — soft/tint/text/on-soft shades
  // differ by scheme so contrast holds in both light and dark modes.
  const { resolved } = useColorScheme()

  useEffect(() => {
    const el = scopeEl
    if (!el) return

    if (primaryColor && isValidHexColor(primaryColor)) {
      const p = deriveTenantPalette(primaryColor, resolved)
      el.style.setProperty('--color-primary', p.base)
      el.style.setProperty('--color-primary-deep', p.deep)
      el.style.setProperty('--color-primary-strong', p.strong)
      el.style.setProperty('--color-primary-bright', p.bright)
      el.style.setProperty('--color-primary-soft', p.soft)
      el.style.setProperty('--color-primary-tint', p.tint)
      el.style.setProperty('--color-primary-text', p.text)
      el.style.setProperty('--color-primary-on-soft', p.onSoft)
      el.style.setProperty('--color-forest-dark', p.sidebar)
      el.style.setProperty('--color-accent', p.accent)
      el.style.setProperty('--color-accent-deep', p.accentDeep)
      el.style.setProperty('--color-accent-hover', p.accentHover)
      el.style.setProperty('--color-accent-soft', p.accentSoft)
      el.style.setProperty('--color-accent-on-soft', p.accentOnSoft)
      el.style.setProperty('--color-accent-text', p.accentText)
    } else {
      for (const cssVar of TENANT_VARS) el.style.removeProperty(cssVar)
    }
  }, [scopeEl, primaryColor, resolved])

  return (
    <div ref={setScopeEl} data-tenant-theme style={style}>
      <ThemePortalContext.Provider value={scopeEl}>{children}</ThemePortalContext.Provider>
    </div>
  )
}
