import { useEffect, useState, type JSX } from 'react'
import { Button } from '../design/components/Button'
import { Modal } from '../design/components/Modal'

export interface SessionTimeoutModalProps {
  /** Epoch-ms at which the session is logged out if the user doesn't respond. */
  deadline: number
  /** "Stay signed in" — extend the session and dismiss. */
  onContinue: () => void
  /** "Sign out now" — end the session immediately. */
  onSignOut: () => void
}

function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`
}

/**
 * Session inactivity warning. Shown after the idle threshold; counts down to the
 * hard logout `deadline` and lets the user stay signed in. The authoritative
 * logout is driven by useIdleTimeout's own timer — this countdown is the visible
 * mirror of it, so the two can't disagree.
 */
export function SessionTimeoutModal({ deadline, onContinue, onSignOut }: SessionTimeoutModalProps): JSX.Element {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const remaining = deadline - now

  return (
    <Modal
      open
      title="Still there?"
      width={480}
      footer={
        <>
          <Button variant="ghost" onClick={onSignOut}>
            Sign out
          </Button>
          <Button variant="accent" onClick={onContinue}>
            Stay signed in
          </Button>
        </>
      }
    >
      <p>
        You&rsquo;ve been inactive for a while. For your security you&rsquo;ll be signed out in{' '}
        <strong>{formatRemaining(remaining)}</strong>.
      </p>
      <p>Choose &ldquo;Stay signed in&rdquo; to continue where you left off.</p>
    </Modal>
  )
}
