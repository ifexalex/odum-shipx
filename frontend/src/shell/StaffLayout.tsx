import { ContentErrorBoundary, QuietBoundary } from './ErrorBoundary'
import { useEffect, useState, type JSX, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { homePathForRole } from '../auth/roleHome'
import type { UserRole } from '../auth/types'
import { ThemeProvider } from '../design/ThemeProvider'
import { useBranding } from '../hooks/useConfig'
import { AnnouncementBanner } from './AnnouncementBanner'
import { AppSidebar } from './AppSidebar'
import { ImpersonationBanner } from './ImpersonationBanner'
import { useStaffBanner, useStaffNotifUnreadCount } from '../hooks/useStaffNotifications'
import { roleForPath, visualRoleFor } from './navConfig'
import { PageShell } from './PageShell'
import { QuotaWarningBanner } from './QuotaWarningBanner'
import { StaffNotificationPanel } from './StaffNotificationPanel'
import { TenantBlockedGate } from './TenantBlockedScreen'
import { GlobalSearch } from './GlobalSearch'
import { searchPlaceholderFor } from './searchRoutes'
import { TopBar } from './TopBar'
import { Breadcrumb } from './Breadcrumb'
import { BreadcrumbContext, breadcrumbTrail, useBreadcrumbLabelState } from './breadcrumbs'

export interface StaffLayoutProps {
  children: ReactNode
}

// Human-readable role labels shown under the user's name in TopBar + Sidebar.
const ROLE_DISPLAY: Record<UserRole, string> = {
  platform_admin: 'Platform Admin',
  tenant_admin: 'Admin',
  china_office_staff: 'China Office Staff',
  nigeria_office_staff: 'Nigeria Office Staff',
  warehouse_attendant: 'Warehouse Attendant',
  customer: 'Customer',
}

export function StaffLayout({ children }: StaffLayoutProps): JSX.Element | null {
  const { session, setActiveRole } = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const breadcrumbLabels = useBreadcrumbLabelState()
  const [notifPanelOpen, setNotifPanelOpen] = useState(false)

  // Tenant theme (4.1 branding_config.primary_color). Platform admins keep the
  // canonical palette — their tenant is "PLATFORM" and /v1/tenant/* would 403
  // for them anyway — but while impersonating, the JWT is tenant-scoped, so
  // they correctly see the impersonated tenant's brand. Hook order: must run
  // before the `if (!session)` early return.
  const isPlatformShell = session?.role === 'platform_admin'
  const { branding } = useBranding(!!session && !isPlatformShell)

  // Staff notification bell — same "not for a bare platform admin, real
  // tenant context only" gate as branding above. GET /v1/notifications/staff
  // 403s for platform_admin anyway (see services/notification/handler.py's
  // _STAFF_NOTIF_ROLES), same reasoning as the branding endpoint.
  const { data: unreadData } = useStaffNotifUnreadCount(!!session && !isPlatformShell)
  const unreadCount = unreadData?.unread_count ?? 0

  // Same gate as the bell above — GET /v1/notifications/staff/banner 403s
  // for platform_admin (no real tenant context).
  const { data: banner } = useStaffBanner(!!session && !isPlatformShell)

  // Ground-truth fix (2026-07-20): the active role is UI-only state, never
  // persisted (no localStorage/sessionStorage in src/auth/ — see
  // 11_security_and_compliance.md), so a reload rebuilds `session.role` from
  // the JWT's primary role while the URL still points at whatever page was
  // open — e.g. switch to Warehouse, reload, and the selector snaps back to
  // Nigeria Office Staff while the page is still /warehouse. Keep the
  // selector honest by re-deriving the active role from the current path
  // whenever they disagree, instead of trying to persist a choice that can
  // drift from reality (direct links, browser back/forward, bookmarks).
  useEffect(() => {
    if (!session) return
    const owner = roleForPath(location.pathname, session.roles, session.role)
    if (owner && owner !== session.role) setActiveRole(owner)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, session?.role, session?.roles])

  if (!session) return null

  // Null for a platform admin: the server refuses them (a tenant-scoped lookup, and they span tenants).
  const searchPlaceholder = searchPlaceholderFor(session.role)
  // Where the page lives (FD-45/46): its parent routes, then itself, named by the page's record once loaded. Rendered
  // above the page's content so it is there while the page loads; the page's own PageHeader follows it (FD-14).
  const breadcrumb = breadcrumbTrail(location.pathname, session.roles, breadcrumbLabels.labels)

  // Always show a user identity in the TopBar / Sidebar — fall back to the role
  // label when the JWT `name` claim is absent (e.g. older tokens or missing attribute).
  const shellUser = {
    name: session.name ?? ROLE_DISPLAY[session.role],
    role: ROLE_DISPLAY[session.role],
  }

  // Role-switch control (TopBar user menu) — only meaningful for a multi-role
  // user; single-role sessions pass a 1-item list, which TopBar treats as "no
  // switch to show." Purely client-side — see SessionContext.setActiveRole.
  const roleOptions = session.roles.map((r) => ({ value: r, label: ROLE_DISPLAY[r] }))

  return (
    <BreadcrumbContext.Provider value={breadcrumbLabels}>
      <ThemeProvider primaryColor={isPlatformShell ? null : (branding?.primary_color ?? null)} style={{ height: '100%' }}>
        <TenantBlockedGate>
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <ImpersonationBanner />
          <QuietBoundary>
            <AnnouncementBanner banner={banner} />
          </QuietBoundary>
          <QuietBoundary>
            <QuotaWarningBanner />
          </QuietBoundary>
          <PageShell
            sidebar={<AppSidebar user={shellUser} />}
            topbar={
              <TopBar
                role={visualRoleFor(session.role)}
                user={shellUser}
                search={searchPlaceholder === null ? undefined : <GlobalSearch audience="staff" placeholder={searchPlaceholder} />}
                notifications={isPlatformShell ? undefined : unreadCount}
                onNotificationsClick={isPlatformShell ? undefined : () => setNotifPanelOpen((o) => !o)}
                notificationsPanel={
                  isPlatformShell ? undefined : (
                    <StaffNotificationPanel open={notifPanelOpen} onClose={() => setNotifPanelOpen(false)} />
                  )
                }
                onUserMenuClick={() => navigate('/profile')}
                roleOptions={roleOptions}
                activeRole={session.role}
                onRoleChange={(role) => {
                  const nextRole = role as UserRole
                  setActiveRole(nextRole)
                  // Switching the active role changes which navConfig/route-guard
                  // tree applies, but the current URL doesn't change on its own —
                  // without this, the page stays mounted at the old role's route
                  // (which may not even be in the new role's nav) until the user
                  // manually clicks a nav link. Land them somewhere sane instead.
                  navigate(homePathForRole(nextRole))
                }}
              />
            }
          >
            <Breadcrumb trail={breadcrumb} />
            <ContentErrorBoundary>{children}</ContentErrorBoundary>
          </PageShell>
        </div>
        </TenantBlockedGate>
      </ThemeProvider>
    </BreadcrumbContext.Provider>
  )
}
