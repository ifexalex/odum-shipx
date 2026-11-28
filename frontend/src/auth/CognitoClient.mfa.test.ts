/**
 * Platform admins' Cognito pool (platform audit Phase 1b): signing in asks for the authenticator code, or for its setup
 * on the first sign-in, and the tokens say which pool issued them.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

interface Callbacks {
  onSuccess: (session: unknown) => void
  onFailure: (err: unknown) => void
  totpRequired?: () => void
  mfaSetup?: () => void
}

class FakeCognitoUser {
  static instances: FakeCognitoUser[] = []
  pool: unknown
  callbacks: Callbacks | null = null
  mfaCallbacks: { onSuccess: (s: unknown) => void; onFailure: (e: unknown) => void } | null = null
  sentCode: { code: string; type?: string } | null = null
  verifiedCode: string | null = null

  constructor(data: { Pool: unknown }) {
    this.pool = data.Pool
    FakeCognitoUser.instances.push(this)
  }
  authenticateUser(_d: unknown, callbacks: Callbacks): void {
    this.callbacks = callbacks
  }
  setAuthenticationFlowType(): void {}
  getUsername(): string {
    return 'admin@shipx.test'
  }
  sendMFACode(code: string, callbacks: { onSuccess: (s: unknown) => void; onFailure: (e: unknown) => void }, type?: string): void {
    this.sentCode = { code, type }
    this.mfaCallbacks = callbacks
  }
  associateSoftwareToken(callbacks: { associateSecretCode: (secret: string) => void }): void {
    callbacks.associateSecretCode('SECRETBASE32')
  }
  verifySoftwareToken(code: string, _name: string, callbacks: { onSuccess: (s: unknown) => void; onFailure: (e: unknown) => void }): void {
    this.verifiedCode = code
    this.mfaCallbacks = callbacks
  }
  signOut(): void {}
}

const poolIds: string[] = []
vi.mock('amazon-cognito-identity-js', () => ({
  CognitoUserPool: class {
    constructor(data: { UserPoolId: string }) {
      poolIds.push(data.UserPoolId)
    }
  },
  AuthenticationDetails: class {},
  CognitoRefreshToken: class {},
  CognitoUser: FakeCognitoUser,
}))

function fakeSession(): unknown {
  return {
    getIdToken: () => ({ getJwtToken: () => 'id' }),
    getAccessToken: () => ({ getJwtToken: () => 'access' }),
    getRefreshToken: () => ({ getToken: () => 'refresh' }),
  }
}

describe('CognitoClient multi-factor sign-in', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'tenant-pool')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'tenant-client')
    vi.stubEnv('VITE_COGNITO_PLATFORM_USER_POOL_ID', 'platform-pool')
    vi.stubEnv('VITE_COGNITO_PLATFORM_CLIENT_ID', 'platform-client')
    FakeCognitoUser.instances = []
  })

  it('knows when this build has a platform pool', async () => {
    const { hasPlatformPool } = await import('./CognitoClient')
    expect(hasPlatformPool()).toBe(true)
  })

  it('asks for the authenticator code, then signs in to the platform pool', async () => {
    const { MfaCodeRequiredError, signIn, submitMfaCode } = await import('./CognitoClient')
    const attempt = signIn('admin@shipx.test', 'pw', { pool: 'platform' })
    expect(poolIds).toContain('platform-pool')
    FakeCognitoUser.instances[0]!.callbacks!.totpRequired!()
    await expect(attempt).rejects.toBeInstanceOf(MfaCodeRequiredError)

    const finished = submitMfaCode('123456')
    const user = FakeCognitoUser.instances[0]!
    expect(user.sentCode).toEqual({ code: '123456', type: 'SOFTWARE_TOKEN_MFA' })
    user.mfaCallbacks!.onSuccess(fakeSession())
    await expect(finished).resolves.toMatchObject({ idToken: 'id', pool: 'platform' })
  })

  it('walks a first sign-in through authenticator setup', async () => {
    const { MfaSetupRequiredError, signIn, verifyMfaSetup } = await import('./CognitoClient')
    const attempt = signIn('admin@shipx.test', 'pw', { pool: 'platform' })
    FakeCognitoUser.instances[0]!.callbacks!.mfaSetup!()
    const err = await attempt.catch((e: unknown) => e)
    expect(err).toBeInstanceOf(MfaSetupRequiredError)
    expect((err as InstanceType<typeof MfaSetupRequiredError>).secret).toBe('SECRETBASE32')
    expect((err as InstanceType<typeof MfaSetupRequiredError>).otpauthUri).toBe(
      'otpauth://totp/ShipX:admin%40shipx.test?secret=SECRETBASE32&issuer=ShipX',
    )

    const finished = verifyMfaSetup('654321')
    FakeCognitoUser.instances[0]!.mfaCallbacks!.onSuccess(fakeSession())
    await expect(finished).resolves.toMatchObject({ pool: 'platform' })
    expect(FakeCognitoUser.instances[0]!.verifiedCode).toBe('654321')
  })

  it('refuses a code when no sign-in is waiting for one', async () => {
    const { signOut, submitMfaCode } = await import('./CognitoClient')
    signOut()
    await expect(submitMfaCode('123456')).rejects.toThrow()
  })
})
