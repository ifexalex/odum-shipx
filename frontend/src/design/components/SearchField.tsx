/**
 * SearchField — a list's search box (FD-11, FD-50): a search icon, the box, and a clear button once something is
 * typed. `label` names it for screen readers ("Search containers"); the placeholder says what can be searched.
 */
import { useId, type JSX, type KeyboardEvent } from 'react'
import styles from './SearchField.module.css'
import { Icon } from './Icon'
import { Pressable } from './Pressable'

export interface SearchFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void
  className?: string
  autoFocus?: boolean
}

export function SearchField({ label, value, onChange, placeholder, onKeyDown, className, autoFocus }: SearchFieldProps): JSX.Element {
  const id = useId()
  return (
    <div className={[styles.root, className].filter(Boolean).join(' ')}>
      <Icon name="search" size={14} color="var(--color-ink-4)" />
      <input
        id={id}
        type="search"
        className={styles.input}
        aria-label={label}
        placeholder={placeholder}
        value={value}
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {value && (
        <Pressable className={styles.clear} aria-label={`Clear ${label.toLowerCase()}`} onClick={() => onChange('')}>
          <Icon name="x" size={13} color="var(--color-ink-4)" />
        </Pressable>
      )}
    </div>
  )
}
