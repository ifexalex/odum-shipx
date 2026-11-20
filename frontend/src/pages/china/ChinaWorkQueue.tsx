/**
 * The China office's home page: the work waiting on them (audit UX-10).
 *
 * China staff used to land on the container list and hunt for work. Four queues, each read from an existing list
 * endpoint: packing lists Nigeria rejected (to revise and resubmit), drafts never submitted, manifests Nigeria has not
 * verified yet, and CBM disputes escalated to China. Each shows how many there are and the first few, and links to
 * its list already filtered (`?status=`, see `useStatusParam`).
 */
import type { JSX, ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { PaginationMeta } from '../../api/client'
import { Banner, Button, Card, LinesSkeleton } from '../../design/components'
import {
  CHINA_QUEUES,
  useChinaManifestQueue,
  useEscalatedDisputes,
  usePackingListQueue,
} from '../../hooks/useDashboard'
import { formatDate } from '../../lib/format'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ChinaWorkQueue.module.css'
import { PageHeader } from '../../shell/PageHeader'

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

interface QueueRow {
  id: string
  primary: string
  secondary: string
  to: string
}

interface QueueProps {
  title: string
  /** "{n} to revise" — what the count means for this queue. */
  countLabel: (count: string) => string
  empty: string
  viewAll: string
  rows: QueueRow[]
  /** The list response's pagination, for the count. */
  pagination: PaginationMeta | undefined
  loading: boolean
  failed: boolean
}

/**
 * How many are in the queue. `total_count` where the endpoint reports it (packing lists); the manifest and dispute
 * lists do not, so there it is the rows on this page, with "+" when the list goes on.
 */
function queueCount(pagination: PaginationMeta | undefined, shown: number): string | undefined {
  if (!pagination) return undefined
  if (typeof pagination.total_count === 'number') return String(pagination.total_count)
  return pagination.has_more ? `${shown}+` : String(shown)
}

function Queue({ title, countLabel, empty, viewAll, rows, pagination, loading, failed }: QueueProps): JSX.Element {
  const navigate = useNavigate()
  const count = queueCount(pagination, rows.length)
  let body: ReactNode
  if (failed) body = <Banner variant="error">This queue could not be loaded.</Banner>
  else if (loading) body = <LinesSkeleton label="Loading" lines={2} />
  else if (rows.length === 0) body = <p className={styles.muted}>{empty}</p>
  else
    body = (
      <ul className={styles.rows}>
        {rows.map((row) => (
          <li key={row.id}>
            <Link to={row.to} className={styles.row}>
              <span className={styles.primary}>{row.primary}</span>
              <span className={styles.secondary}>{row.secondary}</span>
            </Link>
          </li>
        ))}
      </ul>
    )

  return (
    <Card padding="none">
      <section className={styles.queue} aria-label={title}>
        <SectionHead
          title={title}
          sub={count === undefined ? undefined : countLabel(count)}
          action={
            <Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate(viewAll)}>
              View all
            </Button>
          }
        />
        {body}
      </section>
    </Card>
  )
}

export function ChinaWorkQueue(): JSX.Element {
  const rejected = usePackingListQueue(CHINA_QUEUES.rejectedPackingLists)
  const drafts = usePackingListQueue(CHINA_QUEUES.draftPackingLists)
  const manifests = useChinaManifestQueue()
  const disputes = useEscalatedDisputes()

  const packingListRows = (data: typeof rejected.data): QueueRow[] =>
    (data?.data ?? []).map((pl) => ({
      id: pl.id,
      primary: pl.reference ?? 'Packing list',
      secondary: [pl.customer_name, pl.container_number, `updated ${formatDate(pl.updated_at)}`].filter(Boolean).join(' · '),
      to: `/packing-lists/${pl.id}`,
    }))

  return (
    <>
      <PageHeader title="Work queue" meta="What is waiting on the China office." />
      <div className={styles.grid}>
        <Queue
          title="Rejected packing lists"
          countLabel={(n) => `${n} to revise and resubmit`}
          empty="Nothing rejected."
          viewAll="/packing-lists?status=rejected"
          rows={packingListRows(rejected.data)}
          pagination={rejected.data?.meta.pagination}
          loading={rejected.isLoading}
          failed={rejected.isError}
        />
        <Queue
          title="Drafts not submitted"
          countLabel={(n) => `${n} not sent for approval`}
          empty="No drafts waiting."
          viewAll="/packing-lists?status=draft"
          rows={packingListRows(drafts.data)}
          pagination={drafts.data?.meta.pagination}
          loading={drafts.isLoading}
          failed={drafts.isError}
        />
        <Queue
          title="Manifests awaiting verification"
          countLabel={(n) => `${n} not yet verified in Nigeria`}
          empty="Every manifest is verified."
          viewAll="/manifests?status=pending"
          rows={(manifests.data?.data ?? []).map((m) => ({
            id: m.id,
            primary: m.container_number ?? 'Container',
            secondary: `${plural(m.total_customers, 'customer')} · ${plural(m.total_cartons, 'carton')}`,
            to: `/manifests/${m.id}`,
          }))}
          pagination={manifests.data?.meta.pagination}
          loading={manifests.isLoading}
          failed={manifests.isError}
        />
        <Queue
          title="Disputes escalated to China"
          countLabel={(n) => `${n} need a measurement answer`}
          empty="No disputes escalated."
          viewAll="/billing/disputes?status=escalated_china"
          rows={(disputes.data?.data ?? []).map((d) => ({
            id: d.id,
            primary: d.container_number ?? 'CBM dispute',
            secondary: [d.customer_name, `filed ${formatDate(d.submitted_at)}`].filter(Boolean).join(' · '),
            to: `/billing/disputes/${d.id}`,
          }))}
          pagination={disputes.data?.meta.pagination}
          loading={disputes.isLoading}
          failed={disputes.isError}
        />
      </div>
    </>
  )
}
