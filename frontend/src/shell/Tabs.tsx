import type { JSX } from 'react'
import styles from './Tabs.module.css'

export interface TabItem {
  key: string
  label: string
  count?: number
}

export interface TabsProps {
  items: TabItem[]
  active: string
  onChange: (key: string) => void
}

export function Tabs({ items, active, onChange }: TabsProps): JSX.Element {
  return (
    <div className={styles.tabs} role="tablist" data-scroll-strip="">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={item.key === active}
          onClick={() => onChange(item.key)}
          className={[styles.tab, item.key === active ? styles.tabActive : ''].filter(Boolean).join(' ')}
        >
          {item.label}
          {item.count != null && (
            <span className={styles.count} aria-hidden="true">
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
