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
  /** Tenant/role resolved by the backend, for IdPs that don't put them in the
   *  token (Entra External ID). Cognito leaves these unset — its token carries
   *  custom:tenant_id / cognito:groups directly. */
  tenantId?: string | null
  role?: string | null
  roles?: string[] | null
  /** Which Cognito pool issued the tokens: the platform admins' pool (MFA required, platform audit Phase 1b) or the
   *  tenant pool. The backend's session cookie refreshes through the matching app client. */
  pool?: CognitoPoolKind
}

/** The tenant pool (everyone else) or the platform admins' pool, where MFA is required. */
export type CognitoPoolKind = 'tenant' | 'platform'

/** True when this build knows the platform admins' pool (VITE_COGNITO_PLATFORM_*). */
export function hasPlatformPool(): boolean {
  return Boolean(import.meta.env.VITE_COGNITO_PLATFORM_USER_POOL_ID && import.meta.env.VITE_COGNITO_PLATFORM_CLIENT_ID)
}

function readEnv(name: string): string {
  const value = import.meta.env[name]
  if (!value) throw new Error(`Missing required env var: ${name}`)
  return value
}

const pools: Partial<Record<CognitoPoolKind, CognitoUserPool>> = {}
// Module-level, not React state — per 11_security_and_compliance.md, the active
// Cognito user (and the tokens it caches internally via MemoryStorage) must
// never live in a devtools-inspectable, localStorage-backed place.
let currentUser: CognitoUser | null = null
let currentPool: CognitoPoolKind = 'tenant'

function getPool(kind: CognitoPoolKind = 'tenant'): CognitoUserPool {
  let pool = pools[kind]
  if (!pool) {
    pool = new CognitoUserPool({
      UserPoolId: readEnv(kind === 'platform' ? 'VITE_COGNITO_PLATFORM_USER_POOL_ID' : 'VITE_COGNITO_USER_POOL_ID'),
      ClientId: readEnv(kind === 'platform' ? 'VITE_COGNITO_PLATFORM_CLIENT_ID' : 'VITE_COGNITO_CLIENT_ID'),
      Storage: new MemoryStorage(),
      // amazon-cognito-identity-js always targets real AWS unless given an
      // explicit endpoint — local dev points this at Moto's cognito-idp
      // (see frontend/.env.local's VITE_COGNITO_ENDPOINT). Unset in
      // production, where this must hit real Cognito.
      ...(import.meta.env.VITE_COGNITO_ENDPOINT ? { endpoint: import.meta.env.VITE_COGNITO_ENDPOINT } : {}),
    })
    pools[kind] = pool
  }
  return pool
}

function tokensFromSession(session: CognitoUserSession, pool: CognitoPoolKind = 'tenant'): CognitoTokens {
  return {
    idToken: session.getIdToken().getJwtToken(),
    accessToken: session.getAccessToken().getJwtToken(),
    refreshToken: session.getRefreshToken().getToken(),
    pool,
  }
}

// ---------------------------------------------------------------------------
// Multi-factor sign-in (platform admins' pool, platform audit Phase 1b)
// ---------------------------------------------------------------------------

/** Thrown by signIn when the pool wants the authenticator code; call submitMfaCode next. */
export class MfaCodeRequiredError extends Error {
  constructor() {
    super('Enter the code from your authenticator app')
    this.name = 'MfaCodeRequiredError'
  }
}

/**
 * Thrown on the first sign-in to a pool that requires MFA: the user must add ShipX to an authenticator app with
 * `secret` (or `otpauthUri`), then call verifyMfaSetup with the code it shows.
 */
export class MfaSetupRequiredError extends Error {
  readonly secret: string
  readonly otpauthUri: string
  constructor(secret: string, email: string) {
    super('Set up an authenticator app to finish signing in')
    this.name = 'MfaSetupRequiredError'
    this.secret = secret
    this.otpauthUri = `otpauth://totp/ShipX:${encodeURIComponent(email)}?secret=${secret}&issuer=ShipX`
  }
}

// The user parked on an MFA challenge, and which pool they are signing in to. Module memory only, like currentUser.
let pendingMfa: { user: CognitoUser; pool: CognitoPoolKind; email: string } | null = null

type Settle = { resolve: (t: CognitoTokens) => void; reject: (e: Error) => void }

/** Callbacks shared by sign-in and the new-password step: either can end in an MFA challenge. */
function authCallbacks(user: CognitoUser, poolKind: CognitoPoolKind, email: string, settle: Settle) {
  return {
    onSuccess: (session: CognitoUserSession) => {
      pendingMfa = null
      currentUser = user
      currentPool = poolKind
      settle.resolve(tokensFromSession(session, poolKind))
    },
    onFailure: (err: unknown) => settle.reject(err instanceof Error ? err : new Error(String(err))),
    newPasswordRequired: () => {
      pendingNewPasswordUser = user
      pendingChallengePool = poolKind
      settle.reject(new NewPasswordRequiredError())
    },
    totpRequired: () => {
      pendingMfa = { user, pool: poolKind, email }
      settle.reject(new MfaCodeRequiredError())
    },
    mfaSetup: () => {
      user.associateSoftwareToken({
        associateSecretCode: (secret: string) => {
          pendingMfa = { user, pool: poolKind, email }
          settle.reject(new MfaSetupRequiredError(secret, email))
        },
        onFailure: (err: unknown) => settle.reject(err instanceof Error ? err : new Error(String(err))),
      })
    },
  }
}

/** Answer the TOTP challenge started by signIn. */
export function submitMfaCode(code: string): Promise<CognitoTokens> {
  return new Promise((resolve, reject) => {
    const parked = pendingMfa
    if (!parked) {
      reject(new Error('No sign-in is waiting for a code — sign in first'))
      return
    }
    parked.user.sendMFACode(
      code,
      {
        onSuccess: (session) => {
          pendingMfa = null
          currentUser = parked.user
          currentPool = parked.pool
          resolve(tokensFromSession(session, parked.pool))
        },
        onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
      },
      'SOFTWARE_TOKEN_MFA',
    )
  })
}

/** Finish authenticator setup with the first code the app shows; signs the user in. */
export function verifyMfaSetup(code: string): Promise<CognitoTokens> {
  return new Promise((resolve, reject) => {
    const parked = pendingMfa
    if (!parked) {
      reject(new Error('No sign-in is waiting for authenticator setup — sign in first'))
      return
    }
    parked.user.verifySoftwareToken(code, 'ShipX', {
      onSuccess: (session) => {
        pendingMfa = null
        currentUser = parked.user
        currentPool = parked.pool
        resolve(tokensFromSession(session, parked.pool))
      },
      onFailure: (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
    })
  })
}

// Set when signIn hits Cognito's NEW_PASSWORD_REQUIRED challenge (first login
// after backend-provisioned registration emails a temporary password). The
// reset-password screen completes the challenge via completeNewPassword().
let pendingNewPasswordUser: CognitoUser | null = null
let pendingChallengePool: CognitoPoolKind = 'tenant'

/** Thrown by signIn when the user must set a permanent password first. */
export class NewPasswordRequiredError extends Error {
  constructor() {
    super('A new password is required before signing in')
    this.name = 'NewPasswordRequiredError'
  }
}

// Authenticates directly against Cognito — the backend API never sees a password. `pool: 'platform'` signs a platform
// admin in to their own pool, which asks for an authenticator code (or its setup) after the password.
export function signIn(email: string, password: string, options: { pool?: CognitoPoolKind } = {}): Promise<CognitoTokens> {
  const poolKind = options.pool ?? 'tenant'
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: email, Pool: getPool(poolKind), Storage: new MemoryStorage() })
    if (import.meta.env.VITE_COGNITO_ENDPOINT) {
      // Moto's cognito-idp doesn't reliably emulate SRP's auth math — fall
      // back to USER_PASSWORD_AUTH against Moto only. Real Cognito (no
      // VITE_COGNITO_ENDPOINT) always uses the SDK's default USER_SRP_AUTH,
      // which never sends the password to the server even encrypted.
      user.setAuthenticationFlowType('USER_PASSWORD_AUTH')
    }
    const authDetails = new AuthenticationDetails({ Username: email, Password: password })
    // First login with a backend-provisioned temporary password parks the user for the set-new-password screen
    // (newPasswordRequired); the platform pool then asks for an authenticator code or its setup.
    user.authenticateUser(authDetails, authCallbacks(user, poolKind, email, { resolve, reject }))
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
    const poolKind = pendingChallengePool
    // A platform admin's first sign-in continues into the authenticator setup from here. The pending user is kept
    // until the challenge succeeds, so a refused password (too weak) can be tried again.
    const settle: Settle = {
      resolve: (tokens) => {
        pendingNewPasswordUser = null
        resolve(tokens)
      },
      reject: (err) => {
        if (err instanceof MfaCodeRequiredError || err instanceof MfaSetupRequiredError) pendingNewPasswordUser = null
        reject(err)
      },
    }
    user.completeNewPasswordChallenge(newPassword, {}, authCallbacks(user, poolKind, user.getUsername(), settle))
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
      resolve(tokensFromSession(session as CognitoUserSession, currentPool))
    })
  })
}

export function signOut(): void {
  currentUser?.signOut()
  currentUser = null
  pendingMfa = null
}
