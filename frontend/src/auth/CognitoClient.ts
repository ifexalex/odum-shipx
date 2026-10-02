import {
  AuthenticationDetails,
  CognitoRefreshToken,
  CognitoUser,
  CognitoUserPool,
  type CognitoUserSession,
} from 'amazon-cognito-identity-js'
import { MemoryStorage } from './storage'

export interface CognitoTokens {
  idToken: string
  accessToken: string
  refreshToken: string
}

function readEnv(name: string): string {
  const value = import.meta.env[name]
  if (!value) throw new Error(`Missing required env var: ${name}`)
  return value
}

let pool: CognitoUserPool | null = null
// Module-level, not React state — per 11_security_and_compliance.md, the active
// Cognito user (and the tokens it caches internally via MemoryStorage) must
// never live in a devtools-inspectable, localStorage-backed place.
let currentUser: CognitoUser | null = null

function getPool(): CognitoUserPool {
  if (!pool) {
    pool = new CognitoUserPool({
      UserPoolId: readEnv('VITE_COGNITO_USER_POOL_ID'),
      ClientId: readEnv('VITE_COGNITO_CLIENT_ID'),
      Storage: new MemoryStorage(),
      // amazon-cognito-identity-js always targets real AWS unless given an
      // explicit endpoint — local dev points this at Moto's cognito-idp
      // (see frontend/.env.local's VITE_COGNITO_ENDPOINT). Unset in
      // production, where this must hit real Cognito.
      ...(import.meta.env.VITE_COGNITO_ENDPOINT ? { endpoint: import.meta.env.VITE_COGNITO_ENDPOINT } : {}),
    })
  }
  return pool
}

function tokensFromSession(session: CognitoUserSession): CognitoTokens {
  return {
    idToken: session.getIdToken().getJwtToken(),
    accessToken: session.getAccessToken().getJwtToken(),
    refreshToken: session.getRefreshToken().getToken(),
  }
}

// Set when signIn hits Cognito's NEW_PASSWORD_REQUIRED challenge (first login
// after backend-provisioned registration emails a temporary password). The
// reset-password screen completes the challenge via completeNewPassword().
let pendingNewPasswordUser: CognitoUser | null = null

/** Thrown by signIn when the user must set a permanent password first. */
export class NewPasswordRequiredError extends Error {
  constructor() {
    super('A new password is required before signing in')
    this.name = 'NewPasswordRequiredError'
  }
}

// Authenticates directly against Cognito — the backend API never sees a password.
export function signIn(email: string, password: string): Promise<CognitoTokens> {
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: email, Pool: getPool(), Storage: new MemoryStorage() })
    if (import.meta.env.VITE_COGNITO_ENDPOINT) {
      // Moto's cognito-idp doesn't reliably emulate SRP's auth math — fall
      // back to USER_PASSWORD_AUTH against Moto only. Real Cognito (no
      // VITE_COGNITO_ENDPOINT) always uses the SDK's default USER_SRP_AUTH,
      // which never sends the password to the server even encrypted.
      user.setAuthenticationFlowType('USER_PASSWORD_AUTH')
    }
    const authDetails = new AuthenticationDetails({ Username: email, Password: password })
    user.authenticateUser(authDetails, {
      onSuccess: (session) => {
        currentUser = user
        resolve(tokensFromSession(session))
      },
      onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
      // First login with a backend-provisioned temporary password: park the
      // user and let the UI route to the set-new-password screen.
      newPasswordRequired: () => {
        pendingNewPasswordUser = user
        reject(new NewPasswordRequiredError())
      },
    })
  })
}

/**
 * Completes the NEW_PASSWORD_REQUIRED challenge started by signIn.
 * Resolves with a full token set — the user is signed in afterwards.
 */
export function completeNewPassword(newPassword: string): Promise<CognitoTokens> {
  return new Promise((resolve, reject) => {
    const user = pendingNewPasswordUser
    if (!user) {
      reject(new Error('No pending new-password challenge — sign in first'))
      return
    }
    user.completeNewPasswordChallenge(newPassword, {}, {
      onSuccess: (session) => {
        pendingNewPasswordUser = null
        currentUser = user
        resolve(tokensFromSession(session))
      },
      onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
    })
  })
}

export function hasPendingNewPasswordChallenge(): boolean {
  return pendingNewPasswordUser !== null
}

/** Starts the forgot-password flow — Cognito emails a verification code. */
export function forgotPassword(email: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: email, Pool: getPool(), Storage: new MemoryStorage() })
    user.forgotPassword({
      onSuccess: () => resolve(),
      // inputVerificationCode fires as soon as the code is dispatched — treat as success.
      inputVerificationCode: () => resolve(),
      onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
    })
  })
}

/** Confirms the forgot-password flow with the emailed code + new password. */
export function confirmForgotPassword(email: string, code: string, newPassword: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: email, Pool: getPool(), Storage: new MemoryStorage() })
    user.confirmPassword(code, newPassword, {
      onSuccess: () => resolve(),
      onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
    })
  })
}

// Silent refresh using the Cognito refresh token flow — only valid for normal
// sessions. Impersonation tokens hard-expire and must not call this.
export function refreshSession(refreshToken: string): Promise<CognitoTokens> {
  return new Promise((resolve, reject) => {
    if (!currentUser) {
      reject(new Error('No active Cognito user to refresh — call signIn first'))
      return
    }
    currentUser.refreshSession(new CognitoRefreshToken({ RefreshToken: refreshToken }), (err, session) => {
      if (err) {
        reject(err instanceof Error ? err : new Error(String(err)))
        return
      }
      resolve(tokensFromSession(session as CognitoUserSession))
    })
  })
}

export function signOut(): void {
  currentUser?.signOut()
  currentUser = null
}
