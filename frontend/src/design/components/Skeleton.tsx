/**
 * Skeletons (FD-20): grey shapes in the place of what is loading, laid out like it, so nothing jumps when the data
 * arrives. Announced once as "Loading <what>" to screen readers; the shapes themselves are hidden from them.
 *
 *   if (isLoading) return <PageSkeleton kind="detail" label="Loading invoice" />
 *   {loading && <LinesSkeleton label="Loading templates" lines={4} />}
 */
import type { CSSProperties, JSX } from 'react'
import styles from './Skeleton.module.css'

export function Skeleton({ width = '100%', height = 14, style }: { width?: string | number; height?: number; style?: CSSProperties }): JSX.Element {
  return <span className={styles.block} style={{ width, height, ...style }} aria-hidden="true" />
}

/** A few lines of text still loading: a short paragraph, a list in a panel. */
export function LinesSkeleton({ label, lines = 3 }: { label: string; lines?: number }): JSX.Element {
  return (
    <div className={styles.lines} role="status" aria-label={label} aria-busy="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '60%' : '100%'} />
      ))}
    </div>
  )
}

/** A whole page still loading, shaped like the page it becomes. */
export function PageSkeleton({ kind, label }: { kind: 'detail' | 'list' | 'form'; label: string }): JSX.Element {
  return (
    <div className={styles.page} role="status" aria-label={label} aria-busy="true">
      <div className={styles.header}>
        <Skeleton width="38%" height={28} />
        <Skeleton width="22%" height={14} />
      </div>
      {kind === 'detail' && (
        <div className={styles.stats}>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className={styles.card}>
              <Skeleton width="50%" height={12} />
              <Skeleton width="70%" height={24} />
            </div>
          ))}
        </div>
      )}
      <div className={styles.card}>
        {Array.from({ length: kind === 'list' ? 8 : 5 }, (_, i) =>
          kind === 'form' ? (
            <div key={i} className={styles.field}>
              <Skeleton width="25%" height={12} />
              <Skeleton height={40} />
            </div>
          ) : (
            <div key={i} className={styles.row}>
              <Skeleton width="20%" />
              <Skeleton width="35%" />
              <Skeleton width="15%" />
            </div>
          ),
        )}
      </div>
    </div>
  )
}
