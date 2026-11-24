import type { JSX } from 'react'
import type { TenantQuota } from '../../api/tenantManagement'
import { Banner } from './Banner'
import { Button } from './Button'
import { Card } from './Card'
import { DialogGuard } from './Modal'

interface LimitReachedModalProps {
  /** Which resource was blocked — e.g. 'container', 'user'. */
  resource: string
  quota: TenantQuota
  onClose: () => void
}

/**
 * Hard-block modal shown when a creation action is prevented by a plan limit.
 *
 * Usage: render conditionally when `useQuota().atLimit` is true and the user
 * attempts to create a new resource (container, user, etc.).
 */
export function LimitReachedModal({ resource, quota, onClose }: LimitReachedModalProps): JSX.Element {
  const dimLabel =
    resource === 'user'
      ? `Users (${quota.limits.users.used}/${quota.limits.users.max})`
      : `Containers this month (${quota.limits.containers_per_month.used}/${quota.limits.containers_per_month.max})`

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'var(--scrim-modal)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 'var(--layer-modal)',
        padding: 'var(--space-4)',
      }}
      onClick={onClose}
    >
      <DialogGuard onClose={onClose} />
      {/* Interactive wrapper (Card is presentational-only, no event props) */}
      <div
        style={{ maxWidth: 440, width: '100%' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <Card padding="large" radius="xl">
          <h3 style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--text-lg)', fontWeight: 700 }}>Plan limit reached</h3>
          <Banner variant="error" title={`Cannot create ${resource}`}>
            {dimLabel} — your {quota.subscription_tier} plan limit is reached.
          </Banner>
          <p style={{ fontSize: 'var(--text-md)', color: 'var(--color-ink-3)', margin: 'var(--space-3) 0' }}>
            Upgrade your subscription or contact your platform administrator to increase the limit.
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button variant="primary" size="lg" onClick={onClose}>
              Close
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
