import { ApiError } from './client'

// One status-code -> UI-behavior mapping, used everywhere instead of letting
// each page branch on error.status itself (05_api_client_contract.md). Task
// 09 wires this into React Query's global onError; until then, call it
// directly from a catch block.
export type ApiErrorBehavior =
  | { kind: 'blocking-banner' }
  | { kind: 'not-found' }
  | { kind: 'inline-action-error'; message: string }
  | { kind: 'terminal-offboarded' }
  | { kind: 'validation'; fieldErrors: { field: string; message: string }[] | undefined; message: string }
  | { kind: 'quota-exceeded' }
  | { kind: 'retryable-toast'; message: string }
  | { kind: 'generic-toast'; message: string }

export function interpretApiError(error: ApiError): ApiErrorBehavior {
  switch (error.status) {
    case 403:
      return { kind: 'blocking-banner' }
    case 404:
      return { kind: 'not-found' }
    case 409:
      return { kind: 'inline-action-error', message: error.message }
    case 410:
      return { kind: 'terminal-offboarded' }
    case 422:
      return { kind: 'validation', fieldErrors: error.fieldErrors, message: error.message }
    case 429:
      return { kind: 'quota-exceeded' }
    case 0: // network failure — see client.ts#doFetch
    case 502:
    case 503:
      return { kind: 'retryable-toast', message: 'A service is temporarily unavailable. Please try again shortly.' }
    default:
      return { kind: 'generic-toast', message: error.message }
  }
}
