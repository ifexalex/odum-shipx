/**
 * The re-authentication dialog for dangerous platform actions (platform audit Phase 1, C-29).
 *
 * Mounted once for platform admins. It registers itself with `auth/stepUp.ts`; when the API answers a request with
 * `STEP_UP_REQUIRED`, the API client opens it, waits, and retries the request with the five-minute token it stores.
 * Cognito: password, then the authenticator code when the pool asks for it. Entra: a fresh Microsoft sign-in in a small
 * window (auth/EntraClient.beginStepUpSignIn), whose ID token the server checks.
 */
import { useEffect, useRef, useState, type JSX } from 'react'
import { ApiError } from '../api/client'
import { platformSecurityApi } from '../api/platformSecurity'
import { authProvider, beginStepUpSignIn } from '../auth/authClient'
import { registerStepUpHandler, setStepUpGrant } from '../auth/stepUp'
import { Banner, Button, Field, Modal } from '../design/components'

interface Pending {
  resolve: () => void
  reject: (reason: Error) => void
}

export function StepUpHost(): JSX.Element | null {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needsCode, setNeedsCode] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef<Pending | null>(null)

  useEffect(
    () =>
      registerStepUpHandler(
        () =>
          new Promise<void>((resolve, reject) => {
            pending.current = { resolve, reject }
            setPassword('')
            setCode('')
            setNeedsCode(false)
            setError(null)
            setOpen(true)
          }),
      ),
    [],
  )

  function close(): void {
    setOpen(false)
    pending.current?.reject(new Error('Re-authentication cancelled'))
    pending.current = null
  }

  async function submit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const grant = await platformSecurityApi.stepUp({ password, ...(needsCode && code ? { mfa_code: code } : {}) })
      setStepUpGrant(grant.step_up_token, grant.expires_at)
      setOpen(false)
      pending.current?.resolve()
      pending.current = null
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === 'STEP_UP_MFA_REQUIRED') {
        setNeedsCode(true)
        setError(null)
      } else {
        // The server's own words: "Re-authentication failed. Check your password and code."
        setError(err instanceof ApiError ? err.detail : 'Could not confirm it is you.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null

  async function submitEntra(): Promise<void> {
    setError(null)
    // The window opens inside this click, before any await, so it is not blocked as a pop-up.
    const signedIn = beginStepUpSignIn()
    setSubmitting(true)
    try {
      const grant = await platformSecurityApi.stepUp({ id_token: await signedIn })
      setStepUpGrant(grant.step_up_token, grant.expires_at)
      setOpen(false)
      pending.current?.resolve()
      pending.current = null
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : err instanceof Error ? err.message : 'Could not confirm it is you.')
    } finally {
      setSubmitting(false)
    }
  }

  if (authProvider === 'entra') {
    return (
      <Modal open onClose={close} title="Confirm it's you" size="sm">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <p style={{ margin: 0, color: 'var(--color-ink-2)', fontSize: 'var(--text-sm)' }}>
            This action affects tenants or the whole platform. Sign in again with Microsoft in the window that opens;
            you won&apos;t be asked again for 5 minutes.
          </p>
          {error && <Banner variant="error">{error}</Banner>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
            <Button variant="ghost" onClick={close} disabled={submitting}>
              Cancel
            </Button>
            <Button variant="primary" loading={submitting} onClick={() => void submitEntra()}>
              Sign in again
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  const canSubmit = password.length > 0 && (!needsCode || /^\d{6}$/.test(code))

  return (
    <Modal open onClose={close} title="Confirm it's you" size="sm">
      <form
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit && !submitting) void submit()
        }}
      >
        <p style={{ margin: 0, color: 'var(--color-ink-2)', fontSize: 'var(--text-sm)' }}>
          This action affects tenants or the whole platform. Enter your password to continue; you won&apos;t be asked
          again for 5 minutes.
        </p>
        {error && <Banner variant="error">{error}</Banner>}
        <Field
          label="Password"
          name="step_up_password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {needsCode && (
          <Field
            label="Authenticator code"
            name="step_up_code"
            inputMode="numeric"
            autoComplete="one-time-code"
            helper="The 6-digit code from your authenticator app."
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            required
          />
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
          <Button variant="ghost" type="button" onClick={close} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" loading={submitting} disabled={!canSubmit}>
            Confirm
          </Button>
        </div>
      </form>
    </Modal>
  )
}
