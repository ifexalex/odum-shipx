/**
 * ColorField — a brand colour: a swatch that opens the colour picker, and the hex code beside it to type or paste
 * (FD-11). `value` and `onChange` are a #rrggbb string.
 */
import { useState, type JSX, type ReactNode } from 'react'
import styles from './Field.module.css'
import { colors } from '../theme'
import { FieldShell } from './FieldShell'

export interface ColorFieldProps {
  label: string
  value: string
  onChange: (hex: string) => void
  name?: string
  optional?: boolean
  error?: string
  helper?: ReactNode
  disabled?: boolean
}

const HEX = /^#[0-9a-f]{6}$/i

export function ColorField({ label, value, onChange, name, optional, error, helper, disabled }: ColorFieldProps): JSX.Element {
  // What the user is typing, which may be half a code; the colour changes once it is a whole one.
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? value
  return (
    <FieldShell label={label} optional={optional} error={error ?? (draft !== null && !HEX.test(draft) ? 'Use a hex colour like #1c7922.' : undefined)} helper={helper} id={name}>
      {({ id, describedBy, invalid }) => (
        <div className={[styles.wrapper, invalid ? styles.wrapperError : ''].filter(Boolean).join(' ')}>
          <input
            type="color"
            className={styles.swatch}
            value={HEX.test(value) ? value : colors.primary}
            disabled={disabled}
            aria-label={`${label}: pick a colour`}
            onChange={(event) => {
              setDraft(null)
              onChange(event.target.value)
            }}
          />
          <input
            id={id}
            name={name}
            className={styles.input}
            value={shown}
            disabled={disabled}
            maxLength={7}
            spellCheck={false}
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            onChange={(event) => {
              const next = event.target.value.trim()
              setDraft(next)
              if (HEX.test(next)) onChange(next.toLowerCase())
            }}
            onBlur={() => setDraft(null)}
          />
        </div>
      )}
    </FieldShell>
  )
}
