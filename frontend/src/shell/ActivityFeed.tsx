/**
 * B6 — tenant activity feed (audit gap). Shared by the tenant dashboard
 * (§3.1) and the staff-profile activity table (§3.4). Reads GET
 * /v1/tenant/activity (admin-only, tenant-scoped audit log); pass `actorId`
 * to narrow to one staff member.
 */
import { useQuery } from '@tanstack/react-query'
import { type JSX } from 'react'
import { configApi, type TenantActivityEntry } from '../api/tenantManagement'
import { configKeys } from '../api/keys'
import { STALE_30S } from '../lib/queryClient'
import { Badge, type BadgeVariant, ErrorState, LinesSkeleton } from '../design/components'
import styles from './ActivityFeed.module.css'
import { formatDate } from '../lib/format'

const ACTION_VARIANT: Record<TenantActivityEntry['action'], BadgeVariant> = {
  CREATE: 'success',
  UPDATE: 'info',
  DELETE: 'error',
  STATUS_CHANGE: 'warning',
}

const ACTION_TONE: Record<BadgeVariant, string | undefined> = {
  success: styles.toneSuccess,
  info: styles.toneInfo,
  error: styles.toneError,
  warning: styles.toneWarning,
  accent: styles.toneWarning,
  purple: styles.toneInfo,
  neutral: styles.toneNeutral,
  primary: styles.toneSuccess,
}

function humanEntity(entityType: string): string {
  return entityType.replace(/_/g, ' ')
}

function relativeTime(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return formatDate(iso)
}

export function ActivityFeed({
  actorId,
  limit = 8,
  showActor = true,
}: {
  actorId?: string
  limit?: number
  /** Hide the actor name (redundant on the staff-profile, where it's always this user). */
  showActor?: boolean
}): JSX.Element {
  const { data, isPending, error, refetch } = useQuery({
    queryKey: configKeys.activity({ actorId, limit }),
    queryFn: () => configApi.activity({ actorId, limit }),
    staleTime: STALE_30S,
  })

  if (isPending) {
    return <LinesSkeleton label="Loading activity" lines={4} />
  }
  // A failed load says so, with a retry, inside the widget (FD-53): it used to read "No recent activity.", so a
  // broken feed looked like a quiet one. Still compact, so the page around it is unaffected.
  if (error) {
    return <ErrorState compact title="Couldn't load activity" error={error} onRetry={() => void refetch()} />
  }
  const entries: TenantActivityEntry[] = data?.data ?? []
  if (entries.length === 0) {
    return <div className={styles.empty}>No recent activity.</div>
  }

  return (
    <div className={styles.list}>
      {entries.map((e) => {
        const variant = ACTION_VARIANT[e.action] ?? 'neutral'
        return (
          <div key={e.id} className={[styles.row, ACTION_TONE[variant]].filter(Boolean).join(' ')}>
            <div className={styles.rail} aria-hidden="true">
              <span className={styles.node} />
              <span className={styles.line} />
            </div>
            <div className={styles.body}>
              <div className={styles.topLine}>
                <div className={styles.title}>{humanEntity(e.entity_type)}</div>
                <Badge variant={variant} size="sm" dot={false}>{e.action.replace(/_/g, ' ')}</Badge>
              </div>
              <div className={styles.meta}>
                {showActor && e.actor_name ? `by ${e.actor_name} · ` : ''}
                {relativeTime(e.created_at)}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
