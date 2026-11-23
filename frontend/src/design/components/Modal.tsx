import { useEffect, useId, useLayoutEffect, useRef, useState, type JSX, type MouseEvent as ReactMouseEvent, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import styles from './Modal.module.css'
import { Icon } from './Icon'

// Everything a keyboard can land on. `[tabindex="-1"]` is reachable by script but not by Tab, so it is left out.
const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
  'textarea:not([disabled]), [contenteditable="true"], [tabindex]:not([tabindex="-1"])'

function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((element) => {
    if (element.closest('[hidden], [inert]')) return false
    const style = getComputedStyle(element)
    return style.display !== 'none' && style.visibility !== 'hidden'
  })
}

/**
 * Where focus goes when a dialog opens: the first control the user is likely to want (a form field, an action
 * button), not the Close button that comes first in the markup. Close is the fallback, then the overlay itself.
 */
function initialFocusTarget(overlay: HTMLElement): HTMLElement {
  const items = focusableWithin(overlay)
  return items.find((element) => !element.hasAttribute('data-modal-close')) ?? items[0] ?? overlay
}

// Open overlays, innermost last. Only the innermost one handles Tab and Escape, so a confirmation opened over a form
// traps focus inside itself and one Escape closes one dialog, not all of them.
const overlayStack: object[] = []

// Background scroll is locked while any overlay is open and restored only when the last one closes.
let scrollLocks = 0
let restoreScroll: (() => void) | null = null

function lockScroll(): void {
  if (scrollLocks++ > 0) return
  const { body, documentElement } = document
  const previousOverflow = body.style.overflow
  const previousPadding = body.style.paddingRight
  // Hiding the scrollbar would shift the page sideways by its width; pad the body by the same amount.
  const scrollbar = window.innerWidth - documentElement.clientWidth
  body.style.overflow = 'hidden'
  if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`
  restoreScroll = () => {
    body.style.overflow = previousOverflow
    body.style.paddingRight = previousPadding
  }
}

function unlockScroll(): void {
  if (--scrollLocks > 0) return
  restoreScroll?.()
  restoreScroll = null
}

export interface DialogCloseGuard {
  /** True while the "Discard your changes?" question is showing. */
  confirming: boolean
  /** Close, unless something was typed in the dialog: then ask first (FD-12). */
  requestClose: () => void
  /** Whether the dialog holds input the user typed since it opened. */
  isDirty: () => boolean
  keepEditing: () => void
  discard: () => void
}

/**
 * Gives a dialog the behaviour every dialog needs, on the overlay element `overlayRef` points at: focus moves in when
 * it opens, Tab and Shift+Tab stay inside it, Escape asks to close, background scroll is locked, and focus goes back
 * to whatever opened it. A dialog with no accessible name is named from its first heading.
 *
 * Unsaved input (FD-12): once the user has typed into the dialog, Escape or a click on the backdrop asks "Discard
 * your changes?" instead of closing, so a stray click no longer throws a half-filled form away. The dialog's own
 * Cancel and Close buttons still close at once: that is a decision, not an accident.
 */
function useDialogBehavior(overlayRef: RefObject<HTMLElement | null>, onClose: (() => void) | undefined): DialogCloseGuard {
  // Read while rendering, before anything inside the dialog can take focus (an `autoFocus` field does so at commit).
  const [opener] = useState<Element | null>(() => document.activeElement)
  const [confirming, setConfirming] = useState(false)
  const dirtyRef = useRef(false)
  const confirmingRef = useRef(false)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
    confirmingRef.current = confirming
  })

  const ask = (show: boolean): void => {
    confirmingRef.current = show
    setConfirming(show)
  }
  const guard: DialogCloseGuard = {
    confirming,
    isDirty: () => dirtyRef.current,
    requestClose: () => {
      if (dirtyRef.current) ask(true)
      else onCloseRef.current?.()
    },
    keepEditing: () => ask(false),
    discard: () => {
      dirtyRef.current = false
      ask(false)
      onCloseRef.current?.()
    },
  }
  const guardRef = useRef<DialogCloseGuard>(guard)
  useEffect(() => {
    guardRef.current = guard
  })

  useEffect(() => {
    const overlay = overlayRef.current
    if (!overlay) return undefined
    const token = {}
    overlayStack.push(token)
    lockScroll()
    nameFromHeading(overlay)

    // A field that asked for focus itself (`autoFocus`) keeps it.
    if (!overlay.contains(document.activeElement)) initialFocusTarget(overlay).focus()

    const markDirty = (event: Event): void => {
      // Typing in the discard question itself does not count.
      if ((event.target as Element | null)?.closest?.('[data-discard-prompt]')) return
      dirtyRef.current = true
    }
    overlay.addEventListener('input', markDirty)

    function onKeyDown(event: KeyboardEvent): void {
      if (overlayStack[overlayStack.length - 1] !== token || !overlay) return
      if (event.key === 'Escape') {
        if (confirmingRef.current) guardRef.current.keepEditing()
        else guardRef.current.requestClose()
        return
      }
      if (event.key !== 'Tab') return

      const items = focusableWithin(overlay)
      const first = items[0]
      const last = items[items.length - 1]
      if (!first || !last) {
        event.preventDefault()
        overlay.focus()
        return
      }
      const active = document.activeElement
      if (!overlay.contains(active) || active === overlay) {
        // Focus has wandered out (or onto the bare overlay): bring it back in rather than let Tab continue behind.
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      overlay.removeEventListener('input', markDirty)
      overlayStack.splice(overlayStack.indexOf(token), 1)
      unlockScroll()
      // Back to the control that opened the dialog, unless it has since left the page.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [overlayRef, opener])

  return guard
}

/** "Discard your changes?", shown over a dialog whose backdrop was clicked (or Escape pressed) with input in it. */
function DiscardPrompt({ guard }: { guard: DialogCloseGuard }): JSX.Element {
  const titleId = useId()
  const keepRef = useRef<HTMLButtonElement>(null)
  useEffect(() => keepRef.current?.focus(), [])
  return (
    <div
      className={styles.discard}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-discard-prompt
      onClick={(event) => event.stopPropagation()}
    >
      <p id={titleId} className={styles.discardTitle}>
        Discard your changes?
      </p>
      <p className={styles.discardBody}>What you typed in this dialog will be lost.</p>
      <div className={styles.discardActions}>
        <button ref={keepRef} type="button" className={styles.discardKeep} onClick={guard.keepEditing}>
          Keep editing
        </button>
        <button type="button" className={styles.discardDrop} onClick={guard.discard}>
          Discard changes
        </button>
      </div>
    </div>
  )
}

let headingCount = 0

/** A dialog with no `aria-label` or `aria-labelledby` is named by its first heading, so it is never announced bare. */
function nameFromHeading(overlay: HTMLElement): void {
  const dialog = overlay.querySelector<HTMLElement>('[role="dialog"]')
  if (!dialog || dialog.hasAttribute('aria-label') || dialog.hasAttribute('aria-labelledby')) return
  const heading = dialog.querySelector<HTMLElement>('h1, h2, h3, h4')
  if (!heading) return
  if (!heading.id) heading.id = `dialog-heading-${++headingCount}`
  dialog.setAttribute('aria-labelledby', heading.id)
}

export interface ModalOverlayProps {
  onClose?: () => void
  children: ReactNode
}

/**
 * The scrim and centring container, with no header/body/footer chrome, for callers that need the backdrop behaviour
 * without Modal's structure. It also gives its dialog the behaviour in `useDialogBehavior`.
 */
export function ModalOverlay({ onClose, children }: ModalOverlayProps): JSX.Element {
  const overlayRef = useRef<HTMLDivElement>(null)
  const guard = useDialogBehavior(overlayRef, onClose)

  return createPortal(
    <div
      ref={overlayRef}
      className={styles.overlay}
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) guard.requestClose()
      }}
    >
      {children}
      {guard.confirming && <DiscardPrompt guard={guard} />}
    </div>,
    document.body,
  )
}

/**
 * The same dialog behaviour for a dialog that is not built on `Modal`: render it as the first child of the dialog's
 * own overlay element (the one that dims the page and closes on click).
 *
 *     <div className={styles.modalOverlay} onClick={onCancel}>
 *       <DialogGuard onClose={onCancel} />
 *       <div role="dialog" aria-modal="true">…</div>
 *     </div>
 *
 * It renders a hidden placeholder and applies the behaviour to that placeholder's parent. Most of the app's dialogs are
 * hand-rolled, including the payment and pickup flows, so this is what gives them focus handling without rewriting
 * their markup. New dialogs should use `Modal`; a test fails for any dialog that uses neither.
 */
export function DialogGuard({ onClose }: { onClose?: () => void }): JSX.Element {
  const anchorRef = useRef<HTMLSpanElement>(null)
  const overlayRef = useRef<HTMLElement | null>(null)
  const [overlay, setOverlay] = useState<HTMLElement | null>(null)
  // Before `useDialogBehavior`'s effect runs (layout effects come first), point it at the parent.
  useLayoutEffect(() => {
    const parent = anchorRef.current?.parentElement ?? null
    overlayRef.current = parent
    setOverlay(parent)
    if (parent && !parent.hasAttribute('tabindex')) {
      // Last-resort focus target for a dialog with nothing focusable in it.
      parent.tabIndex = -1
      parent.style.outline = 'none'
    }
  }, [])
  const guard = useDialogBehavior(overlayRef, onClose)
  const guardRef = useRef(guard)
  useEffect(() => {
    guardRef.current = guard
  })

  // The page's own overlay closes on click. With unsaved input, catch that click on the backdrop before it reaches
  // the page's handler (React's listener runs later, at the root) and ask first.
  useEffect(() => {
    if (!overlay) return undefined
    const onBackdropClick = (event: MouseEvent): void => {
      if (event.target !== overlay || !guardRef.current.isDirty()) return
      event.stopPropagation()
      guardRef.current.requestClose()
    }
    overlay.addEventListener('click', onBackdropClick)
    return () => overlay.removeEventListener('click', onBackdropClick)
  }, [overlay])

  return (
    <>
      <span ref={anchorRef} hidden />
      {guard.confirming && overlay && createPortal(<DiscardPrompt guard={guard} />, overlay)}
    </>
  )
}

export interface ModalProps {
  open: boolean
  onClose?: () => void
  title?: string
  /** Panel width (FD-12): sm 480 (alert, confirmation), md 560 (form, default), lg 720 (long form), xl 960 (detail). */
  size?: 'sm' | 'md' | 'lg' | 'xl'
  children: ReactNode
  footer?: ReactNode
}

export function Modal({ open, onClose, title, size = 'md', children, footer }: ModalProps): JSX.Element | null {
  const titleId = useId()
  if (!open) return null

  const stopPropagation = (event: ReactMouseEvent<HTMLDivElement>): void => event.stopPropagation()

  return (
    <ModalOverlay onClose={onClose}>
      <div
        className={styles.panel}
        style={{ maxWidth: `var(--dialog-${size})` }}
        role="dialog"
        aria-modal="true"
        // Named by its own visible heading, so what a screen reader announces can never drift from what is on screen.
        aria-labelledby={title ? titleId : undefined}
        onClick={stopPropagation}
      >
        {title && (
          <div className={styles.header}>
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            <button type="button" aria-label="Close" data-modal-close className={styles.closeButton} onClick={() => onClose?.()}>
              <Icon name="x" size={18} />
            </button>
          </div>
        )}
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </ModalOverlay>
  )
}
