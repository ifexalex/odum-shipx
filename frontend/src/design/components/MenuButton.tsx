/**
 * MenuButton (FD-14): a "more actions" button that opens a short menu of further actions. A page header keeps one
 * primary action and a few secondaries in view and folds the rest in here, so its action row never wraps into a wall
 * of buttons.
 *
 *   <MenuButton label="More invoice actions" items={[{ label: 'Cancel invoice', tone: 'danger', onSelect: cancel }]} />
 *
 * Keyboard: Enter, Space or Down opens it on the first item, Up opens it on the last; Up and Down move, Home and End
 * jump, Escape closes it and returns focus to the button, Tab closes it. A click outside closes it. Read-only sessions
 * disable the items that change data, the same rule as `Button` (`mutates` defaults to true for a danger item).
 */
import { useEffect, useId, useLayoutEffect, useRef, useState, type JSX, type KeyboardEvent, type ReactNode } from 'react'
import { READ_ONLY_TITLE, useReadOnlyBlock } from './Button'
import { Icon, type IconName } from './Icon'
import { IconButton } from './IconButton'
import styles from './MenuButton.module.css'

export interface MenuItem {
  label: string
  onSelect: () => void
  icon?: IconName
  /** A destructive action: shown in the error colour. */
  tone?: 'danger'
  disabled?: boolean
  /** Whether it changes data, for read-only sessions (default: only a danger item does). */
  mutates?: boolean
}

/** What a custom trigger must spread onto its `<button>`. */
export interface MenuTriggerProps {
  'aria-haspopup': 'menu'
  'aria-expanded': boolean
  'aria-controls'?: string
  onClick: () => void
  onKeyDown: (event: KeyboardEvent) => void
}

export interface MenuButtonProps {
  items: MenuItem[]
  /** The button's accessible name: "More actions", "More invoice actions". Also names the menu. */
  label?: string
  /**
   * A button of your own in place of the "more" icon button, such as the top bar's account button. It must render a
   * `<button>` and spread the props it is given.
   */
  trigger?: (props: MenuTriggerProps) => ReactNode
}

function Item({ item, onPick }: { item: MenuItem; onPick: (item: MenuItem) => void }): JSX.Element {
  const blocked = useReadOnlyBlock(item.tone === 'danger' ? 'danger-ghost' : 'ghost', item.mutates)
  const disabled = item.disabled || blocked
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      className={[styles.item, item.tone === 'danger' ? styles.danger : ''].join(' ')}
      aria-disabled={disabled || undefined}
      title={blocked ? READ_ONLY_TITLE : undefined}
      onClick={() => !disabled && onPick(item)}
    >
      {item.icon && <Icon name={blocked ? 'suspend' : item.icon} size={15} stroke={2} />}
      <span>{item.label}</span>
    </button>
  )
}

export function MenuButton({ items, label = 'More actions', trigger }: MenuButtonProps): JSX.Element | null {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const startAt = useRef<'first' | 'last'>('first')
  const menuId = useId()

  const entries = (): HTMLElement[] => Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])
  const button = (): HTMLButtonElement | null => rootRef.current?.querySelector('button') ?? null

  // The menu hangs from the button's right edge; where that would run off the left of the screen (the button sits at
  // the start of a row on a phone), it hangs from the left edge instead. Measured before paint, so it never flickers.
  useLayoutEffect(() => {
    const menu = menuRef.current
    if (!open || !menu) return
    menu.classList.remove(styles.alignStart!)
    if (menu.getBoundingClientRect().left < 8) menu.classList.add(styles.alignStart!)
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const list = entries()
    ;(startAt.current === 'last' ? list.at(-1) : list[0])?.focus()
    const onDown = (event: MouseEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  if (items.length === 0) return null

  const close = (refocus: boolean): void => {
    setOpen(false)
    if (refocus) button()?.focus()
  }
  const pick = (item: MenuItem): void => {
    close(true)
    item.onSelect()
  }
  const onButtonKey = (event: KeyboardEvent): void => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      startAt.current = event.key === 'ArrowUp' ? 'last' : 'first'
      setOpen(true)
    }
  }
  const onMenuKey = (event: KeyboardEvent): void => {
    const list = entries()
    const at = list.indexOf(document.activeElement as HTMLElement)
    const move: Record<string, number> = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: list.length - 1 }
    if (event.key in move) {
      event.preventDefault()
      list[(move[event.key]! + list.length) % list.length]?.focus()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      close(true)
    } else if (event.key === 'Tab') {
      close(false)
    }
  }

  const triggerProps: MenuTriggerProps = {
    'aria-haspopup': 'menu',
    'aria-expanded': open,
    'aria-controls': open ? menuId : undefined,
    onClick: () => {
      startAt.current = 'first'
      setOpen((o) => !o)
    },
    onKeyDown: onButtonKey,
  }

  return (
    <div ref={rootRef} className={styles.root}>
      {trigger ? (
        trigger(triggerProps)
      ) : (
        <IconButton icon="dot3" label={label} variant="secondary" {...triggerProps} />
      )}
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          className={styles.menu}
          onKeyDown={onMenuKey}
        >
          {items.map((item) => (
            <Item key={item.label} item={item} onPick={pick} />
          ))}
        </div>
      )}
    </div>
  )
}
