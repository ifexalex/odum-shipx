/**
 * The re-authentication dialog (platform audit Phase 1, C-29): password first, the authenticator code when the pool
 * asks for it, and the token stored for the retry.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { platformSecurityApi } from '../api/platformSecurity'
import { getStepUpToken, requestStepUp, resetStepUpForTests } from '../auth/stepUp'
import { StepUpHost } from './StepUpHost'

vi.mock('../api/platformSecurity', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/platformSecurity')>()
  return { ...original, platformSecurityApi: { ...original.platformSecurityApi, stepUp: vi.fn() } }
})

function apiError(code: string, detail: string): ApiError {
  return new ApiError({ type: 'x', title: 'Forbidden', status: 403, detail, error_code: code }, null)
}

beforeEach(() => {
  vi.clearAllMocks()
  resetStepUpForTests()
})

describe('StepUpHost', () => {
  it('stays hidden until a request asks for re-authentication', () => {
    render(<StepUpHost />)
    expect(screen.queryByText("Confirm it's you")).toBeNull()
  })

  it('asks for the code after the password, then stores the token and resolves', async () => {
    vi.mocked(platformSecurityApi.stepUp)
      .mockRejectedValueOnce(apiError('STEP_UP_MFA_REQUIRED', 'Enter the 6-digit code.'))
      .mockResolvedValueOnce({ step_up_token: 'tok', expires_at: Date.now() / 1000 + 300 })
    render(<StepUpHost />)

    let prompt!: Promise<void>
    act(() => {
      prompt = requestStepUp()
    })
    await userEvent.type(await screen.findByLabelText(/Password/), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await userEvent.type(await screen.findByLabelText(/Authenticator code/), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await expect(prompt).resolves.toBeUndefined()
    expect(platformSecurityApi.stepUp).toHaveBeenLastCalledWith({ password: 'secret', mfa_code: '123456' })
    expect(getStepUpToken()).toBe('tok')
    expect(screen.queryByText("Confirm it's you")).toBeNull()
  })

  it('shows a failed attempt and lets the admin cancel', async () => {
    vi.mocked(platformSecurityApi.stepUp).mockRejectedValueOnce(
      apiError('STEP_UP_FAILED', 'Re-authentication failed. Check your password and code.'),
    )
    render(<StepUpHost />)
    let prompt!: Promise<void>
    act(() => {
      prompt = requestStepUp()
    })
    const outcome = prompt.catch((e: unknown) => e)
    await userEvent.type(await screen.findByLabelText(/Password/), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText('Re-authentication failed. Check your password and code.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await outcome).toBeInstanceOf(Error)
    expect(getStepUpToken()).toBeNull()
  })
})
