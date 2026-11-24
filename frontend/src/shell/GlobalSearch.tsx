import { useEffect, useId, useRef, useState, type FocusEvent, type JSX, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { MAX_SEARCH_LENGTH, MIN_SEARCH_LENGTH, type SearchResult } from '../api/search'
import { Icon } from '../design/components'
import { useGlobalSearch } from '../hooks/useGlobalSearch'
import styles from './GlobalSearch.module.css'
import { SEARCH_KIND_LABELS, searchResultPath, type SearchAudience } from './searchRoutes'
import { statusLabel, type StatusKind } from '../design/status'

export interface GlobalSearchProps {
  /** Which portal the viewer is in: decides where a result opens and how the box is drawn. */
  audience: SearchAudience
  placeholder: string
}

// A result's status in the registry's words (FD-08): a shipment is a packing list.
const RESULT_STATUS_KIND: Partial<Record<string, StatusKind>> = {
  container: 'container',
  shipment: 'packingList',
  invoice: 'invoice',
  release_note: 'releaseNote',
}

function resultStatus(kind: string, status: string, audience: SearchAudience): string {
  const registryKind = RESULT_STATUS_KIND[kind]
  if (registryKind) return statusLabel(registryKind, status, audience === 'customer' ? 'customer' : 'staff')
  const text = status.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * The header search box: finds a container, shipment, invoice, release note or customer by reference, container
 * number, tracking code or name (audit UX-05). What a signed-in user can find is decided by the server, so this
 * only renders and opens whatever comes back.
 *
 * ARIA 1.2 combobox with a listbox popup: focus stays in the input, the arrow keys move a virtual highlight
 * (`aria-activedescendant`), Enter opens it, Escape closes. At phone widths the box collapses to an icon and
 * opens as a full-width bar. Ctrl/Cmd+K focuses it from anywhere.
 */
export function GlobalSearch({ audience, placeholder }: GlobalSearchProps): JSX.Element {
  const navigate = useNavigate()
  const listId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  // Phone widths only: whether the collapsed icon has opened into the full-width bar.
  const [expanded, setExpanded] = useState(false)
  const [focusRequest, setFocusRequest] = useState(0)
  const { term, results, isSearching, isError } = useGlobalSearch(text)

  const typedLength = text.trim().length
  const long = typedLength >= MIN_SEARCH_LENGTH
  const showPanel = open && typedLength > 0
  const showList = showPanel && results.length > 0
  const optionId = (index: number): string => `${listId}-opt-${index}`

  // Focus is requested from event handlers but applied after the render that reveals the input (it is display:none
  // while collapsed on a phone).
  useEffect(() => {
    if (focusRequest > 0) inputRef.current?.focus()
  }, [focusRequest])

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setExpanded(true)
        setFocusRequest((n) => n + 1)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function close(): void {
    setOpen(false)
    setActive(-1)
  }

  function pick(result: SearchResult): void {
    const path = searchResultPath(result, audience)
    if (path === null) return
    setText('')
    close()
    setExpanded(false)
    inputRef.current?.blur()
    navigate(path)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (results.length === 0) return
      event.preventDefault()
      setOpen(true)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((current) => (current + step + results.length) % results.length)
    } else if (event.key === 'Enter') {
      // Results arrive best match first, so Enter with nothing highlighted opens the top one.
      const target = results[active >= 0 ? active : 0]
      if (showList && target) {
        event.preventDefault()
        pick(target)
      }
    } else if (event.key === 'Escape') {
      if (showPanel) {
        event.preventDefault()
        close()
      } else {
        setText('')
        setExpanded(false)
      }
    }
  }

  function onBlur(event: FocusEvent<HTMLDivElement>): void {
    if (rootRef.current?.contains(event.relatedTarget as Node | null)) return
    close()
    setExpanded(false)
  }

  let message: JSX.Element | null = null
  if (showPanel && !showList) {
    if (!long) {
      message = <p className={styles.message}>Keep typing: at least {MIN_SEARCH_LENGTH} characters.</p>
    } else if (isError) {
      message = <p className={styles.message}>Search is unavailable right now. Try again in a moment.</p>
    } else if (isSearching) {
      message = <p className={styles.message}>Searching…</p>
    } else {
      message = (
        <p className={styles.message}>
          No matches for “{term}”.
          <span className={styles.hint}>
            {audience === 'customer'
              ? 'Try a reference, container number or tracking code.'
              : 'Try a reference, container number, tracking code or customer name.'}
          </span>
        </p>
      )
    }
  }

  return (
    <div
      ref={rootRef}
      className={`${styles.root} ${audience === 'customer' ? styles.onBrand : ''} ${expanded ? styles.expanded : ''}`}
      onBlur={onBlur}
    >
      <button
        type="button"
        className={styles.toggle}
        aria-label="Search"
        onClick={() => {
          setExpanded(true)
          setFocusRequest((n) => n + 1)
        }}
      >
        <Icon name="search" size={17} stroke={2} />
      </button>
      <div className={styles.box}>
        <span className={styles.icon}>
          <Icon name="search" size={15} />
        </span>
        <input
          ref={inputRef}
          className={styles.input}
          type="search"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          maxLength={MAX_SEARCH_LENGTH}
          placeholder={placeholder}
          aria-label={placeholder}
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={showList ? listId : undefined}
          aria-activedescendant={showList && active >= 0 ? optionId(active) : undefined}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            setOpen(true)
            setActive(-1)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {showPanel && (
          <div className={styles.panel}>
            {showList && (
              <ul id={listId} role="listbox" aria-label="Search results" className={styles.list}>
                {results.map((result, index) => (
                  <li
                    key={`${result.kind}:${result.id}`}
                    id={optionId(index)}
                    role="option"
                    aria-selected={index === active}
                    className={`${styles.option} ${index === active ? styles.optionActive : ''}`}
                    // Keep focus in the input so a click is not preempted by the blur that closes the panel.
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => pick(result)}
                  >
                    <span className={styles.kind}>{SEARCH_KIND_LABELS[result.kind]}</span>
                    <span className={styles.body}>
                      <span className={styles.title}>{result.title}</span>
                      {result.subtitle && <span className={styles.subtitle}>{result.subtitle}</span>}
                    </span>
                    {result.status && <span className={styles.status}>{resultStatus(result.kind, result.status, audience)}</span>}
                  </li>
                ))}
              </ul>
            )}
            <div role="status" aria-live="polite">
              {message}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
