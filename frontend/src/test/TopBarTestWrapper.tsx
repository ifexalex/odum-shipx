import { useState, type ReactNode } from 'react'
import { TopBarContext } from '../shell/TopBarContext'

/**
 * Wraps a staff-shell page in a real TopBarContext and surfaces whatever the
 * page injects (subtitle, actions, search handler) into the DOM, so isolated
 * unit tests can assert on them the same way StaffLayout renders them.
 *
 * Needed because list pages no longer render their own title/actions in-body —
 * they push them to the shared TopBar via useTopBarSlot().
 */
export function TopBarTestWrapper({ children }: { children: ReactNode }): React.JSX.Element {
  const [suffix, setSuffix] = useState<string | null>(null)
  const [subtitle, setSubtitle] = useState<string | null>(null)
  const [actions, setActions] = useState<ReactNode | null>(null)
  const [onSearch, setOnSearch] = useState<((query: string) => void) | null>(null)
  return (
    <TopBarContext.Provider
      value={{ suffix, setSuffix, subtitle, setSubtitle, actions, setActions, onSearch, setOnSearch }}
    >
      {children}
      {subtitle && <div data-testid="topbar-subtitle">{subtitle}</div>}
      {actions && <div data-testid="topbar-actions">{actions}</div>}
      {onSearch && (
        <input
          aria-label="Header search"
          data-testid="topbar-search"
          onChange={(event) => onSearch(event.target.value)}
        />
      )}
    </TopBarContext.Provider>
  )
}
