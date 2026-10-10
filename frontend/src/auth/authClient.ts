// Cloud-agnostic auth facade. The app imports auth functions from here, not
// from a specific provider, so the identity backend is selected by build-time
// config: VITE_AUTH_PROVIDER = 'cognito' (AWS, default) | 'entra' (Azure).
//
// Both providers expose the same signIn/refreshSession/signOut surface, so the
// LoginScreen + SessionProvider are unchanged across clouds. Password-reset
// flows are Cognito's in-app challenge model; on Entra they are hosted/self-
// service (the Entra impl rejects them with a clear message).

import * as cognito from './CognitoClient'
import * as entra from './EntraClient'

export type { CognitoTokens } from './CognitoClient'
// A real error class (instanceof checks in LoginScreen); Entra never throws it.
export { NewPasswordRequiredError } from './CognitoClient'

const provider = (import.meta.env.VITE_AUTH_PROVIDER || 'cognito').toLowerCase()

/** The active identity provider for this build. */
export const authProvider: 'cognito' | 'entra' = provider === 'entra' ? 'entra' : 'cognito'

const impl = authProvider === 'entra' ? entra : cognito

export const signIn = impl.signIn
export const signOut = impl.signOut
export const refreshSession = impl.refreshSession
export const forgotPassword = impl.forgotPassword
export const completeNewPassword = impl.completeNewPassword
export const confirmForgotPassword = impl.confirmForgotPassword
export const hasPendingNewPasswordChallenge = impl.hasPendingNewPasswordChallenge
