/**
 * Pressable (FD-07) — the unstyled button underneath a selectable tile, an option row, a pipeline stage or a work
 * queue row: anything clickable that is not shaped like a button. Pages never write a raw `<button>`; they use
 * Button, IconButton, a router Link (for navigation) or this.
 *
 * It defaults to `type="button"` (a bare button inside a form submits it), keeps the page's own styling, and adds the
 * shared focus ring.
 */
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import styles from './Pressable.module.css'

export type PressableProps = ButtonHTMLAttributes<HTMLButtonElement>

export const Pressable = forwardRef<HTMLButtonElement, PressableProps>(function Pressable({ className, ...rest }, ref) {
  return <button ref={ref} type="button" {...rest} className={[styles.pressable, className].filter(Boolean).join(' ')} />
})
