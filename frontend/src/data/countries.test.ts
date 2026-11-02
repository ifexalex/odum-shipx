import { describe, expect, it } from 'vitest'
import {
  COUNTRIES,
  COUNTRIES_FOR_PICKER,
  DEFAULT_COUNTRY_CODE,
  PRIMARY_COUNTRY_CODES,
  countryByCode,
  countryByName,
} from './countries'
import { matchSubdivision, subdivisionLabelFor, subdivisionsFor } from './subdivisions'

describe('countries dataset', () => {
  it('has no duplicate ISO codes or names', () => {
    expect(new Set(COUNTRIES.map((c) => c.code)).size).toBe(COUNTRIES.length)
    expect(new Set(COUNTRIES.map((c) => c.name)).size).toBe(COUNTRIES.length)
  })

  it('uses uppercase alpha-2 codes and plausible dial codes', () => {
    for (const c of COUNTRIES) {
      expect(c.code, c.name).toMatch(/^[A-Z]{2}$/)
      // Digits only, no '+', 1-4 digits (NANP members like +1268 are 4).
      expect(c.dial, c.name).toMatch(/^\d{1,4}$/)
      expect(c.name.trim(), c.code).toBe(c.name)
    }
  })

  it('defaults to Nigeria', () => {
    expect(DEFAULT_COUNTRY_CODE).toBe('NG')
    expect(countryByCode('NG')?.dial).toBe('234')
  })

  it('resolves a country from a stored free-text name, case-insensitively', () => {
    // Existing rows hold typed names (tenant.origin_country, warehouse.country),
    // so a picker has to map a name back to a selection.
    expect(countryByName('nigeria')?.code).toBe('NG')
    expect(countryByName('  China  ')?.code).toBe('CN')
    expect(countryByName('Atlantis')).toBeUndefined()
    expect(countryByName(null)).toBeUndefined()
  })

  it('puts the operating markets first in the picker, then the rest', () => {
    expect(COUNTRIES_FOR_PICKER.slice(0, PRIMARY_COUNTRY_CODES.length).map((c) => c.code)).toEqual([
      ...PRIMARY_COUNTRY_CODES,
    ])
    // No country is dropped or duplicated by the reordering.
    expect(COUNTRIES_FOR_PICKER).toHaveLength(COUNTRIES.length)
    expect(new Set(COUNTRIES_FOR_PICKER.map((c) => c.code)).size).toBe(COUNTRIES.length)
  })

})

describe('subdivisions dataset', () => {
  it('covers Nigeria with 36 states plus the FCT', () => {
    const ng = subdivisionsFor('NG')
    expect(ng).toHaveLength(37)
    expect(ng).toContain('Lagos')
    expect(ng).toContain('Federal Capital Territory')
  })

  it('covers mainland China with its 31 divisions', () => {
    // 22 provinces + 5 autonomous regions + 4 municipalities. Hong Kong and
    // Macao are separate COUNTRIES entries, so they must not appear here.
    const cn = subdivisionsFor('CN')
    expect(cn).toHaveLength(31)
    expect(cn).toContain('Guangdong')
    expect(cn).not.toContain('Hong Kong')
  })

  it('has no duplicates and is sorted within each country', () => {
    for (const code of ['NG', 'CN', 'GH', 'ZA', 'GB', 'US']) {
      const list = subdivisionsFor(code)!
      expect(list, code).toBeDefined()
      expect(new Set(list).size, code).toBe(list.length)
      expect([...list].sort((a, b) => a.localeCompare(b)), code).toEqual([...list])
    }
  })

  it('returns undefined for a country with no list, so callers can fall back', () => {
    // A meaningful answer, not an error — an empty dropdown would block entry.
    expect(subdivisionsFor('KE')).toBeUndefined()
    expect(subdivisionsFor(null)).toBeUndefined()
  })

  it('labels a subdivision the way the country does', () => {
    expect(subdivisionLabelFor('NG')).toBe('State')
    expect(subdivisionLabelFor('CN')).toBe('Province')
    expect(subdivisionLabelFor('GH')).toBe('Region')
    expect(subdivisionLabelFor('KE')).toBe('State / province')
  })

  it('matches a stored subdivision name case-insensitively', () => {
    expect(matchSubdivision('NG', 'lagos')).toBe('Lagos')
    expect(matchSubdivision('NG', '  Rivers ')).toBe('Rivers')
    expect(matchSubdivision('NG', 'Atlantis')).toBeUndefined()
    expect(matchSubdivision('KE', 'Nairobi')).toBeUndefined()
  })
})
