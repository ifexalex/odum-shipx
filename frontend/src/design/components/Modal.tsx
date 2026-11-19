import { useEffect, useId, useLayoutEffect, useRef, useState, type JSX, type MouseEvent, type ReactNode, type RefObject } from 'react'
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

/**
 * Gives a dialog the behaviour every dialog needs, on the overlay element `overlayRef` points at: focus moves in when
 * it opens, Tab and Shift+Tab stay inside it, Escape calls `onClose`, background scroll is locked, and focus goes back
 * to whatever opened it. A dialog with no accessible name is named from its first heading.
 */
function useDialogBehavior(overlayRef: RefObject<HTMLElement | null>, onClose: (() => void) | undefined): void {
  // Read while rendering, before anything inside the dialog can take focus (an `autoFocus` field does so at commit).
  const [opener] = useState<Element | null>(() => document.activeElement)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
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

    function onKeyDown(event: KeyboardEvent): void {
      if (overlayStack[overlayStack.length - 1] !== token || !overlay) return
      if (event.key === 'Escape') {
        onCloseRef.current?.()
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
      overlayStack.splice(overlayStack.indexOf(token), 1)
      unlockScroll()
      // Back to the control that opened the dialog, unless it has since left the page.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [overlayRef, opener])
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
  useDialogBehavior(overlayRef, onClose)

  return createPortal(
    <div ref={overlayRef} className={styles.overlay} tabIndex={-1} onClick={() => onClose?.()}>
      {children}
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
  // Before `useDialogBehavior`'s effect runs (layout effects come first), point it at the parent.
  useLayoutEffect(() => {
    const overlay = anchorRef.current?.parentElement ?? null
    overlayRef.current = overlay
    if (overlay && !overlay.hasAttribute('tabindex')) {
      // Last-resort focus target for a dialog with nothing focusable in it.
      overlay.tabIndex = -1
      overlay.style.outline = 'none'
    }
  }, [])
  useDialogBehavior(overlayRef, onClose)
  return <span ref={anchorRef} hidden />
}

export interface ModalProps {
  open: boolean
  onClose?: () => void
  title?: string
  /** Panel width in px — 480 (alert), 560 (form, default), 720 (long-form), 960 (detail). */
  width?: number
  children: ReactNode
  footer?: ReactNode
}

export function Modal({ open, onClose, title, width = 560, children, footer }: ModalProps): JSX.Element | null {
  const titleId = useId()
  if (!open) return null

  const stopPropagation = (event: MouseEvent<HTMLDivElement>): void => event.stopPropagation()

  return (
    <ModalOverlay onClose={onClose}>
      <div
        className={styles.panel}
        style={{ maxWidth: width }}
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
