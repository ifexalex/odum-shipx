import { useEffect, useRef, useState, type JSX } from 'react'
import { useSession } from '../auth/useSession'
import { Icon } from '../design/components'
import styles from './ImpersonationBanner.module.css'

function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const mm = String(Math.floor(totalSeconds / 60)).padStart(2, '0')
  const ss = String(totalSeconds % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

export function ImpersonationBanner(): JSX.Element | null {
  const { session, exitImpersonation } = useSession()
  const [remaining, setRemaining] = useState<number>(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!session?.readOnly) return

    function tick(): void {
      setRemaining(session!.expiresAt - Date.now())
    }

    tick()
    intervalRef.current = setInterval(tick, 1000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [session])

  // Auto-exit once the countdown reaches zero
  useEffect(() => {
    if (session?.readOnly && remaining <= 0 && intervalRef.current !== null) {
      exitImpersonation()
    }
  }, [remaining, session, exitImpersonation])

  if (!session?.readOnly) return null

  const displayName = session.tenantName ?? session.tenantId
  const startedBy = session.impersonatedBy ?? 'platform admin'

  return (
    <div className={styles.banner} role="alert" aria-live="polite">
      <span className={styles.pill}>
        <Icon name="eye" size={13} color="#fff" />
        Impersonating
      </span>
      <span className={styles.message}>
        Viewing <strong>{displayName}</strong> as Tenant Admin · <strong>read-only</strong>.
        All editing is disabled.{' '}
        <span className={styles.startedBy}>Started by {startedBy}</span>
      </span>
      <span className={styles.countdown}>
        <Icon name="clock" size={13} color="#fff" />
        Ends in {formatCountdown(remaining)}
      </span>
      <button type="button" className={styles.exitBtn} onClick={exitImpersonation}>
        <Icon name="logout" size={14} color="var(--color-accent-deep)" />
        Exit impersonation
      </button>
    </div>
  )
}
