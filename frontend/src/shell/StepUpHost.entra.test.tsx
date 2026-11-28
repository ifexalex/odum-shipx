/**
 * The re-authentication dialog on Entra (platform audit Phase 1b): a fresh Microsoft sign-in in a small window, whose
 * ID token the server checks.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformSecurityApi } from '../api/platformSecurity'
import { beginStepUpSignIn } from '../auth/authClient'
import { getStepUpToken, requestStepUp, resetStepUpForTests } from '../auth/stepUp'
import { StepUpHost } from './StepUpHost'

vi.mock('../auth/authClient', () => ({ authProvider: 'entra', beginStepUpSignIn: vi.fn() }))
vi.mock('../api/platformSecurity', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/platformSecurity')>()
  return { ...original, platformSecurityApi: { ...original.platformSecurityApi, stepUp: vi.fn() } }
})

beforeEach(() => {
  vi.clearAllMocks()
  resetStepUpForTests()
})

describe('StepUpHost on Entra', () => {
  it('signs in again in a window and sends the fresh ID token', async () => {
    vi.mocked(beginStepUpSignIn).mockResolvedValue('fresh.id.token')
    vi.mocked(platformSecurityApi.stepUp).mockResolvedValue({ step_up_token: 'tok', expires_at: Date.now() / 1000 + 300 })
    render(<StepUpHost />)
    let prompt!: Promise<void>
    act(() => {
      prompt = requestStepUp()
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in again' }))
    await expect(prompt).resolves.toBeUndefined()
    expect(platformSecurityApi.stepUp).toHaveBeenCalledWith({ id_token: 'fresh.id.token' })
    expect(getStepUpToken()).toBe('tok')
  })

  it('shows why the window did not finish', async () => {
    vi.mocked(beginStepUpSignIn).mockRejectedValue(new Error('Allow pop-ups for ShipX, then try again.'))
    render(<StepUpHost />)
    act(() => {
      void requestStepUp().catch(() => undefined)
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in again' }))
    expect(await screen.findByText('Allow pop-ups for ShipX, then try again.')).toBeInTheDocument()
    expect(platformSecurityApi.stepUp).not.toHaveBeenCalled()
  })
})
