import type { JSX } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { RoleGuard } from '../auth/RoleGuard'
import { SessionLoading } from '../auth/SessionLoading'
import { useSession } from '../auth/useSession'
import { ForgotPasswordScreen } from '../pages/auth/ForgotPasswordScreen'
import { ActivateScreen } from '../pages/auth/ActivateScreen'
import { InviteClaimScreen } from '../pages/auth/InviteClaimScreen'
import { LoginScreen } from '../pages/auth/LoginScreen'
import { RegisterScreen } from '../pages/auth/RegisterScreen'
import { RequestOnboardingScreen } from '../pages/auth/RequestOnboardingScreen'
import { AuthCallback } from '../pages/auth/AuthCallback'
import { ResetPasswordScreen } from '../pages/auth/ResetPasswordScreen'
import { LandingPage } from '../pages/marketing/LandingPage'
import { ContainerDetail } from '../pages/china/ContainerDetail'
import { ContainerList } from '../pages/china/ContainerList'
import { CreateContainer } from '../pages/china/CreateContainer'
import { CreatePackingList } from '../pages/china/CreatePackingList'
import { ImportPackingLists } from '../pages/china/ImportPackingLists'
import { PackingListDetail } from '../pages/china/PackingListDetail'
import { PackingListList } from '../pages/china/PackingListList'
import { BillingDetail } from '../pages/nigeria/BillingDetail'
import { BillingList } from '../pages/nigeria/BillingList'
import { ClaimDetail } from '../pages/nigeria/ClaimDetail'
import { ClaimList } from '../pages/nigeria/ClaimList'
import { DisputeList } from '../pages/nigeria/DisputeList'
import { ManifestDetail } from '../pages/nigeria/ManifestDetail'
import { ManifestList } from '../pages/nigeria/ManifestList'
import { MissingItemList } from '../pages/nigeria/MissingItemList'
import { RefundDetail } from '../pages/nigeria/RefundDetail'
import { RefundList } from '../pages/nigeria/RefundList'
import { PrintPackingList } from '../pages/print/PrintPackingList'
import { PrintReleaseNote } from '../pages/print/PrintReleaseNote'
import { CarryoverLedger } from '../pages/nigeria/CarryoverLedger'
import { ReleaseNoteDetail } from '../pages/nigeria/ReleaseNoteDetail'
import { ReleaseNoteList } from '../pages/nigeria/ReleaseNoteList'
import { SeizedItemList } from '../pages/nigeria/SeizedItemList'
import { WarehouseDashboard } from '../pages/warehouse/WarehouseDashboard'
// Tenant-admin pages
import { Dashboard } from '../pages/tenant-admin/Dashboard'
import { StaffUserList } from '../pages/tenant-admin/StaffUserList'
import { StaffUserDetail } from '../pages/tenant-admin/StaffUserDetail'
import { AdminCustomerList } from '../pages/tenant-admin/AdminCustomerList'
import { AdminCustomerDetail } from '../pages/tenant-admin/AdminCustomerDetail'
import { CompanySettings } from '../pages/tenant-admin/CompanySettings'
import { ConfigLayout } from '../pages/tenant-admin/ConfigLayout'
import { ActivityLog } from '../pages/tenant-admin/ActivityLog'
import { DollarRateConfig } from '../pages/tenant-admin/DollarRateConfig'
import { CbmRateConfig } from '../pages/tenant-admin/CbmRateConfig'
import { ChargeTypes } from '../pages/tenant-admin/ChargeTypes'
import { ContainerCapacities } from '../pages/tenant-admin/ContainerCapacities'
import { Warehouses } from '../pages/tenant-admin/Warehouses'
import { NotificationLog } from '../pages/tenant-admin/NotificationLog'
import { NotificationTemplates } from '../pages/tenant-admin/NotificationTemplates'
import { PaymentGatewayConfig } from '../pages/tenant-admin/PaymentGatewayConfig'
import { TenantReports } from '../pages/tenant-admin/TenantReports'
import { WebhookConfig } from '../pages/tenant-admin/WebhookConfig'
import { AnnouncementsPage } from '../pages/staff/AnnouncementsPage'
import { StaffProfile } from '../pages/staff/StaffProfile'
// Platform-admin pages
import { PlatformAuditLog } from '../pages/platform/PlatformAuditLog'
import { CreateTenantPage } from '../pages/platform/CreateTenantPage'
import { OnboardingRequests } from '../pages/platform/OnboardingRequests'
import { PlatformSettings } from '../pages/platform/PlatformSettings'
import { PlatformDashboard } from '../pages/platform/PlatformDashboard'
import { PlatformTenantList } from '../pages/platform/PlatformTenantList'
import { PlatformTenantDetail } from '../pages/platform/PlatformTenantDetail'
// Customer pages
import { Account } from '../pages/customer/Account'
import { MyClaims } from '../pages/customer/MyClaims'
import { MyClaimsNew } from '../pages/customer/MyClaimsNew'
import { MyBilling } from '../pages/customer/MyBilling'
import { DisputeDetail } from '../pages/china/DisputeDetail'
import { MyBillingDetail } from '../pages/customer/MyBillingDetail'
import { MyShipments } from '../pages/customer/MyShipments'
import { MyReleaseNote } from '../pages/customer/MyReleaseNote'
import { MyShipmentDetail } from '../pages/customer/MyShipmentDetail'
import { PaymentFailed } from '../pages/customer/PaymentFailed'
import { PaymentSuccess } from '../pages/customer/PaymentSuccess'
import { PublicTrack } from '../pages/customer/PublicTrack'
import { RefundRequest } from '../pages/customer/RefundRequest'
import { CustomerLayout } from './CustomerLayout'
import { NotFoundPage } from './NotFoundPage'
import { RouteStub } from './RouteStub'
import { routeTable, type RouteDef } from './routeTable'
import { StaffLayout } from './StaffLayout'

// The apex path redirects signed-in visitors to their role's home; signed-out
// visitors get the public marketing landing page (not a further redirect to
// /login — that stays a distinct, explicit destination reachable from the
// landing page's nav/footer). Not in routeTable.ts since this dual behavior
// isn't a single guarded page.
function RootRedirect(): JSX.Element {
  const { session, status } = useSession()
  // Wait for SessionProvider's mount-time silent-restore before deciding —
  // otherwise a signed-in visitor would see the marketing page flash before
  // swapping to their role home on every reload.
  if (status === 'loading') {
    return <SessionLoading />
  }
  if (status === 'authenticated' && session) {
    return <Navigate to={homePathForRole(session.role)} replace />
  }
  return <LandingPage />
}

// src/pages/auth/auth-screens.jsx will eventually supply real screens for
// these; LoginScreen is the only one Task 04 built, the rest stay stubs
// until Task 07.
const PUBLIC_SCREENS: Record<string, JSX.Element> = {
  '/login': <LoginScreen />,
  '/register': <RegisterScreen />,
  '/register/:slug': <RegisterScreen />,
  '/get-started': <RequestOnboardingScreen />,
  '/auth/callback': <AuthCallback />,
  '/invite/:token': <InviteClaimScreen />,
  '/activate/:token': <ActivateScreen />,
  '/forgot-password': <ForgotPasswordScreen />,
  '/reset-password': <ResetPasswordScreen />,
  '/track': <PublicTrack />,
  '/track/:code': <PublicTrack />,
}

// Task 07's vertical slices (7.1 Containers & Packing Lists / China Office;
// 7.3 Manifests / Nigeria Office) — real screens for the routes
// routeTable.ts already declares. Every other guarded route still falls
// through to RouteStub until its own 7.x slice lands.
const STAFF_SCREENS: Record<string, JSX.Element> = {
  '/containers': <ContainerList />,
  '/containers/new': <CreateContainer />,
  '/containers/:id': <ContainerDetail />,
  '/packing-lists': <PackingListList />,
  '/packing-lists/new': <CreatePackingList />,
  '/packing-lists/import': <ImportPackingLists />,
  '/packing-lists/:id/edit': <CreatePackingList />,
  '/packing-lists/:id': <PackingListDetail />,
  '/packing-lists/:id/print': <PrintPackingList />,
  '/manifests': <ManifestList />,
  '/manifests/:id': <ManifestDetail />,
  '/billing': <BillingList />,
  '/billing/disputes/:id': <DisputeDetail />,
  '/billing/disputes': <DisputeList />,
  '/billing/carryovers': <CarryoverLedger />,
  '/billing/:id': <BillingDetail />,
  '/claims': <ClaimList />,
  '/claims/missing-items': <MissingItemList />,
  '/claims/seized-items': <SeizedItemList />,
  '/claims/:id': <ClaimDetail />,
  '/refunds': <RefundList />,
  '/refunds/:id': <RefundDetail />,
  // Dashboard
  '/dashboard': <Dashboard />,
  // Tenant-admin
  '/admin/users': <StaffUserList />,
  '/admin/users/:id': <StaffUserDetail />,
  '/admin/customers': <AdminCustomerList />,
  '/admin/customers/:id': <AdminCustomerDetail />,
  // Config section — every screen shares ConfigLayout's persistent sub-nav
  // rail, so switching sections swaps only the content (feels like one
  // settings page) while keeping per-section URLs/deep links.
  '/admin/config': <ConfigLayout><CompanySettings /></ConfigLayout>,
  '/admin/config/dollar-rate': <ConfigLayout><DollarRateConfig /></ConfigLayout>,
  '/admin/config/cbm-rate': <ConfigLayout><CbmRateConfig /></ConfigLayout>,
  '/admin/config/charge-types': <ConfigLayout><ChargeTypes /></ConfigLayout>,
  '/admin/config/container-capacities': <ConfigLayout><ContainerCapacities /></ConfigLayout>,
  '/admin/config/warehouses': <ConfigLayout><Warehouses /></ConfigLayout>,
  '/admin/config/notifications': <ConfigLayout><NotificationTemplates /></ConfigLayout>,
  '/admin/config/webhooks': <ConfigLayout><WebhookConfig /></ConfigLayout>,
  '/admin/config/payments': <ConfigLayout><PaymentGatewayConfig /></ConfigLayout>,
  '/profile': <StaffProfile />,
  '/admin/reports': <TenantReports />,
  '/admin/notifications/log': <NotificationLog />,
  '/admin/activity-log': <ActivityLog />,
  '/announcements': <AnnouncementsPage />,
  // Platform-admin
  '/platform/dashboard': <PlatformDashboard />,
  '/platform/audit-log': <PlatformAuditLog />,
  '/platform/settings': <PlatformSettings />,
  '/platform/settings/notifications': <PlatformSettings />,
  '/platform/settings/plans': <PlatformSettings />,
  '/platform/tenants': <PlatformTenantList />,
  '/platform/onboarding-requests': <OnboardingRequests />,
  '/platform/tenants/new': <CreateTenantPage />,
  '/platform/tenants/:id': <PlatformTenantDetail />,
  // Release notes (already here, kept)
  '/release-notes': <ReleaseNoteList />,
  '/release-notes/:id': <ReleaseNoteDetail />,
  '/release-notes/:id/print': <PrintReleaseNote />,
  '/warehouse': <WarehouseDashboard />,
  // Customer portal
  '/my-shipments': <MyShipments />,
  '/my-shipments/:code': <MyShipmentDetail />,
  '/my-billing': <MyBilling />,
  '/my-billing/:id': <MyBillingDetail />,
  '/my-release-notes/:id': <MyReleaseNote />,
  '/my-billing/:id/payment-success': <PaymentSuccess />,
  '/payment-failed': <PaymentFailed />,
  '/my-billing/:id/refund-request': <RefundRequest />,
  '/my-claims': <MyClaims />,
  '/my-claims/new': <MyClaimsNew />,
  '/account': <Account />,
}

function elementForRoute(route: RouteDef): JSX.Element {
  const page = STAFF_SCREENS[route.path] ?? <RouteStub title={route.title} />

  if (route.allow === 'public') {
    return PUBLIC_SCREENS[route.path] ?? page
  }

  const guarded = (
    <RoleGuard allow={route.allow}>
      {route.layout === 'customer' ? (
        <CustomerLayout>{page}</CustomerLayout>
      ) : route.layout === 'none' ? (
        // Guarded but shell-less — print/document views (14.12).
        page
      ) : (
        <StaffLayout>{page}</StaffLayout>
      )}
    </RoleGuard>
  )
  return guarded
}

// The one place <Route> elements get built — every entry in routeTable.ts
// becomes exactly one <Route>, guarded and shelled per its own declaration,
// so nav (navConfig.ts), guards, and the actual route tree all read from the
// same source (06_routing_rbac_and_navigation.md).
export function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      {routeTable.map((route) => (
        <Route key={route.path} path={route.path} element={elementForRoute(route)} />
      ))}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
