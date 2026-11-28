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
  const [now, setNow] = useState<number>(() => Date.now())
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!session?.readOnly) return

    const expiresAt = session.expiresAt
    let exited = false

    const handleTick = (): void => {
      const current = Date.now()
      setNow(current)
      if (current >= expiresAt && !exited) {
        exited = true
        if (intervalRef.current) {
          clearInterval(intervalRef.current)
          intervalRef.current = null
        }
        exitImpersonation()
      }
    }

    if (Date.now() >= expiresAt) {
      exited = true
      exitImpersonation()
      return
    }

    intervalRef.current = setInterval(handleTick, 1000)
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [session, exitImpersonation])

  if (!session?.readOnly) return null

  const displayName = session.tenantName ?? session.tenantId
  const startedBy = session.impersonatedBy ?? 'platform admin'
  const countdownMs = Math.max(0, session.expiresAt - now)

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
        Ends in {formatCountdown(countdownMs)}
      </span>
      <button type="button" className={styles.exitBtn} onClick={exitImpersonation}>
        <Icon name="logout" size={14} color="var(--color-accent-deep)" />
        Exit impersonation
      </button>
    </div>
  )
}
