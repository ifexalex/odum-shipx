/**
 * Step-up re-authentication for dangerous platform actions (platform audit Phase 1, C-29).
 *
 * The API answers a dangerous platform request that carries no fresh re-authentication with 403 `STEP_UP_REQUIRED`.
 * `api/client.ts` then calls the registered handler (the `StepUpHost` dialog), which asks the admin to re-authenticate,
 * stores the five-minute step-up token here, and resolves; the client retries the request once with the token.
 *
 * Module memory only, like the session tokens (tokenStore.ts): never localStorage, gone on reload or sign-out.
 */

interface StepUpGrant {
  token: string
  /** Unix seconds, from the server. */
  expiresAt: number
}

let grant: StepUpGrant | null = null
let handler: (() => Promise<void>) | null = null
let pending: Promise<void> | null = null

/** Seconds of validity a token must have left to be sent, so it does not expire in flight. */
const SAFETY_MARGIN_SECONDS = 15

export const STEP_UP_HEADER = 'X-Step-Up-Token'

/** The current step-up token, or null when there is none or it is about to expire. */
export function getStepUpToken(now: number = Date.now() / 1000): string | null {
  if (!grant || grant.expiresAt - SAFETY_MARGIN_SECONDS <= now) return null
  return grant.token
}

export function setStepUpGrant(token: string, expiresAt: number): void {
  grant = { token, expiresAt }
}

export function clearStepUp(): void {
  grant = null
}

/** The dialog registers itself; returns the unregister function. */
export function registerStepUpHandler(fn: () => Promise<void>): () => void {
  handler = fn
  return () => {
    if (handler === fn) handler = null
  }
}

/**
 * Ask the admin to re-authenticate. Resolves once a fresh token is stored; rejects if they cancel or no dialog is
 * mounted. Concurrent callers share one prompt.
 */
export function requestStepUp(): Promise<void> {
  if (!handler) return Promise.reject(new Error('Re-authentication is not available here'))
  if (!pending) {
    pending = handler().finally(() => {
      pending = null
    })
  }
  return pending
}

/** Test helper: forget the grant, the handler and any prompt in progress. */
export function resetStepUpForTests(): void {
  grant = null
  handler = null
  pending = null
}
