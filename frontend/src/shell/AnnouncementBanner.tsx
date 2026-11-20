import { useState, type JSX } from 'react'
import { Banner } from '../design/components'
import styles from './AnnouncementBanner.module.css'

export interface AnnouncementBannerData {
  id: string
  title: string
  body: string | null
}

export interface AnnouncementBannerProps {
  banner: AnnouncementBannerData | null | undefined
  /** Told when the user dismisses it, so the shell can show the next notice in line (FD-16). */
  onDismiss?: (id: string) => void
}

/**
 * Shell-level banner for the single currently-active announcement — shown
 * above the routed content on every page, not just in the notification
 * bell, so the target audience "won't miss it." Direct user request, sent
 * mid-review of the announcement-approval feature: "annoucement should be a
 * banner on the target user's web page... we can add amination to it, so
 * that it is obvious to the target user."
 *
 * Mounted once each in StaffLayout and CustomerLayout (same slot as
 * ImpersonationBanner/QuotaWarningBanner), backed by useStaffBanner /
 * useCustomerBanner — both poll GET /v1/notifications/{staff,customer}/banner,
 * which the backend guarantees returns at most one row at a time per
 * audience ("more can be created but only one can be visible per time").
 *
 * Dismissing only hides it for this browser tab's session — closing it
 * doesn't touch the backend, so a reload (or another device/tab) still
 * shows it until a tenant_admin actually deactivates it. Re-showing on a
 * genuinely new banner falls out of comparing ids at render time: a
 * different id (a new send, or an admin re-activating a different past one)
 * never equals the dismissed id, so it renders regardless of what was
 * dismissed before.
 *
 * Uses the design system's `warning` Banner variant (amber, from the
 * existing --color-warning palette) rather than the neutral `info` blue —
 * direct user request: "the banner should have a colour that draws
 * attention too. look at the color pallet." Amber is this codebase's
 * established "pay attention" language (QuotaWarningBanner uses the same
 * variant), distinct from success/error so it never reads as good or bad
 * news, just "read this."
 */
export function AnnouncementBanner({ banner, onDismiss }: AnnouncementBannerProps): JSX.Element | null {
  const [dismissedId, setDismissedId] = useState<string | null>(null)

  if (!banner || banner.id === dismissedId) return null

  return (
    <div className={styles.wrap} key={banner.id}>
      <Banner
        variant="warning"
        icon="bell"
        title={banner.title}
        dismissible
        onDismiss={() => {
          setDismissedId(banner.id)
          onDismiss?.(banner.id)
        }}
      >
        {banner.body}
      </Banner>
    </div>
  )
}
