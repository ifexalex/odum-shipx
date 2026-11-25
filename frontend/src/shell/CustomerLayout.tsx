import { ContentErrorBoundary, QuietBoundary } from './ErrorBoundary'
import { useState, type JSX, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { PoweredByShipx, TenantBrand } from '../design/components'
import { ThemeProvider } from '../design/ThemeProvider'
import { useBranding } from '../hooks/useConfig'
import { useCustomerBanner, useCustomerNotifUnreadCount } from '../hooks/useCustomerNotifications'
import { ShellNotice } from './ShellNotice'
import { Breadcrumb } from './Breadcrumb'
import { BreadcrumbContext, breadcrumbTrail, useBreadcrumbLabelState } from './breadcrumbs'
import { useDocumentTitle } from './documentTitle'
import { CustomerNotificationPanel } from './CustomerNotificationPanel'
import { CustShell } from './CustShell'
import { CustomerTopNav } from './CustomerTopNav'
import { GlobalSearch } from './GlobalSearch'
import { ImpersonationBanner } from './ImpersonationBanner'
import { navConfig } from './navConfig'
import { searchPlaceholderFor } from './searchRoutes'
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
  const { branding } = useBranding(!!session)
  // Ground-truth gap found live, reported by the user: they rejected a
  // payment claim and, checking as the customer, "did not see the
  // notification when I logged in" — this bell existed in the markup but
  // was never fed any data at all, the same gap the staff bell had before
  // it was fixed (see StaffLayout.tsx / 15_api_notifications.md).
  const { data: unreadData } = useCustomerNotifUnreadCount(!!session)
  const { data: banner } = useCustomerBanner(!!session)
  const breadcrumbLabels = useBreadcrumbLabelState()
  const { pathname } = useLocation()
  useDocumentTitle(session?.roles ?? [], breadcrumbLabels.labels)
  if (!session) return null
  const trail = breadcrumbTrail(pathname, session.roles, breadcrumbLabels.labels)

  const links = navConfig.customer.flatMap((group) => group.items)
  const tenantName = branding?.display_name?.trim()

  return (
    <ThemeProvider primaryColor={branding?.primary_color ?? null} style={{ height: '100%' }}>
      <TenantBlockedGate>
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <ImpersonationBanner />
          <CustShell
            topnav={
              <CustomerTopNav
                links={links}
                brand={
                  tenantName ? (
                    <TenantBrand
                      name={tenantName}
                      logoUrl={branding?.logo_url}
                      color={branding?.primary_color}
                      surface="dark"
                    />
                  ) : undefined
                }
                drawerBrand={
                  tenantName ? (
                    <TenantBrand
                      name={tenantName}
                      logoUrl={branding?.logo_url}
                      color={branding?.primary_color}
                      surface="light"
                    />
                  ) : undefined
                }
                drawerFooter={tenantName ? <PoweredByShipx surface="light" /> : undefined}
                onLogout={logout}
                search={<GlobalSearch audience="customer" placeholder={searchPlaceholderFor('customer') ?? 'Search…'} />}
                notifications={unreadData?.unread_count ?? 0}
                onNotificationsClick={() => setNotifPanelOpen((o) => !o)}
                notificationsPanel={
                  <CustomerNotificationPanel open={notifPanelOpen} onClose={() => setNotifPanelOpen(false)} />
                }
              />
            }
            footer={tenantName ? <PoweredByShipx surface="light" /> : undefined}
          >
            <BreadcrumbContext.Provider value={breadcrumbLabels}>
              <QuietBoundary>
                <ShellNotice announcement={banner} />
              </QuietBoundary>
              <Breadcrumb trail={trail} />
              <ContentErrorBoundary>{children}</ContentErrorBoundary>
            </BreadcrumbContext.Provider>
          </CustShell>
        </div>
      </TenantBlockedGate>
    </ThemeProvider>
  )
}
