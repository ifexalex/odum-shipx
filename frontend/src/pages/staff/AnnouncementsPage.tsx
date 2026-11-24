import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, Field, StatusBadge, LinesSkeleton, ConfirmDialog, ErrorState } from '../../design/components'
import { formatDateTime } from '../../lib/format'
import { SectionHead } from '../../shell/SectionHead'
import { ComposeAnnouncementModal } from '../../shell/ComposeAnnouncementModal'
import type {
  AnnouncementAudience,
  AnnouncementHistoryEntry,
  AnnouncementRequest,
} from '../../api/announcements'
import {
  useActivateAnnouncement,
  useAnnouncementHistory,
  useAnnouncementPending,
  useApproveAnnouncement,
  useDeactivateAnnouncement,
  useDeleteAnnouncement,
  useDeleteAnnouncementRequest,
  useMyAnnouncementRequests,
  useRejectAnnouncement,
  useUpdateAnnouncement,
  useUpdateAnnouncementRequest,
} from '../../hooks/useAnnouncements'
import styles from './AnnouncementsPage.module.css'
import { PageHeader } from '../../shell/PageHeader'

function audienceLabel(audience: AnnouncementAudience): string {
  return audience === 'all_staff' ? 'All staff' : 'All customers'
}

function EditForm({
  initialTitle,
  initialBody,
  saving,
  onSave,
  onCancel,
}: {
  initialTitle: string
  initialBody: string | null
  saving: boolean
  onSave: (title: string, body: string | undefined) => void
  onCancel: () => void
}): JSX.Element {
  const [title, setTitle] = useState(initialTitle)
  const [body, setBody] = useState(initialBody ?? '')

  return (
    <div className={styles.editForm}>
      <Field label="Title" required value={title} onChange={(e) => setTitle(e.target.value)} />
      <Field
        label="Message"
        optional
        multiline
        rows={2}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <div className={styles.rowActions}>
        <Button size="sm" variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          loading={saving}
          disabled={!title.trim()}
          onClick={() => onSave(title.trim(), body.trim() || undefined)}
        >
          Save
        </Button>
      </div>
    </div>
  )
}

function mutationError(err: unknown): string | null {
  if (!err) return null
  return err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'
}

// tenant_admin: one row per staff-submitted customer request awaiting review.
function PendingRow({ req }: { req: AnnouncementRequest }): JSX.Element {
  const approve = useApproveAnnouncement()
  const reject = useRejectAnnouncement()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const rowErr = mutationError(approve.error ?? reject.error)

  return (
    <div className={styles.row}>
      <div className={styles.rowHeader}>
        <span className={styles.rowTitle}>{req.title}</span>
        <Badge variant="warning" size="sm" dot={false}>
          {audienceLabel(req.audience)}
        </Badge>
      </div>
      <div className={styles.rowMeta}>
        Submitted {formatDateTime(req.created_at)}
      </div>
      {req.body && <p className={styles.rowBody}>{req.body}</p>}
      {rowErr && <Banner variant="error">{rowErr}</Banner>}
      {!rejecting ? (
        <div className={styles.rowActions}>
          <Button
            size="sm"
            variant="primary"
            onClick={() => approve.mutate(req.id)}
            loading={approve.isPending}
          >
            Approve
          </Button>
          <Button
            size="sm"
            variant="danger-ghost"
            onClick={() => setRejecting(true)}
            disabled={approve.isPending}
          >
            Reject
          </Button>
        </div>
      ) : (
        <div className={styles.editForm}>
          <Field
            label="Reason"
            optional
            multiline
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why is this being rejected?"
          />
          <div className={styles.rowActions}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setRejecting(false)}
              disabled={reject.isPending}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() =>
                reject.mutate({
                  requestId: req.id,
                  reason: reason.trim() || undefined,
                })
              }
              loading={reject.isPending}
            >
              Confirm reject
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// tenant_admin: one row per sent announcement — banner toggle, edit, delete.
function HistoryRow({ entry }: { entry: AnnouncementHistoryEntry }): JSX.Element {
  const activate = useActivateAnnouncement()
  const deactivate = useDeactivateAnnouncement()
  const update = useUpdateAnnouncement()
  const remove = useDeleteAnnouncement()
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const togglePending = activate.isPending || deactivate.isPending
  const rowErr = mutationError(activate.error ?? deactivate.error ?? update.error ?? remove.error)

  if (editing) {
    return (
      <div className={styles.row}>
        {rowErr && <Banner variant="error">{rowErr}</Banner>}
        <EditForm
          initialTitle={entry.title}
          initialBody={entry.body}
          saving={update.isPending}
          onCancel={() => setEditing(false)}
          onSave={(title, body) =>
            update.mutate(
              { groupId: entry.announcement_group_id, input: { title, body } },
              { onSuccess: () => setEditing(false) },
            )
          }
        />
      </div>
    )
  }

  return (
    <div className={styles.row}>
      <div className={styles.rowHeader}>
        <span className={styles.rowTitle}>{entry.title}</span>
        <Badge variant={entry.banner_active ? 'success' : 'neutral'} size="sm" dot={false}>
          {entry.banner_active ? 'Published' : 'Draft'}
        </Badge>
        <Badge variant="neutral" size="sm" dot={false}>
          {audienceLabel(entry.audience)}
        </Badge>
      </div>
      <div className={styles.rowMeta}>
        Sent {formatDateTime(entry.created_at)}
      </div>
      {entry.body && <p className={styles.rowBody}>{entry.body}</p>}
      {rowErr && <Banner variant="error">{rowErr}</Banner>}
      <div className={styles.rowControls}>
        {entry.banner_active ? (
          <Button
            size="sm"
            variant="secondary"
            loading={deactivate.isPending}
            onClick={() => deactivate.mutate(entry.announcement_group_id)}
          >
            Unpublish
          </Button>
        ) : (
          <Button
            size="sm"
            variant="primary"
            loading={activate.isPending}
            onClick={() => activate.mutate(entry.announcement_group_id)}
          >
            Publish
          </Button>
        )}
        <div className={styles.rowActions}>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setEditing(true)}
            disabled={togglePending}
          >
            Edit
          </Button>
          {!confirmingDelete ? (
            <Button
              size="sm"
              variant="danger-ghost"
              onClick={() => setConfirmingDelete(true)}
              disabled={togglePending}
            >
              Delete
            </Button>
          ) : (
            <>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirmingDelete(false)}
                disabled={remove.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="danger"
                loading={remove.isPending}
                onClick={() => remove.mutate(entry.announcement_group_id)}
              >
                Confirm delete
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// nigeria_office_staff: one row per own submission, any status.
function MyRequestRow({ req }: { req: AnnouncementRequest }): JSX.Element {
  const update = useUpdateAnnouncementRequest()
  const remove = useDeleteAnnouncementRequest()
  const [editing, setEditing] = useState(false)
  const [confirmWithdraw, setConfirmWithdraw] = useState(false)
  const rowErr = mutationError(update.error ?? remove.error)

  return (
    <div className={styles.row}>
      <ConfirmDialog
        open={confirmWithdraw}
        title={`Withdraw "${req.title}"?`}
        confirmLabel="Withdraw announcement"
        undo="You can submit it again later."
        busy={remove.isPending}
        onConfirm={() => remove.mutate(req.id, { onSettled: () => setConfirmWithdraw(false) })}
        onCancel={() => setConfirmWithdraw(false)}
      >
        It will be taken out of the admin's review queue and will not be sent.
      </ConfirmDialog>
      <div className={styles.rowHeader}>
        <span className={styles.rowTitle}>{req.title}</span>
        <StatusBadge size="sm" kind="announcement" status={req.status} />
      </div>
      <div className={styles.rowMeta}>
        Submitted {formatDateTime(req.created_at)}
        {req.reviewed_at ? ` · Reviewed ${formatDateTime(req.reviewed_at)}` : ''}
      </div>
      {req.body && <p className={styles.rowBody}>{req.body}</p>}
      {rowErr && <Banner variant="error">{rowErr}</Banner>}
      {req.status === 'rejected' && req.rejection_reason && (
        <p className={styles.rejectionReason}>Reason: {req.rejection_reason}</p>
      )}
      {req.status === 'pending' && editing && (
        <EditForm
          initialTitle={req.title}
          initialBody={req.body}
          saving={update.isPending}
          onCancel={() => setEditing(false)}
          onSave={(title, body) =>
            update.mutate(
              { requestId: req.id, input: { title, body } },
              { onSuccess: () => setEditing(false) },
            )
          }
        />
      )}
      {req.status === 'pending' && !editing && (
        <div className={styles.rowActions}>
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button
            size="sm"
            variant="danger-ghost"
            loading={remove.isPending}
            onClick={() => setConfirmWithdraw(true)}
          >
            Withdraw
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * Dedicated page for composing and managing announcements — moved off the
 * notification bell popup at the user's explicit request: "no, i wan the
 * annoucement management to be on it's own page, not on the notification
 * popup." tenant_admin sends to either audience immediately and can
 * enable/disable/edit/delete anything ever sent ("Annoucement is managed in
 * that page (CRUD), and they can enable only one announcement to be visible
 * per time... for admin they can toggle staffs and customers. no approval is
 * required for them to publish it"). nigeria_office_staff can only target
 * customers, and every submission is held for tenant_admin approval before
 * it can reach anyone ("For staff they can only sent to customers, but it
 * must be approved by the admin before it can become visible to the
 * customer").
 */
export function AnnouncementsPage(): JSX.Element {
  const { session } = useSession()
  const isAdmin = session?.role === 'tenant_admin'
  const [composeOpen, setComposeOpen] = useState(false)

  const pendingQuery = useAnnouncementPending(isAdmin)
  const historyQuery = useAnnouncementHistory(isAdmin)
  const mineQuery = useMyAnnouncementRequests(!isAdmin)

  const pending = pendingQuery.data?.data ?? []
  const history = historyQuery.data ?? []
  const mine = mineQuery.data ?? []

  return (
    <div>
      <PageHeader
        title="Announcements"
        meta={
          isAdmin
            ? 'Broadcast to every staff member or every customer — only one banner shows per audience at a time.'
            : 'Submit an announcement for customers. A tenant admin reviews it before it reaches anyone.'
        }
        primary={
          <Button variant="primary" icon="plus" onClick={() => setComposeOpen(true)}>
            New announcement
          </Button>
        }
      />
      {isAdmin ? (
        <>
          <Card padding="default" style={{ marginBottom: 'var(--space-4)' }}>
            <SectionHead
              title="Pending approval"
              sub="Customer announcements submitted by staff."
            />
            {pendingQuery.isLoading && <LinesSkeleton label="Loading" />}
            {pendingQuery.error && (
              <ErrorState compact title="Couldn't load announcements awaiting approval" error={pendingQuery.error} onRetry={() => void pendingQuery.refetch()} />
            )}
            {!pendingQuery.isLoading && !pendingQuery.error && pending.length === 0 && (
              <div className={styles.empty}>No customer announcements awaiting approval.</div>
            )}
            {pending.map((req) => (
              <PendingRow key={req.id} req={req} />
            ))}
          </Card>

          <Card padding="default">
            <SectionHead
              title="All announcements"
              sub="Toggle which one is visible as a page banner."
            />
            {historyQuery.isLoading && <LinesSkeleton label="Loading" />}
            {historyQuery.error && (
              <ErrorState compact title="Couldn't load announcements" error={historyQuery.error} onRetry={() => void historyQuery.refetch()} />
            )}
            {!historyQuery.isLoading && !historyQuery.error && history.length === 0 && (
              <div className={styles.empty}>No announcements sent yet.</div>
            )}
            {history.map((entry) => (
              <HistoryRow key={entry.announcement_group_id} entry={entry} />
            ))}
          </Card>
        </>
      ) : (
        <Card padding="default">
          <SectionHead title="My announcements" />
          {mineQuery.isLoading && <LinesSkeleton label="Loading" />}
          {mineQuery.error && (
            <ErrorState compact title="Couldn't load your announcements" error={mineQuery.error} onRetry={() => void mineQuery.refetch()} />
          )}
          {!mineQuery.isLoading && !mineQuery.error && mine.length === 0 && (
            <div className={styles.empty}>You haven't submitted any announcements yet.</div>
          )}
          {mine.map((req) => (
            <MyRequestRow key={req.id} req={req} />
          ))}
        </Card>
      )}

      <ComposeAnnouncementModal open={composeOpen} onClose={() => setComposeOpen(false)} />
    </div>
  )
}
