import { createContext, useContext, useEffect, type ReactNode } from 'react'

export interface TopBarCtxValue {
  /** Last breadcrumb segment supplied by the current page (e.g. 'MSCU1234567'). */
  suffix: string | null
  setSuffix: (s: string | null) => void
  /** One-line descriptive subtitle shown under the page title in the TopBar. */
  subtitle: string | null
  setSubtitle: (s: string | null) => void
  /** Action buttons rendered in the TopBar right side, between search and bell. */
  actions: ReactNode | null
  setActions: (a: ReactNode | null) => void
  /** Handler for the shared TopBar search box, opted into by the active page. */
  onSearch: ((query: string) => void) | null
  setOnSearch: (fn: ((query: string) => void) | null) => void
  /** What the registered search box searches, e.g. "Search containers…". */
  searchPlaceholder: string | null
  setSearchPlaceholder: (text: string | null) => void
}

export const TopBarContext = createContext<TopBarCtxValue>({
  suffix: null,
  setSuffix: () => {},
  subtitle: null,
  setSubtitle: () => {},
  actions: null,
  setActions: () => {},
  onSearch: null,
  setOnSearch: () => {},
  searchPlaceholder: null,
  setSearchPlaceholder: () => {},
})

/**
 * Hook for pages to inject a breadcrumb suffix, action buttons, and/or a
 * search handler into the shared StaffLayout TopBar. All are automatically
 * cleared on unmount so navigating away never leaves stale content/behavior
 * in the bar.
 *
 * Usage:
 *   useTopBarSlot({ suffix: container.container_number })
 *   useTopBarSlot({ subtitle: 'Track refunds across all customers.' })
 *   useTopBarSlot({ actions: <Button>Create</Button> })
 *   useTopBarSlot({ onSearch: setSearch }) // syncs the header search box with
 *                                          // the page's own list filter state
 */
export function useTopBarSlot({
  suffix,
  subtitle,
  actions,
  onSearch,
  searchPlaceholder,
}: {
  suffix?: string | null
  subtitle?: string | null
  actions?: ReactNode | null
  onSearch?: ((query: string) => void) | null
  /** Names what `onSearch` searches. The header shows no search box unless a page registers a handler. */
  searchPlaceholder?: string
}): void {
  const ctx = useContext(TopBarContext)

  useEffect(() => {
    if (suffix !== undefined) ctx.setSuffix(suffix)
    return () => ctx.setSuffix(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suffix])

  useEffect(() => {
    if (subtitle !== undefined) ctx.setSubtitle(subtitle)
    return () => ctx.setSubtitle(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtitle])

  useEffect(() => {
    if (actions !== undefined) ctx.setActions(actions)
    return () => ctx.setActions(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (onSearch !== undefined) ctx.setOnSearch(() => onSearch)
    return () => ctx.setOnSearch(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onSearch])

  useEffect(() => {
    if (searchPlaceholder !== undefined) ctx.setSearchPlaceholder(searchPlaceholder)
    return () => ctx.setSearchPlaceholder(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchPlaceholder])
}
