import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { interpretApiError } from './errorBehavior'

function makeError(status: number, overrides: Partial<ConstructorParameters<typeof ApiError>[0]> = {}): ApiError {
  return new ApiError(
    {
      type: 'https://errors.logistics-api.com/some-error',
      title: 'Some error',
      status,
      detail: 'Something went wrong.',
      error_code: 'SOME_ERROR',
      ...overrides,
    },
    null,
  )
}

describe('interpretApiError', () => {
  it('maps 403 to a blocking banner', () => {
    expect(interpretApiError(makeError(403))).toEqual({ kind: 'blocking-banner' })
  })

  it('maps 404 to not-found', () => {
    expect(interpretApiError(makeError(404))).toEqual({ kind: 'not-found' })
  })

  it('maps 409 to an inline action error carrying the detail message', () => {
    expect(interpretApiError(makeError(409, { detail: 'Packing list already submitted.' }))).toEqual({
      kind: 'inline-action-error',
      message: 'Packing list already submitted.',
    })
  })

  it('maps 410 to the terminal offboarded state', () => {
    expect(interpretApiError(makeError(410))).toEqual({ kind: 'terminal-offboarded' })
  })

  it('maps 422 to validation, carrying field errors', () => {
    const fieldErrors = [{ field: 'email', message: 'Invalid email' }]
    expect(interpretApiError(makeError(422, { errors: fieldErrors, detail: 'Validation failed.' }))).toEqual({
      kind: 'validation',
      fieldErrors,
      message: 'Validation failed.',
    })
  })

  it('maps 429 to quota-exceeded', () => {
    expect(interpretApiError(makeError(429))).toEqual({ kind: 'quota-exceeded' })
  })

  it.each([0, 502, 503])('maps %i to a retryable toast', (status) => {
    expect(interpretApiError(makeError(status))).toEqual({
      kind: 'retryable-toast',
      message: 'A service is temporarily unavailable. Please try again shortly.',
    })
  })

  it('falls back to a generic toast for anything else', () => {
    expect(interpretApiError(makeError(418, { detail: "I'm a teapot." }))).toEqual({
      kind: 'generic-toast',
      message: "I'm a teapot.",
    })
  })
})
