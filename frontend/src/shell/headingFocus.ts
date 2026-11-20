/**
 * Move keyboard focus to the page's heading after an in-app navigation (audit FD-48), so a screen reader announces
 * the new page and the next Tab starts from its top rather than from the link that was clicked.
 *
 * Only after a navigation: on the first load (React Router's location key "default") focus stays where the browser
 * put it, and outside a router (a component rendered on its own) nothing happens. Once per location, so a heading that re-renders, or a page that swaps its loading state for its content,
 * does not pull focus back. `preventScroll`, so the page does not jump.
 */
import { useContext, useEffect, type RefObject } from 'react'
import { UNSAFE_LocationContext } from 'react-router-dom'

let focusedFor: string | null = null

export function useFocusOnNavigate(ref: RefObject<HTMLElement | null>): void {
  // The context, not useLocation(), which throws outside a router.
  const key = useContext(UNSAFE_LocationContext)?.location?.key
  useEffect(() => {
    if (!key || key === 'default' || focusedFor === key) return
    focusedFor = key
    ref.current?.focus({ preventScroll: true })
  }, [key, ref])
}
