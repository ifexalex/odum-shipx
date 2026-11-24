import { useMemo, type JSX } from 'react'
import { COUNTRIES_FOR_PICKER, countryByName } from '../../data/countries'
import { Combobox } from './Combobox'
import styles from './Field.module.css'

export interface CountrySelectProps {
  label?: string
  /**
   * The country NAME, which is what the database stores
   * (`tenant.origin_country`, `warehouse.country`). Not an ISO code.
   */
  value: string
  onChange: (countryName: string) => void
  name?: string
  id?: string
  /** Accepted for parity with the other fields; required fields carry no mark (FD-11: only optional ones do). */
  required?: boolean
  optional?: boolean
  helper?: string
  disabled?: boolean
  placeholder?: string
}

/**
 * Searchable country picker.
 *
 * Stores and emits the country **name** rather than an ISO code, because every
 * existing column holds a name and changing that would mean a migration plus a
 * display mapping on every read. Searching matches the name or the dial code,
 * so "234" finds Nigeria.
 *
 * A stored value that matches no known country is kept as its own option rather
 * than being silently dropped — a tenant row typed by hand years ago must not
 * lose its country just because this list spells it differently.
 */
export function CountrySelect({
  label,
  value,
  onChange,
  name,
  id,
  optional = false,
  helper,
  disabled = false,
  placeholder = 'Search for a country…',
}: CountrySelectProps): JSX.Element {
  const fieldId = id ?? name

  const options = useMemo(() => {
    const base = COUNTRIES_FOR_PICKER.map((c) => ({
      value: c.name,
      label: c.name,
      meta: `+${c.dial}`,
    }))
    const trimmed = value.trim()
    // Keep an unrecognised stored value selectable so it is visible and
    // preserved until someone deliberately changes it.
    if (trimmed && !countryByName(trimmed)) {
      return [{ value: trimmed, label: trimmed, meta: 'as stored' }, ...base]
    }
    return base
  }, [value])

  // Show the canonical spelling when the stored name differs only in case or
  // padding, so the picker does not look unset for a perfectly valid value.
  const selected = countryByName(value)?.name ?? value

  return (
    <div className={styles.fieldRoot}>
      {label && (
        <label className={styles.label} htmlFor={fieldId}>
          <span>
            {label}
          </span>
          {optional && <span className={styles.optionalTag}>Optional</span>}
        </label>
      )}
      <Combobox
        id={fieldId}
        ariaLabel={label}
        options={options}
        value={selected}
        onChange={onChange}
        disabled={disabled}
        placeholder={placeholder}
        searchPlaceholder="Search by name or dial code…"
        emptyText="No country matches"
      />
      {helper && <div className={styles.helper}>{helper}</div>}
    </div>
  )
}
