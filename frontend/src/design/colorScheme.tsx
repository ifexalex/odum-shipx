import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type JSX,
  type ReactNode,
} from 'react'

/**
 * Light/dark theming.
 *
 * The user's *preference* is one of 'light' | 'dark' | 'system'. 'system'
 * follows the OS via `prefers-color-scheme`. Whatever it resolves to is
 * written to `<html data-theme="light|dark">`, which flips the CSS custom
 * properties in tokens.css. Resolving 'system' here (not in a CSS media
 * query) keeps tokens.css to a single dark block.
 *
 * A matching pre-paint script in index.html applies the same attribute
 * before React mounts, so there is no light-mode flash on first load; this
 * provider then keeps it in sync and re-resolves 'system' when the OS flips.
 */
export type ColorSchemePreference = 'light' | 'dark' | 'system'
export type ResolvedColorScheme = 'light' | 'dark'

const STORAGE_KEY = 'shipx-color-scheme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readStoredPreference(): ColorSchemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Private mode / blocked storage — fall through to the default.
  }
  return 'system'
}

function systemScheme(): ResolvedColorScheme {
  try {
    return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

function resolve(preference: ColorSchemePreference): ResolvedColorScheme {
  return preference === 'system' ? systemScheme() : preference
}

function apply(resolved: ResolvedColorScheme): void {
  try {
    document.documentElement.dataset.theme = resolved
  } catch {
    // SSR / no document — nothing to apply.
  }
}

export interface ColorSchemeValue {
  /** What the user chose. */
  preference: ColorSchemePreference
  /** The scheme actually in effect (system resolved to light/dark). */
  resolved: ResolvedColorScheme
  setPreference: (preference: ColorSchemePreference) => void
  /** Cycle system → light → dark → system, for a single toggle control. */
  cycle: () => void
}

// Default value is a functional standalone controller (reads/writes storage +
// the <html data-theme> attribute directly) so a <ThemeToggle> still works
// when rendered without a provider — e.g. a component test that mounts a shell
// in isolation. The provider adds React reactivity (re-rendering the icon on
// change); the standalone default just lacks that, which is harmless.
function standaloneCycle(): void {
  const current = readStoredPreference()
  const next: ColorSchemePreference =
    current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system'
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // Non-fatal.
  }
  apply(resolve(next))
}

function standaloneSet(next: ColorSchemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // Non-fatal.
  }
  apply(resolve(next))
}

function standaloneDefault(): ColorSchemeValue {
  const preference = readStoredPreference()
  return {
    preference,
    resolved: resolve(preference),
    setPreference: standaloneSet,
    cycle: standaloneCycle,
  }
}

const ColorSchemeContext = createContext<ColorSchemeValue | null>(null)

export function ColorSchemeProvider({ children }: { children: ReactNode }): JSX.Element {
  const [preference, setPreferenceState] = useState<ColorSchemePreference>(readStoredPreference)
  const [resolved, setResolved] = useState<ResolvedColorScheme>(() => resolve(readStoredPreference()))

  // Apply on every preference change, and when 'system' flips at the OS level.
  useEffect(() => {
    const next = resolve(preference)
    setResolved(next)
    apply(next)

    if (preference !== 'system') return
    const mq = window.matchMedia(DARK_QUERY)
    const onChange = (): void => {
      const sys = systemScheme()
      setResolved(sys)
      apply(sys)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [preference])

  const setPreference = useCallback((next: ColorSchemePreference) => {
    setPreferenceState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Non-fatal — the choice just won't survive a reload.
    }
  }, [])

  const cycle = useCallback(() => {
    setPreferenceState((prev) => {
      const next: ColorSchemePreference =
        prev === 'system' ? 'light' : prev === 'light' ? 'dark' : 'system'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        // Non-fatal.
      }
      return next
    })
  }, [])

  const value = useMemo<ColorSchemeValue>(
    () => ({ preference, resolved, setPreference, cycle }),
    [preference, resolved, setPreference, cycle],
  )

  return <ColorSchemeContext.Provider value={value}>{children}</ColorSchemeContext.Provider>
}

export function useColorScheme(): ColorSchemeValue {
  return useContext(ColorSchemeContext) ?? standaloneDefault()
}
