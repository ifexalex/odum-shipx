import { beforeEach, describe, expect, it } from 'vitest'
import { rememberNext, takeNext } from './returnPath'

describe('returning from the interactive (Entra) sign-in', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('gives back the page the visitor wanted, once', () => {
    rememberNext('/my-billing/abc')
    expect(takeNext()).toBe('/my-billing/abc')
    expect(takeNext()).toBeNull()
  })

  it('refuses a stored value that is not a safe in-app path', () => {
    window.sessionStorage.setItem('shipx_login_next', 'https://example.com')
    expect(takeNext()).toBeNull()
  })

  it('remembering nothing clears an earlier value', () => {
    rememberNext('/containers')
    rememberNext(null)
    expect(takeNext()).toBeNull()
  })
})
