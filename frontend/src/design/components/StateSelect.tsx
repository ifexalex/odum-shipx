import { useMemo, type JSX } from 'react'
import { countryByName } from '../../data/countries'
import { matchSubdivision, subdivisionLabelFor, subdivisionsFor } from '../../data/subdivisions'
import { Combobox } from './Combobox'
import { Field } from './Field'
import styles from './Field.module.css'

export interface StateSelectProps {
  /** Omit to use the country's own term — "State", "Province", "Region". */
  label?: string
  /** Country NAME (as stored). The subdivision list is derived from it. */
  country: string
  value: string
  onChange: (subdivision: string) => void
  name?: string
  id?: string
  required?: boolean
  optional?: boolean
  helper?: string
  disabled?: boolean
}

/**
 * Searchable state/province picker for a given country, with a deliberate
 * free-text fallback.
 *
 * `subdivisions.ts` only carries lists for the countries ShipX operates in. For
 * anything else this renders a plain text input instead of an empty dropdown:
 * a picker with nothing in it would make the field impossible to fill, which is
 * strictly worse than typing. The label follows local usage, so a Chinese
 * origin address asks for a "Province" and a Ghanaian one for a "Region".
 */
export function StateSelect({
  label,
  country,
  value,
  onChange,
  name,
  id,
  required = false,
  optional = false,
  helper,
  disabled = false,
}: StateSelectProps): JSX.Element {
  const countryCode = countryByName(country)?.code
  const list = subdivisionsFor(countryCode)
  const resolvedLabel = label ?? subdivisionLabelFor(countryCode)
  const fieldId = id ?? name

  const options = useMemo(() => {
    if (!list) return []
    const base = list.map((s) => ({ value: s, label: s }))
    const trimmed = value.trim()
    // Preserve a stored value that is not in the list (a renamed state, or a
    // row typed before this picker existed) rather than blanking it.
    if (trimmed && !matchSubdivision(countryCode, trimmed)) {
      return [{ value: trimmed, label: trimmed, meta: 'as stored' }, ...base]
    }
    return base
  }, [list, value, countryCode])

  if (!list) {
    return (
      <Field
        label={resolvedLabel}
        name={name}
        id={id}
        required={required}
        optional={optional}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={country ? `${resolvedLabel} in ${country}` : resolvedLabel}
        helper={helper ?? (country ? `No ${resolvedLabel.toLowerCase()} list on file for ${country} — type it.` : undefined)}
      />
    )
  }

  const selected = matchSubdivision(countryCode, value) ?? value

  return (
    <div className={styles.fieldRoot}>
      <label className={styles.label} htmlFor={fieldId}>
        <span>
          {resolvedLabel}
        </span>
        {optional && <span className={styles.optionalTag}>Optional</span>}
      </label>
      <Combobox
        id={fieldId}
        ariaLabel={resolvedLabel}
        options={options}
        value={selected}
        onChange={onChange}
        disabled={disabled}
        placeholder={`Select a ${resolvedLabel.toLowerCase()}…`}
        searchPlaceholder="Search…"
        emptyText="No match"
      />
      {helper && <div className={styles.helper}>{helper}</div>}
    </div>
  )
}
