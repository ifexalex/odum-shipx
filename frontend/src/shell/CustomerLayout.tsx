import { ContentErrorBoundary, QuietBoundary } from './ErrorBoundary'
import { useState, type JSX, type ReactNode } from 'react'
import { useSession } from '../auth/useSession'
import { useCustomerBanner, useCustomerNotifUnreadCount } from '../hooks/useCustomerNotifications'
import { AnnouncementBanner } from './AnnouncementBanner'
import { CustomerNotificationPanel } from './CustomerNotificationPanel'
import { CustShell } from './CustShell'
import { CustomerTopNav } from './CustomerTopNav'
import { ImpersonationBanner } from './ImpersonationBanner'
import { navConfig } from './navConfig'
import { TenantBlockedGate } from './TenantBlockedScreen'

export interface CustomerLayoutProps {
  children: ReactNode
}

// Shell every customer-portal route (routeTable.ts layout: 'customer')
// renders inside. Customer's navConfig is a single flat group (no sidebar
// sections), so it flattens directly into CustomerTopNav's link list. Plain
// children-prop composition, same reasoning as StaffLayout.tsx.
export function CustomerLayout({ children }: CustomerLayoutProps): JSX.Element | null {
  const { session, logout } = useSession()
  const [notifPanelOpen, setNotifPanelOpen] = useState(false)
  // Ground-truth gap found live, reported by the user: they rejected a
  // payment claim and, checking as the customer, "did not see the
  // notification when I logged in" — this bell existed in the markup but
  // was never fed any data at all, the same gap the staff bell had before
  // it was fixed (see StaffLayout.tsx / 15_api_notifications.md).
  const { data: unreadData } = useCustomerNotifUnreadCount(!!session)
  const { data: banner } = useCustomerBanner(!!session)
  if (!session) return null

  const links = navConfig.customer.flatMap((group) => group.items)

  return (
    <TenantBlockedGate>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <ImpersonationBanner />
        <QuietBoundary>
          <AnnouncementBanner banner={banner} />
        </QuietBoundary>
        <CustShell
          topnav={
            <CustomerTopNav
              links={links}
              onLogout={logout}
              notifications={unreadData?.unread_count ?? 0}
              onNotificationsClick={() => setNotifPanelOpen((o) => !o)}
              notificationsPanel={
                <CustomerNotificationPanel open={notifPanelOpen} onClose={() => setNotifPanelOpen(false)} />
              }
            />
          }
        >
          <ContentErrorBoundary>{children}</ContentErrorBoundary>
        </CustShell>
      </div>
    </TenantBlockedGate>
  )
}
