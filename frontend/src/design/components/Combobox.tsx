import { useEffect, useId, useMemo, useRef, useState, type JSX } from 'react'
import { Icon } from './Icon'
import styles from './Combobox.module.css'

export interface ComboboxOption {
  value: string
  label: string
  /** Secondary line shown muted under the label (e.g. "76 CBM · rec. 70"). */
  meta?: string
}

export interface ComboboxProps {
  options: ComboboxOption[]
  value: string | null
  onChange: (value: string) => void
  placeholder?: string
  searchPlaceholder?: string
  disabled?: boolean
  emptyText?: string
  id?: string
  ariaLabel?: string
}

/**
 * Searchable single-select. A button showing the current selection opens a
 * panel with a filter box + keyboard-navigable list — better UX than a native
 * <select> once the list is long (container pickers, capacity presets).
 */
export function Combobox({
  options,
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  disabled = false,
  emptyText = 'No matches',
  id,
  ariaLabel,
}: ComboboxProps): JSX.Element {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()

  const selected = options.find((o) => o.value === value) ?? null

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(
      (o) => o.label.toLowerCase().includes(q) || (o.meta?.toLowerCase().includes(q) ?? false),
    )
  }, [options, query])

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent): void {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Focus the search box when opening; reset the query/active row.
  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      // Defer so the input is mounted.
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  function choose(optValue: string): void {
    onChange(optValue)
    setOpen(false)
  }

  function onKeyDown(e: React.KeyboardEvent): void {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const opt = filtered[active]
      if (opt) choose(opt.value)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        type="button"
        id={id}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={[styles.control, disabled ? styles.disabled : ''].filter(Boolean).join(' ')}
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
      >
        <span className={selected ? styles.value : styles.placeholder}>
          {selected ? selected.label : placeholder}
        </span>
        <Icon name="chevdown" size={14} color="var(--color-ink-4)" />
      </button>

      {open && (
        <div className={styles.panel}>
          <div className={styles.searchRow}>
            <Icon name="search" size={14} color="var(--color-ink-4)" />
            <input
              ref={inputRef}
              className={styles.search}
              placeholder={searchPlaceholder}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={onKeyDown}
              role="combobox"
              aria-controls={listId}
              aria-expanded={open}
              aria-autocomplete="list"
            />
          </div>
          <ul className={styles.list} id={listId} role="listbox">
            {filtered.length === 0 ? (
              <li className={styles.empty}>{emptyText}</li>
            ) : (
              filtered.map((opt, i) => (
                <li
                  key={opt.value}
                  role="option"
                  aria-selected={opt.value === value}
                  className={[
                    styles.option,
                    i === active ? styles.optionActive : '',
                    opt.value === value ? styles.optionSelected : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => {
                    // mousedown, not click: fire before the control button's
                    // blur/outside-click can close the panel.
                    e.preventDefault()
                    choose(opt.value)
                  }}
                >
                  <span className={styles.optLabel}>{opt.label}</span>
                  {opt.meta && <span className={styles.optMeta}>{opt.meta}</span>}
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
