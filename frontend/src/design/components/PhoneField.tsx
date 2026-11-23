import { useMemo, type JSX } from 'react'
import { COUNTRIES_FOR_PICKER, DEFAULT_COUNTRY_CODE, countryByCode } from '../../data/countries'
import { parsePhone, toE164 } from '../../data/phone'
import { Combobox } from './Combobox'
import { Field } from './Field'
import styles from './Field.module.css'
import phoneStyles from './PhoneField.module.css'

export interface PhoneFieldProps {
  label?: string
  /**
   * The stored phone number. Normally E.164 (`+2348012345678`), but a legacy
   * local-format value is parsed too, so editing an old record works.
   */
  value: string
  /**
   * Receives **E.164** (`+2348012345678`), or `''` when the number is cleared.
   *
   * This is the whole point of the component: the database stores E.164, so
   * emitting it means customer de-duplication works and the backend never has
   * to guess a country from a bare local number.
   */
  onChange: (e164: string) => void
  /** Defaults to Nigeria — this platform's destination market. */
  defaultCountryCode?: string
  name?: string
  id?: string
  required?: boolean
  optional?: boolean
  helper?: string
  error?: string
  disabled?: boolean
  placeholder?: string
  autoComplete?: string
  autoFocus?: boolean
}

/**
 * Phone input with a searchable country-code picker, defaulting to Nigeria.
 *
 * Replaces the free-text phone inputs that were scattered across the app, each
 * of which depended on the user happening to type a format the backend could
 * normalise. The country is held in the parsed value rather than in local
 * state, so this stays a controlled component with a single source of truth —
 * `value` — and no effect is needed to resync when a parent loads a record.
 */
export function PhoneField({
  label,
  value,
  onChange,
  defaultCountryCode = DEFAULT_COUNTRY_CODE,
  name,
  id,
  required = false,
  optional = false,
  helper,
  error,
  disabled = false,
  placeholder = '801 234 5678',
  autoComplete = 'tel',
  autoFocus = false,
}: PhoneFieldProps): JSX.Element {
  const fieldId = id ?? name
  const { countryCode, national } = useMemo(
    () => parsePhone(value, defaultCountryCode),
    [value, defaultCountryCode],
  )

  const options = useMemo(
    () =>
      COUNTRIES_FOR_PICKER.map((c) => ({
        // Keyed by ISO code, not dial code: several countries share a dial code
        // (+1, +7), and Combobox needs each option to be distinct.
        value: c.code,
        label: `+${c.dial}`,
        meta: c.name,
      })),
    [],
  )

  const selectedDial = countryByCode(countryCode)?.dial ?? ''

  return (
    <div className={styles.fieldRoot}>
      {/* What sighted users read; the number input carries the same words as its own (hidden) label. */}
      {label && (
        <div className={styles.label} aria-hidden="true">
          <span>{label}</span>
          {optional && <span className={styles.optionalTag}>Optional</span>}
        </div>
      )}
      <div className={phoneStyles.row}>
        <div className={phoneStyles.dial}>
          <Combobox
            ariaLabel={label ? `${label} country code` : 'Country code'}
            options={options}
            value={countryCode}
            // Re-emit with the existing national part so switching country
            // rewrites the stored number instead of silently disagreeing with it.
            onChange={(code) => onChange(toE164(code, national))}
            disabled={disabled}
            placeholder={selectedDial ? `+${selectedDial}` : 'Code'}
            searchPlaceholder="Country or code…"
            emptyText="No match"
          />
        </div>
        <div className={phoneStyles.number}>
          <Field
            label={label ?? 'Phone number'}
            hideLabel
            id={fieldId}
            name={name}
            type="tel"
            inputMode="tel"
            autoComplete={autoComplete}
            autoFocus={autoFocus}
            required={required}
            disabled={disabled}
            placeholder={placeholder}
            value={national}
            onChange={(e) => onChange(toE164(countryCode, e.target.value))}
          />
        </div>
      </div>
      {error && <div className={styles.errorMsg}>{error}</div>}
      {helper && !error && <div className={styles.helper}>{helper}</div>}
    </div>
  )
}
