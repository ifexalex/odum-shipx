/**
 * Toasts (FD-21): the one way a page confirms that an action worked. Call `toast.success('Payment recorded',
 * 'ACM-INV-0042 · ₦150,000')` after a change succeeds; `<ToastRegion />` (mounted once, in App) shows it top right on
 * desktop and at the bottom on a phone, announces it to screen readers, and removes it after four seconds.
 *
 * A toast names what happened and to which record. Keep inline banners for state that lasts ("Approved by Chidi on
 * 13 Nov 2026"); a "Saved." banner that a page keeps in its own state is what this replaces.
 *
 * A module-level store, not a context, so a handler can call it without threading a hook through.
 */
export type ToastVariant = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  variant: ToastVariant
  title: string
  body?: string
}

export const TOAST_DURATION_MS = 4000
const MAX_SHOWN = 3

let items: ToastItem[] = []
let nextId = 1
const listeners = new Set<(items: ToastItem[]) => void>()
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function emit(): void {
  for (const listener of listeners) listener(items)
}

export function dismissToast(id: number): void {
  clearTimeout(timers.get(id))
  timers.delete(id)
  items = items.filter((item) => item.id !== id)
  emit()
}

function show(variant: ToastVariant, title: string, body?: string): number {
  const id = nextId++
  items = [...items, { id, variant, title, body }].slice(-MAX_SHOWN)
  timers.set(
    id,
    setTimeout(() => dismissToast(id), TOAST_DURATION_MS),
  )
  emit()
  return id
}

export const toast = {
  success: (title: string, body?: string): number => show('success', title, body),
  error: (title: string, body?: string): number => show('error', title, body),
  info: (title: string, body?: string): number => show('info', title, body),
}

export function subscribeToasts(listener: (items: ToastItem[]) => void): () => void {
  listeners.add(listener)
  listener(items)
  return () => listeners.delete(listener)
}

/** Test helper: start from no toasts. */
export function resetToasts(): void {
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
  items = []
  emit()
}
