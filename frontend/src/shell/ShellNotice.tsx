/**
 * The one notice at the top of the content column (FD-16). When several apply, only the first shows, in this order:
 * impersonation (shown above the whole app by `ImpersonationBanner`, so nothing here), tenant blocked (a full-page
 * gate, `TenantBlockedGate`), the active announcement, then the plan-limit notice (tenant admin only). Dismissing the
 * announcement lets the next one in line show.
 */
import { useState, type JSX } from 'react'
import { useSession } from '../auth/useSession'
import { AnnouncementBanner, type AnnouncementBannerData } from './AnnouncementBanner'
import { QuotaWarningBanner, useQuotaNotice } from './QuotaWarningBanner'

export function ShellNotice({ announcement }: { announcement: AnnouncementBannerData | null | undefined }): JSX.Element | null {
  const { session } = useSession()
  const quotaNotice = useQuotaNotice()
  const [dismissedAnnouncement, setDismissedAnnouncement] = useState<string | null>(null)

  if (!session || session.readOnly) return null
  if (announcement && announcement.id !== dismissedAnnouncement) {
    return <AnnouncementBanner banner={announcement} onDismiss={setDismissedAnnouncement} />
  }
  if (quotaNotice && session.role === 'tenant_admin') return <QuotaWarningBanner notice={quotaNotice} />
  return null
}
