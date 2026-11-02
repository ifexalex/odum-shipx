import { describe, expect, it } from 'vitest'
import { isPlausibleNational, parsePhone, toE164 } from './phone'

describe('parsePhone', () => {
  it('splits an E.164 number into country and national part', () => {
    expect(parsePhone('+2348012345678')).toEqual({ countryCode: 'NG', national: '8012345678' })
    expect(parsePhone('+8613800138000')).toEqual({ countryCode: 'CN', national: '13800138000' })
  })

  it('tolerates the spacing a human or a manifest writes', () => {
    expect(parsePhone('+234 801 234 5678')).toEqual({ countryCode: 'NG', national: '8012345678' })
    expect(parsePhone('  +44 (20) 7123-4567 ')).toEqual({ countryCode: 'GB', national: '2071234567' })
  })

  it('prefers the longest matching dial code', () => {
    // +1268 (Antigua) must win over +1 (US/Canada), or every Caribbean number
    // would come back as American with a mangled national part.
    expect(parsePhone('+12684641234')).toEqual({ countryCode: 'AG', national: '4641234' })
  })

  it('breaks a shared dial code toward an operating market', () => {
    // +1 is genuinely shared by the US and Canada and cannot be resolved by
    // prefix alone. The tie-break picks the operating market so the result is at
    // least deterministic; the ambiguity is cosmetic because both share the dial
    // code, so the number round-trips to the identical string either way.
    expect(parsePhone('+12125551234').countryCode).toBe('US')
    expect(toE164('US', '2125551234')).toBe(toE164('CA', '2125551234'))
  })

  it('treats a local number as the default country and strips the trunk 0', () => {
    expect(parsePhone('08012345678')).toEqual({ countryCode: 'NG', national: '8012345678' })
    expect(parsePhone('08012345678', 'GH')).toEqual({ countryCode: 'GH', national: '8012345678' })
  })

  it('reads a manifest-style international number written without the +', () => {
    // Imports carry '2348012345678'. Length disambiguates it from a national number.
    expect(parsePhone('2348012345678')).toEqual({ countryCode: 'NG', national: '8012345678' })
  })

  it('keeps the digits of an unrecognised + number instead of discarding them', () => {
    // Losing a stored number because its country is unknown is worse than
    // showing it under the default country.
    const parsed = parsePhone('+9995551234')
    expect(parsed.national).toBe('9995551234')
    expect(parsed.countryCode).toBe('NG')
  })

  it('returns the default country and an empty national part for blank input', () => {
    for (const input of ['', '   ', null, undefined, '+', 'abc']) {
      expect(parsePhone(input)).toEqual({ countryCode: 'NG', national: '' })
    }
  })
})

describe('toE164', () => {
  it('assembles a number the database will match exactly', () => {
    expect(toE164('NG', '8012345678')).toBe('+2348012345678')
    expect(toE164('CN', '13800138000')).toBe('+8613800138000')
  })

  it('strips a trunk 0 and any formatting the user typed', () => {
    expect(toE164('NG', '08012345678')).toBe('+2348012345678')
    expect(toE164('NG', '0801 234 5678')).toBe('+2348012345678')
  })

  it('returns empty rather than a bare dial code when nothing was entered', () => {
    // '+234' alone would persist as a meaningless "phone number" on every
    // optional field the user never touched.
    expect(toE164('NG', '')).toBe('')
    expect(toE164('NG', '   ')).toBe('')
  })

  it('falls back to the default dial code for an unknown country', () => {
    expect(toE164('ZZ', '8012345678')).toBe('+2348012345678')
  })

  it('never emits a bare dial code from a lone trunk zero', () => {
    // Found by a page test: while typing "0803…" the value is momentarily just
    // "0". Emitting '+234' for that made parsePhone read '234' back as the
    // national part, so the next keystroke produced '+234234…' and the number
    // grew a doubled dial code with every character.
    expect(toE164('NG', '0')).toBe('')
    expect(toE164('NG', '000')).toBe('+23400')
  })

  it('survives a character-by-character type-in without doubling the dial code', () => {
    // Simulates a controlled field: each keystroke re-parses the emitted value.
    let stored = ''
    for (const ch of '09098765432') {
      const { countryCode, national } = parsePhone(stored)
      stored = toE164(countryCode, national + ch)
    }
    expect(stored).toBe('+2349098765432')
  })

  it('reads a bare dial code as an empty national part', () => {
    expect(parsePhone('+234')).toEqual({ countryCode: 'NG', national: '' })
    expect(parsePhone('+86')).toEqual({ countryCode: 'CN', national: '' })
  })

  it('round-trips with parsePhone', () => {
    for (const e164 of ['+2348012345678', '+8613800138000', '+442071234567', '+12125551234']) {
      const { countryCode, national } = parsePhone(e164)
      expect(toE164(countryCode, national)).toBe(e164)
    }
  })
})

describe('isPlausibleNational', () => {
  it('accepts normal numbers and rejects obviously truncated ones', () => {
    expect(isPlausibleNational('NG', '8012345678')).toBe(true)
    expect(isPlausibleNational('NG', '123')).toBe(false)
    expect(isPlausibleNational('NG', '')).toBe(false)
  })

  it('enforces the E.164 15-digit ceiling including the dial code', () => {
    expect(isPlausibleNational('NG', '123456789012')).toBe(true) // 3 + 12 = 15
    expect(isPlausibleNational('NG', '1234567890123')).toBe(false) // 3 + 13 = 16
  })
})
