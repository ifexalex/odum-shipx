/**
 * ToastRegion — where toasts appear (FD-21). Mounted once at the app root; see `design/toast.ts`.
 * A polite live region: a screen reader reads each toast once, without interrupting.
 */
import { useEffect, useState, type JSX } from 'react'
import { dismissToast, subscribeToasts, type ToastItem } from '../toast'
import { Icon, type IconName } from './Icon'
import { IconButton } from './IconButton'
import styles from './ToastRegion.module.css'

const ICON: Record<ToastItem['variant'], IconName> = { success: 'check', error: 'alert', info: 'info' }

export function ToastRegion(): JSX.Element {
  const [items, setItems] = useState<ToastItem[]>([])
  useEffect(() => subscribeToasts(setItems), [])
  return (
    <div className={styles.region} role="status" aria-live="polite" aria-relevant="additions">
      {items.map((item) => (
        <div key={item.id} className={[styles.toast, styles[item.variant]].join(' ')}>
          <span className={styles.icon}>
            <Icon name={ICON[item.variant]} size={16} stroke={2.4} />
          </span>
          <div className={styles.text}>
            <div className={styles.title}>{item.title}</div>
            {item.body && <div className={styles.body}>{item.body}</div>}
          </div>
          <IconButton icon="x" label="Dismiss" size="sm" onClick={() => dismissToast(item.id)} />
        </div>
      ))}
    </div>
  )
}
