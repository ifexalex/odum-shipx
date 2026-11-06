import { useEffect, useRef } from 'react'

// User-activity signals that count as "still here". Pointer moves are debounced
// by the browser into these; we deliberately omit raw mousemove to avoid a
// timer reset on every pixel — a click/key/scroll/touch is a real interaction.
const ACTIVITY_EVENTS: readonly string[] = ['mousedown', 'keydown', 'touchstart', 'scroll', 'wheel', 'focus']

export interface IdleTimeoutOptions {
  /** Inactivity before the warning appears (ms). */
  idleMs: number
  /** Grace period of the warning countdown before hard logout (ms). */
  warningMs: number
  /** Only arm the timers while true (i.e. authenticated, non-impersonation). */
  enabled: boolean
  /** Fired when idleMs elapses with no activity. `deadline` is the epoch-ms at
   *  which onTimeout will fire unless reset() is called first. */
  onWarn: (deadline: number) => void
  /** Fired warningMs after the warning if the user never responds. */
  onTimeout: () => void
}

export interface IdleTimeout {
  /** Dismiss the warning and restart the full idle countdown ("Stay signed in"). */
  reset: () => void
}

/**
 * Inactivity (idle) timeout. While `enabled`, resets a countdown on user
 * activity; after `idleMs` of inactivity it calls `onWarn` and, unless `reset`
 * is called within `warningMs`, calls `onTimeout`. During the warning window
 * activity is intentionally ignored — the user must explicitly choose to stay
 * signed in — so an incidental mouse move can't silently keep a session alive.
 */
export function useIdleTimeout({ idleMs, warningMs, enabled, onWarn, onTimeout }: IdleTimeoutOptions): IdleTimeout {
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const warningActive = useRef(false)
  // Keep the latest callbacks without re-arming the effect (and its listeners)
  // on every parent render.
  const onWarnRef = useRef(onWarn)
  const onTimeoutRef = useRef(onTimeout)
  // Assigned after commit, not during render: a ref write during render is not
  // safe under concurrent rendering, where a render can be thrown away.
  useEffect(() => {
    onWarnRef.current = onWarn
    onTimeoutRef.current = onTimeout
  })

  const resetRef = useRef<() => void>(() => undefined)

  useEffect(() => {
    if (!enabled) return undefined

    const clearIdle = (): void => {
      if (idleTimer.current) clearTimeout(idleTimer.current)
      idleTimer.current = null
    }
    const clearExpiry = (): void => {
      if (expiryTimer.current) clearTimeout(expiryTimer.current)
      expiryTimer.current = null
    }

    const armIdle = (): void => {
      clearIdle()
      idleTimer.current = setTimeout(() => {
        warningActive.current = true
        const deadline = Date.now() + warningMs
        expiryTimer.current = setTimeout(() => {
          warningActive.current = false
          onTimeoutRef.current()
        }, warningMs)
        onWarnRef.current(deadline)
      }, idleMs)
    }

    const onActivity = (): void => {
      // While the warning is up, only an explicit reset() counts — ignore
      // ambient activity so the countdown can't be cancelled by accident.
      if (warningActive.current) return
      armIdle()
    }

    const reset = (): void => {
      warningActive.current = false
      clearExpiry()
      armIdle()
    }
    resetRef.current = reset

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, onActivity, { passive: true })
    }
    armIdle()

    return () => {
      for (const evt of ACTIVITY_EVENTS) window.removeEventListener(evt, onActivity)
      clearIdle()
      clearExpiry()
      warningActive.current = false
    }
  }, [enabled, idleMs, warningMs])

  return { reset: () => resetRef.current() }
}
