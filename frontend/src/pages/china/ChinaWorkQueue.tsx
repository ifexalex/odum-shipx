/**
 * The China office's home page: the work waiting on them (audit UX-10).
 *
 * China staff used to land on the container list and hunt for work. Four queues, each read from an existing list
 * endpoint: packing lists Nigeria rejected (to revise and resubmit), drafts never submitted, manifests Nigeria has not
 * verified yet, and CBM disputes escalated to China. Each shows how many there are and the first few, and links to
 * its list already filtered (`?status=`, see `useStatusParam`).
 */
import { useContext, type JSX, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { PaginationMeta } from '../../api/client'
import { SessionContext } from '../../auth/SessionContext'
import { Banner, Button, Card, LinesSkeleton, StatCard } from '../../design/components'
import {
  CHINA_QUEUES,
  useChinaManifestQueue,
  useEscalatedDisputes,
  usePackingListQueue,
} from '../../hooks/useDashboard'
import { formatDate } from '../../lib/format'
import { StatRow } from '../../shell/ListPage'
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
        <div className={styles.queueHead}>
          <SectionHead
            title={title}
            sub={count === undefined ? undefined : countLabel(count)}
            action={
              <Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate(viewAll)}>
                View all
              </Button>
            }
          />
        </div>
        <div className={styles.queueBody}>{body}</div>
      </section>
    </Card>
  )
}

export function ChinaWorkQueue(): JSX.Element {
  const navigate = useNavigate()
  const session = useContext(SessionContext)?.session ?? null
  const pendingApproval = usePackingListQueue(CHINA_QUEUES.pendingApprovalPackingLists)
  const rejected = usePackingListQueue(CHINA_QUEUES.rejectedPackingLists)
  const drafts = usePackingListQueue(CHINA_QUEUES.draftPackingLists)
  const manifests = useChinaManifestQueue()
  const disputes = useEscalatedDisputes()

  const peerApprovalItems = (pendingApproval.data?.data ?? []).filter(
    (pl) => !session?.userId || pl.created_by !== session.userId,
  )

  const packingListRows = (items: NonNullable<typeof rejected.data>['data']): QueueRow[] =>
    items.map((pl) => ({
      id: pl.id,
      primary: pl.reference ?? 'Packing list',
      secondary: [pl.customer_name, pl.container_number, `updated ${formatDate(pl.updated_at)}`].filter(Boolean).join(' · '),
      to: `/packing-lists/${pl.id}`,
    }))

  const pendingCount =
    typeof pendingApproval.data?.meta.pagination.total_count === 'number'
      ? pendingApproval.data.meta.pagination.total_count
      : peerApprovalItems.length
  const rejectedCount = rejected.data?.meta.pagination.total_count ?? rejected.data?.data.length ?? 0
  const draftCount = drafts.data?.meta.pagination.total_count ?? drafts.data?.data.length ?? 0
  const disputeCount = disputes.data?.meta.pagination.total_count ?? disputes.data?.data.length ?? 0

  return (
    <>
      <PageHeader
        title="Work queue"
        meta="What is waiting on the China office."
        primary={
          <Button variant="primary" icon="plus" onClick={() => navigate('/packing-lists/new')}>
            Create packing list
          </Button>
        }
        actions={
          <>
            <Button variant="secondary" icon="upload" onClick={() => navigate('/packing-lists/import')}>
              Import Excel
            </Button>
            <Button variant="secondary" icon="container" onClick={() => navigate('/containers/new')}>
              Create container
            </Button>
          </>
        }
      />
      <div className={styles.stats}>
        <StatRow>
          <StatCard
            label="Pending approval"
            value={pendingCount}
            sublabel="peer review queue"
            icon="check"
            onSelect={() => navigate('/packing-lists?status=pending_approval')}
          />
          <StatCard
            label="Rejected lists"
            value={rejectedCount}
            sublabel="to revise & resubmit"
            icon="warn"
            onSelect={() => navigate('/packing-lists?status=rejected')}
          />
          <StatCard
            label="Drafts"
            value={draftCount}
            sublabel="not yet submitted"
            icon="file"
            onSelect={() => navigate('/packing-lists?status=draft')}
          />
          <StatCard
            label="Escalated disputes"
            value={disputeCount}
            sublabel="need measurement answer"
            icon="alert"
            onSelect={() => navigate('/billing/disputes?status=escalated_china')}
          />
        </StatRow>
      </div>
      <div className={styles.grid}>
        <Queue
          title="Packing lists to peer-approve"
          countLabel={(n) => `${n} waiting on another colleague`}
          empty="Nothing waiting for your approval."
          viewAll="/packing-lists?status=pending_approval"
          rows={packingListRows(peerApprovalItems)}
          pagination={
            pendingApproval.data
              ? {
                  ...pendingApproval.data.meta.pagination,
                  total_count:
                    peerApprovalItems.length === pendingApproval.data.data.length
                      ? pendingApproval.data.meta.pagination.total_count
                      : peerApprovalItems.length,
                }
              : undefined
          }
          loading={pendingApproval.isLoading}
          failed={pendingApproval.isError}
        />
        <Queue
          title="Rejected packing lists"
          countLabel={(n) => `${n} to revise and resubmit`}
          empty="Nothing rejected."
          viewAll="/packing-lists?status=rejected"
          rows={packingListRows(rejected.data?.data ?? [])}
          pagination={rejected.data?.meta.pagination}
          loading={rejected.isLoading}
          failed={rejected.isError}
        />
        <Queue
          title="Drafts not submitted"
          countLabel={(n) => `${n} not sent for approval`}
          empty="No drafts waiting."
          viewAll="/packing-lists?status=draft"
          rows={packingListRows(drafts.data?.data ?? [])}
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
