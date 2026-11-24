/**
 * A form's unsaved input, kept in this browser tab so a detour (creating the container a packing list needs, a
 * reload, the back button) does not lose it (FD-25, FD-54).
 *
 * Session storage, not local storage: the draft survives navigation and reloads within the tab, but closing the tab
 * on a shared office machine leaves nothing behind for the next person. The key names the tenant and user, so another
 * account signed in on the same tab never sees it. Storage can be blocked; the form then works as before, without a
 * draft.
 *
 *   const [seed] = useState(() => readTabDraft<Fields>('packing-list', session))
 *   const [name, setName] = useState(seed?.name ?? '')
 *   const draft = useTabDraft('packing-list', { name }, { name: '' })
 */
import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { SessionContext } from '../auth/SessionContext'
import type { Session } from '../auth/types'

interface Stored<T> {
  value: T
  savedAt: string
}

/** How long typing pauses before the draft is written. */
const WRITE_DELAY_MS = 400

function storageKey(form: string, session: Pick<Session, 'tenantId' | 'userId'> | null | undefined): string {
  return `shipx_draft:${form}:${session?.tenantId ?? 'none'}:${session?.userId ?? 'none'}`
}

function readStored<T>(key: string): Stored<T> | null {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as Stored<T>) : null
  } catch {
    return null
  }
}

/** The draft this tab holds for `form`, to seed the form's fields when it opens; null when there is none. */
export function readTabDraft<T>(form: string, session: Pick<Session, 'tenantId' | 'userId'> | null | undefined): T | null {
  return readStored<T>(storageKey(form, session))?.value ?? null
}

export interface TabDraft {
  /** When the current input was last written to the tab, or null when nothing is stored. */
  savedAt: Date | null
  /** Forget the draft: after the form is saved for real, or when the user starts over. */
  clear: () => void
}

/**
 * Keep `value` in the tab while it differs from `pristine`.
 *
 * @param form A name for the form, part of the storage key.
 * @param value The form's current input. It must survive a JSON round trip.
 * @param pristine The input of an untouched form; matching it removes the draft instead of storing it.
 * @param enabled False while the form edits a record saved on the server, which is its own draft.
 */
export function useTabDraft<T>(form: string, value: T, pristine: T, enabled = true): TabDraft {
  const session = useContext(SessionContext)?.session
  const key = storageKey(form, session)
  const [savedAt, setSavedAt] = useState<Date | null>(() => {
    const stored = enabled ? readStored<T>(key) : null
    return stored ? new Date(stored.savedAt) : null
  })
  const serialised = JSON.stringify(value)
  const pristineSerialised = JSON.stringify(pristine)
  // Set by clear(), so a write already scheduled for the input being discarded does not bring it back.
  const cleared = useRef(false)
  // The write waiting out the typing pause. Leaving the page (in the app or the browser) writes it at once, so the
  // last few keystrokes before a click away are not lost (FD-54).
  const pending = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!enabled) return undefined
    cleared.current = false
    const write = (): void => {
      pending.current = null
      if (cleared.current) return
      try {
        if (serialised === pristineSerialised) {
          window.sessionStorage.removeItem(key)
          setSavedAt(null)
          return
        }
        const now = new Date()
        const stored: Stored<T> = { value: JSON.parse(serialised) as T, savedAt: now.toISOString() }
        window.sessionStorage.setItem(key, JSON.stringify(stored))
        setSavedAt(now)
      } catch {
        // Blocked or full storage: the form still works, it just keeps no draft.
      }
    }
    pending.current = write
    const timer = window.setTimeout(write, WRITE_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [enabled, key, serialised, pristineSerialised])

  // Flush a pending write when the form unmounts (navigating away) or the page is hidden (reload, tab close).
  useEffect(() => {
    const flush = (): void => pending.current?.()
    window.addEventListener('pagehide', flush)
    return () => {
      window.removeEventListener('pagehide', flush)
      flush()
    }
  }, [])

  const clear = useCallback(() => {
    cleared.current = true
    try {
      window.sessionStorage.removeItem(key)
    } catch {
      // Nothing was stored, then.
    }
    setSavedAt(null)
  }, [key])

  return { savedAt, clear }
}
