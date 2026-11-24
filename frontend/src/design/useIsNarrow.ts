import { useLayoutEffect, useState, type RefObject } from 'react'

/**
 * Whether an element is at or below `breakpoint` px wide, measured on the element itself with a ResizeObserver (not
 * the viewport), so a component switches layout by the room it has. An unmeasured element (width 0, e.g. jsdom) reads
 * as wide.
 */
export function useIsNarrow(ref: RefObject<HTMLElement | null>, breakpoint: number): boolean {
  const [isNarrow, setIsNarrow] = useState(false)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = (width: number): void => {
      if (width > 0) setIsNarrow(width <= breakpoint)
    }
    measure(el.getBoundingClientRect().width)

    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width != null) measure(width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref, breakpoint])

  return isNarrow
}
