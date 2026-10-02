import { useEffect, type JSX, type MouseEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import styles from './Modal.module.css'
import { Icon } from './Icon'

export interface ModalOverlayProps {
  onClose?: () => void
  children: ReactNode
}

// The scrim + centering container alone, with no header/body/footer chrome —
// for callers that need the backdrop behavior without Modal's structure.
export function ModalOverlay({ onClose, children }: ModalOverlayProps): JSX.Element {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return createPortal(
    <div className={styles.overlay} onClick={() => onClose?.()}>
      {children}
    </div>,
    document.body,
  )
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
  if (!open) return null

  const stopPropagation = (event: MouseEvent<HTMLDivElement>): void => event.stopPropagation()

  return (
    <ModalOverlay onClose={onClose}>
      <div
        className={styles.panel}
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={stopPropagation}
      >
        {title && (
          <div className={styles.header}>
            <h2 className={styles.title}>{title}</h2>
            <button type="button" aria-label="Close" className={styles.closeButton} onClick={() => onClose?.()}>
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
