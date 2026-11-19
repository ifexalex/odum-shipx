/**
 * RadioGroup — a labelled set of choices, each with an optional line of explanation (FD-11).
 *
 *   <RadioGroup label="Refund preference" name="choice" value={choice} onChange={setChoice}
 *     options={[{ value: 'immediate_refund', label: 'Bank account refund', hint: 'Within 5–7 business days.' }]} />
 */
import type { JSX, ReactNode } from 'react'
import styles from './Field.module.css'

export interface RadioOption<V extends string> {
  value: V
  label: ReactNode
  hint?: ReactNode
  disabled?: boolean
}

export interface RadioGroupProps<V extends string> {
  label: string
  hideLabel?: boolean
  name: string
  value: V | null
  onChange: (value: V) => void
  options: RadioOption<V>[]
  /** `cards`: each choice is a bordered tile, side by side (a language, a plan). */
  layout?: 'list' | 'cards'
}

export function RadioGroup<V extends string>({ label, hideLabel, name, value, onChange, options, layout = 'list' }: RadioGroupProps<V>): JSX.Element {
  return (
    <fieldset className={styles.radioGroup}>
      <legend className={hideLabel ? styles.visuallyHidden : styles.label}>{label}</legend>
      <div className={layout === 'cards' ? styles.radioCards : styles.radioOptions}>
        {options.map((option) => (
          <label
            key={option.value}
            className={[styles.radioOption, layout === 'cards' ? styles.radioCard : '', layout === 'cards' && value === option.value ? styles.radioCardActive : '']
              .filter(Boolean)
              .join(' ')}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              disabled={option.disabled}
              onChange={() => onChange(option.value)}
            />
            <span>
              <strong>{option.label}</strong>
              {option.hint && <span className={styles.radioHint}>{option.hint}</span>}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
