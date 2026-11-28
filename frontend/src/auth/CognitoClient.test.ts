import { beforeEach, describe, expect, it, vi } from 'vitest'

interface AuthCallbacks {
  onSuccess: (session: unknown) => void
  onFailure: (err: unknown) => void
}
type RefreshCallback = (err: unknown, session: unknown) => void

class FakeCognitoUser {
  static instances: FakeCognitoUser[] = []
  authCallbacks: AuthCallbacks | null = null
  refreshCallback: RefreshCallback | null = null
  signedOut = false

  constructor(_data: unknown) {
    FakeCognitoUser.instances.push(this)
  }

  authenticateUser(_details: unknown, callbacks: AuthCallbacks): void {
    this.authCallbacks = callbacks
  }

  setAuthenticationFlowType(_flowType: string): void {}

  refreshSession(_token: unknown, callback: RefreshCallback): void {
    this.refreshCallback = callback
  }

  signOut(): void {
    this.signedOut = true
  }
}

vi.mock('amazon-cognito-identity-js', () => ({
  CognitoUserPool: class {},
  AuthenticationDetails: class {},
  CognitoRefreshToken: class {},
  CognitoUser: FakeCognitoUser,
}))

function fakeSession(): unknown {
  return {
    getIdToken: () => ({ getJwtToken: () => 'id-token' }),
    getAccessToken: () => ({ getJwtToken: () => 'access-token' }),
    getRefreshToken: () => ({ getToken: () => 'refresh-token' }),
  }
}

describe('CognitoClient', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'pool-1')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-1')
    FakeCognitoUser.instances = []
  })

  it('resolves tokens on successful sign in', async () => {
    const { signIn } = await import('./CognitoClient')
    const promise = signIn('a@b.com', 'password')
    FakeCognitoUser.instances[0]!.authCallbacks!.onSuccess(fakeSession())
    const tokens = await promise
    expect(tokens).toEqual({
      idToken: 'id-token',
      accessToken: 'access-token',
      refreshToken: 'refresh-token',
      pool: 'tenant',
    })
  })

  it('rejects on failed sign in', async () => {
    const { signIn } = await import('./CognitoClient')
    const promise = signIn('a@b.com', 'wrong-password')
    FakeCognitoUser.instances[0]!.authCallbacks!.onFailure(new Error('Incorrect username or password.'))
    await expect(promise).rejects.toThrow('Incorrect username or password.')
  })

  it('refreshes the session for the currently signed-in user', async () => {
    const { signIn, refreshSession } = await import('./CognitoClient')
    const signInPromise = signIn('a@b.com', 'password')
    FakeCognitoUser.instances[0]!.authCallbacks!.onSuccess(fakeSession())
    await signInPromise

    const refreshPromise = refreshSession('refresh-token')
    FakeCognitoUser.instances[0]!.refreshCallback!(undefined, fakeSession())
    await expect(refreshPromise).resolves.toEqual({
      idToken: 'id-token',
      accessToken: 'access-token',
      refreshToken: 'refresh-token',
      pool: 'tenant',
    })
  })

  it('rejects refresh when no user has signed in yet', async () => {
    vi.resetModules()
    const { refreshSession } = await import('./CognitoClient')
    await expect(refreshSession('refresh-token')).rejects.toThrow('No active Cognito user')
  })

  it('signs out the current user', async () => {
    const { signIn, signOut } = await import('./CognitoClient')
    const promise = signIn('a@b.com', 'password')
    FakeCognitoUser.instances[0]!.authCallbacks!.onSuccess(fakeSession())
    await promise
    signOut()
    expect(FakeCognitoUser.instances[0]!.signedOut).toBe(true)
  })
})
