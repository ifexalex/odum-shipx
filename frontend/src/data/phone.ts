/**
 * Phone parsing/formatting for the browser — the client-side counterpart to
 * `shared/phone.py`.
 *
 * The contract: **every phone field submits E.164** (`+2348012345678`). That is
 * what the database stores, so emitting it from the form means
 *   - customer de-duplication works (a number typed as `08012345678` and one
 *     imported as `+234801...` resolve to the same customer), and
 *   - the backend never has to guess a country. `normalize_phone` passes a
 *     string starting with '+' straight through, so a dial code the backend's
 *     `_DIAL_CODES` table has never heard of is still stored correctly.
 */

import {
  COUNTRIES,
  DEFAULT_COUNTRY_CODE,
  PRIMARY_COUNTRY_CODES,
  countryByCode,
  type Country,
} from './countries'

const IS_PRIMARY = new Set<string>(PRIMARY_COUNTRY_CODES)

/**
 * Candidate order for resolving a '+' number back to a country:
 *   1. longest dial code first, so '+1268' (Antigua) wins over '+1'
 *   2. then an operating market, so '+1' resolves to the US rather than Canada
 *   3. then alphabetically, purely for determinism
 *
 * Step 2 exists because some dial codes are genuinely shared and **cannot** be
 * resolved by prefix alone: +1 covers the US, Canada and much of the Caribbean;
 * +7 covers Russia and Kazakhstan. Distinguishing them needs area-code tables
 * (libphonenumber), which is not worth a dependency here, because the ambiguity
 * is only ever **cosmetic**: both candidates share the dial code, so `toE164`
 * reassembles the identical string either way and the stored value is unaffected.
 * The user can always correct the picker.
 */
const DIAL_RESOLUTION_ORDER: readonly Country[] = [...COUNTRIES].sort((a, b) => {
  if (a.dial.length !== b.dial.length) return b.dial.length - a.dial.length
  const aPrimary = IS_PRIMARY.has(a.code)
  const bPrimary = IS_PRIMARY.has(b.code)
  if (aPrimary !== bPrimary) return aPrimary ? -1 : 1
  return a.name.localeCompare(b.name)
})

export interface ParsedPhone {
  /** ISO alpha-2 of the resolved country. Falls back to the supplied default. */
  countryCode: string
  /** The national part, digits only, trunk '0' removed. May be ''. */
  national: string
}

/**
 * Split a stored phone into (country, national part) so a picker can show the
 * right selection when editing an existing record.
 *
 * `+234 801 234 5678` → { NG, '8012345678' }
 * `08012345678`       → { <default>, '8012345678' }  (trunk 0 stripped)
 * ''                  → { <default>, '' }
 *
 * A '+' number whose dial code matches nothing known keeps its digits in
 * `national` under the default country rather than being discarded — losing a
 * stored number because its country is unrecognised would be worse than showing
 * it imperfectly.
 */
export function parsePhone(
  raw: string | null | undefined,
  defaultCountryCode: string = DEFAULT_COUNTRY_CODE,
): ParsedPhone {
  const fallback = countryByCode(defaultCountryCode)?.code ?? DEFAULT_COUNTRY_CODE
  const text = (raw ?? '').trim()
  if (!text) return { countryCode: fallback, national: '' }

  const digits = text.replace(/\D/g, '')
  if (!digits) return { countryCode: fallback, national: '' }

  // Only treat it as international when it was actually written that way.
  // Bare '2348012345678' is ambiguous with a national number in some plans, but
  // an explicit '+' is not, so require it.
  if (text.startsWith('+')) {
    for (const country of DIAL_RESOLUTION_ORDER) {
      if (digits.startsWith(country.dial) && digits.length > country.dial.length) {
        return { countryCode: country.code, national: stripTrunk(digits.slice(country.dial.length)) }
      }
    }
    // Exactly a dial code and nothing more ('+234'): the country is known and
    // the national part is simply empty. Returning `digits` here would hand the
    // dial code back as a national number, which is how the doubling bug above
    // got its fuel.
    for (const country of DIAL_RESOLUTION_ORDER) {
      if (digits === country.dial) {
        return { countryCode: country.code, national: '' }
      }
    }
    return { countryCode: fallback, national: digits }
  }

  // Local format. If it happens to begin with the default country's own dial
  // code AND is longer than a plausible national number, treat it as
  // international anyway — manifests carry '2348012345678' without the '+'.
  const def = countryByCode(fallback)
  if (def && digits.startsWith(def.dial) && digits.length > def.dial.length + 6) {
    return { countryCode: def.code, national: stripTrunk(digits.slice(def.dial.length)) }
  }
  return { countryCode: fallback, national: stripTrunk(digits) }
}

/** Remove a single leading trunk '0' (as in Nigerian 0803…). */
function stripTrunk(digits: string): string {
  return digits.startsWith('0') ? digits.slice(1) : digits
}

/**
 * Assemble E.164 from a country + national part. Returns '' when there is no
 * national number, so an untouched optional field submits empty rather than a
 * bare dial code like '+234' that would store as a meaningless "number".
 */
export function toE164(countryCode: string, national: string): string {
  // Strip the trunk BEFORE testing for emptiness. A lone '0' — which is what
  // exists for one keystroke while someone types "0803…" — otherwise produced a
  // bare '+234'. parsePhone then read those dial digits back as the national
  // part, so the next keystroke built '+234234…': a doubled dial code that grew
  // with every character typed.
  const digits = stripTrunk((national ?? '').replace(/\D/g, ''))
  if (!digits) return ''
  const country = countryByCode(countryCode)
  const dial = country?.dial ?? countryByCode(DEFAULT_COUNTRY_CODE)!.dial
  return `+${dial}${digits}`
}

/**
 * Light plausibility check, deliberately not full per-country validation.
 *
 * A national subscriber number is 4–14 digits (E.164 caps the whole number at
 * 15 including the dial code). Rejecting more than this would need
 * libphonenumber's per-country rules; being stricter here risks blocking a
 * legitimate number, which is worse than accepting an odd one — the backend
 * normalises either way.
 */
export function isPlausibleNational(countryCode: string, national: string): boolean {
  const digits = (national ?? '').replace(/\D/g, '')
  if (!digits) return false
  const dial = countryByCode(countryCode)?.dial ?? ''
  return digits.length >= 4 && digits.length + dial.length <= 15
}
