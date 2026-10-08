/**
 * 16.12 — Tenant Offboarded / Suspended full-page state (audit gap A4,
 * prototype gapfix-screens-a.jsx OffboardedScreen).
 *
 * Rendered by StaffLayout/CustomerLayout in place of ALL routed content when
 * the API reports the tenant itself is gone (see auth/tenantGate.ts) — the
 * backend fails every request identically in this state (shared/auth.py,
 * fail-closed), so per-page error banners would just repeat on every screen.
 */
import type { JSX } from 'react'
import { useSession } from '../auth/useSession'
import { useTenantBlocked, type TenantBlockedKind } from '../auth/tenantGate'
import { Button, Icon, KolaMark } from '../design/components'
import styles from './TenantBlockedScreen.module.css'

const COPY: Record<TenantBlockedKind, { title: string; body: string; hint: string; code: string }> = {
  offboarded: {
    title: 'This account has been closed',
    body: 'Your company is no longer active on ShipX. Its data has been retained per the data-retention policy in case it needs to be exported.',
    hint: 'If you believe this is an error, contact ShipX support.',
    code: 'HTTP 410 · TENANT_OFFBOARDED',
  },
  suspended: {
    title: 'This account is suspended',
    body: "Your company's ShipX subscription is currently suspended, so access is paused for everyone on the account.",
    hint: 'Your administrator can contact ShipX support to restore access.',
    code: 'HTTP 403 · TENANT_SUSPENDED',
  },
}

export function TenantBlockedScreen({ kind }: { kind: TenantBlockedKind }): JSX.Element {
  const { logout } = useSession()
  const copy = COPY[kind]

  return (
    <div className={styles.page}>
      <div className={styles.panel}>
        <div className={styles.mark}>
          <KolaMark size={40} color="var(--color-primary-bright)" />
        </div>
        <div className={styles.iconCircle}>
          <Icon name="suspend" size={28} color="#fca5a5" />
        </div>
        <h1 className={styles.title}>{copy.title}</h1>
        <p className={styles.body}>{copy.body}</p>
        <p className={styles.hint}>{copy.hint}</p>
        <div className={styles.actions}>
          <a href="mailto:support@shipx.co" className={styles.mailLink}>
            <Button variant="accent" size="lg" icon="mail">
              Contact support
            </Button>
          </a>
          <Button variant="ghost" size="lg" icon="logout" onClick={logout} className={styles.signOut}>
            Sign out
          </Button>
        </div>
        <div className={styles.code}>{copy.code}</div>
      </div>
    </div>
  )
}

/**
 * Wraps a layout's routed content: renders the full-page blocked state when
 * the gate is tripped, the children otherwise.
 */
export function TenantBlockedGate({ children }: { children: React.ReactNode }): JSX.Element {
  const blocked = useTenantBlocked()
  if (blocked) return <TenantBlockedScreen kind={blocked} />
  return <>{children}</>
}
