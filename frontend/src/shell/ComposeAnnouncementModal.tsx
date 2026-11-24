import { useState, type JSX } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useSession } from '../auth/useSession'
import { Banner, Button, Chip, Field, Modal } from '../design/components'
import { announcementsApi, type AnnouncementAudience } from '../api/announcements'
import { announcementKeys, customerNotifKeys, staffNotifKeys } from '../api/keys'
import { toast } from '../design/toast'

export interface ComposeAnnouncementModalProps {
  open: boolean
  onClose: () => void
}

/**
 * tenant_admin / nigeria_office_staff compose a one-off broadcast — e.g. a
 * holiday-hours notice during a celebration, or an import-maintenance
 * window — delivered via the same in-app bell (and, once active, a page
 * banner) as every system-triggered notification. Direct user request:
 * "tenant admin and nigeria staff should be able to send announcements."
 *
 * Follow-up restricting staff: "the staff can only send to customers, which
 * should be approved by the tenant admins, this is to ensure that a
 * compromised staff does not misinformation the customers." A
 * nigeria_office_staff session never even sees the "All staff" choice (the
 * backend 403s it outright, not just requires approval), and their submit
 * goes into the tenant_admin review queue rather than sending immediately —
 * reflected here by locking the audience and relabeling the button.
 */
export function ComposeAnnouncementModal({ open, onClose }: ComposeAnnouncementModalProps): JSX.Element {
  const { session } = useSession()
  const isStaffRequest = session?.role === 'nigeria_office_staff'

  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [audience, setAudience] = useState<AnnouncementAudience>(isStaffRequest ? 'all_customers' : 'all_staff')
  const qc = useQueryClient()

  const send = useMutation({
    mutationFn: () => announcementsApi.send({ title: title.trim(), body: body.trim() || undefined, audience }),
    onSuccess: (result) => {
      toast.success(result.status === 'pending' ? 'Announcement sent for approval' : 'Announcement sent', title.trim())
      // The sender is themself a staff member — their own bell should pick
      // up an "all_staff" announcement immediately, same as anyone else's.
      // A staff submission doesn't create a notification yet (it's pending
      // approval), but invalidating is harmless either way.
      void qc.invalidateQueries({ queryKey: staffNotifKeys.all })
      void qc.invalidateQueries({ queryKey: customerNotifKeys.all })
      void qc.invalidateQueries({ queryKey: announcementKeys.all })
      setTitle('')
      setBody('')
      setAudience(isStaffRequest ? 'all_customers' : 'all_staff')
      onClose()
    },
  })

  function handleClose(): void {
    send.reset()
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="New announcement" size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {send.isError && (
          <Banner variant="error" title="Couldn't send announcement">
            {send.error instanceof Error ? send.error.message : 'Something went wrong.'}
          </Banner>
        )}
        <Field
          label="Title"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Office closed for the holidays"
        />
        <Field
          label="Message"
          optional
          multiline
          rows={3}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Optional details…"
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--color-ink-2)' }}>Send to</span>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            {!isStaffRequest && (
              <Chip active={audience === 'all_staff'} onClick={() => setAudience('all_staff')}>
                All staff
              </Chip>
            )}
            <Chip active={audience === 'all_customers'} onClick={() => setAudience('all_customers')}>
              All customers
            </Chip>
          </div>
          {isStaffRequest && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>
              Customer announcements need tenant admin approval before they're sent.
            </span>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)', marginTop: 'var(--space-1)' }}>
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => send.mutate()}
            loading={send.isPending}
            disabled={!title.trim()}
          >
            {isStaffRequest ? 'Submit announcement' : 'Send announcement'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
