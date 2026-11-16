import { Suspense, type JSX } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { RoleGuard } from '../auth/RoleGuard'
import { SessionLoading } from '../auth/SessionLoading'
import { useSession } from '../auth/useSession'
import { lazyNamed } from '../lib/lazyPage'
import { AuthCallback } from '../pages/auth/AuthCallback'
import { LoginScreen } from '../pages/auth/LoginScreen'
import { LandingPage } from '../pages/marketing/LandingPage'
import { PublicTrack } from '../pages/customer/PublicTrack'
import { NotFoundPage } from './NotFoundPage'
import { RouteStub } from './RouteStub'
import { routeTable, type RouteDef } from './routeTable'

// Pages load on demand, one chunk per area (shell/areas/*): a customer on a phone never downloads the platform,
// admin or staff screens. Sign-in, the landing page, public tracking and the sign-in callback stay in the entry chunk.

const accountScreensArea = () => import('./areas/accountScreens')
const chinaArea = () => import('./areas/china')
const customerArea = () => import('./areas/customer')
const nigeriaArea = () => import('./areas/nigeria')
const platformArea = () => import('./areas/platform')
const printArea = () => import('./areas/print')
const tenantAdminArea = () => import('./areas/tenantAdmin')
const warehouseArea = () => import('./areas/warehouse')
const staffLayout = () => import('./StaffLayout')
const customerLayout = () => import('./CustomerLayout')

const RegisterScreen = lazyNamed(accountScreensArea, 'RegisterScreen')
const RequestOnboardingScreen = lazyNamed(accountScreensArea, 'RequestOnboardingScreen')
const InviteClaimScreen = lazyNamed(accountScreensArea, 'InviteClaimScreen')
const ActivateScreen = lazyNamed(accountScreensArea, 'ActivateScreen')
const ForgotPasswordScreen = lazyNamed(accountScreensArea, 'ForgotPasswordScreen')
const ResetPasswordScreen = lazyNamed(accountScreensArea, 'ResetPasswordScreen')
const ContainerDetail = lazyNamed(chinaArea, 'ContainerDetail')
const ContainerList = lazyNamed(chinaArea, 'ContainerList')
const CreateContainer = lazyNamed(chinaArea, 'CreateContainer')
const CreatePackingList = lazyNamed(chinaArea, 'CreatePackingList')
const ImportPackingLists = lazyNamed(chinaArea, 'ImportPackingLists')
const PackingListDetail = lazyNamed(chinaArea, 'PackingListDetail')
const PackingListList = lazyNamed(chinaArea, 'PackingListList')
const DisputeDetail = lazyNamed(chinaArea, 'DisputeDetail')
const Account = lazyNamed(customerArea, 'Account')
const MyClaims = lazyNamed(customerArea, 'MyClaims')
const MyClaimsNew = lazyNamed(customerArea, 'MyClaimsNew')
const MyBilling = lazyNamed(customerArea, 'MyBilling')
const MyBillingDetail = lazyNamed(customerArea, 'MyBillingDetail')
const MyShipments = lazyNamed(customerArea, 'MyShipments')
const MyReleaseNote = lazyNamed(customerArea, 'MyReleaseNote')
const MyShipmentDetail = lazyNamed(customerArea, 'MyShipmentDetail')
const PaymentFailed = lazyNamed(customerArea, 'PaymentFailed')
const PaymentSuccess = lazyNamed(customerArea, 'PaymentSuccess')
const RefundRequest = lazyNamed(customerArea, 'RefundRequest')
const BillingDetail = lazyNamed(nigeriaArea, 'BillingDetail')
const BillingList = lazyNamed(nigeriaArea, 'BillingList')
const ClaimDetail = lazyNamed(nigeriaArea, 'ClaimDetail')
const ClaimList = lazyNamed(nigeriaArea, 'ClaimList')
const DisputeList = lazyNamed(nigeriaArea, 'DisputeList')
const ManifestDetail = lazyNamed(nigeriaArea, 'ManifestDetail')
const ManifestList = lazyNamed(nigeriaArea, 'ManifestList')
const MissingItemList = lazyNamed(nigeriaArea, 'MissingItemList')
const RefundDetail = lazyNamed(nigeriaArea, 'RefundDetail')
const RefundList = lazyNamed(nigeriaArea, 'RefundList')
const CarryoverLedger = lazyNamed(nigeriaArea, 'CarryoverLedger')
const ReleaseNoteDetail = lazyNamed(nigeriaArea, 'ReleaseNoteDetail')
const ReleaseNoteList = lazyNamed(nigeriaArea, 'ReleaseNoteList')
const SeizedItemList = lazyNamed(nigeriaArea, 'SeizedItemList')
const PlatformAuditLog = lazyNamed(platformArea, 'PlatformAuditLog')
const CreateTenantPage = lazyNamed(platformArea, 'CreateTenantPage')
const OnboardingRequests = lazyNamed(platformArea, 'OnboardingRequests')
const PlatformSettings = lazyNamed(platformArea, 'PlatformSettings')
const PlatformDashboard = lazyNamed(platformArea, 'PlatformDashboard')
const PlatformTenantList = lazyNamed(platformArea, 'PlatformTenantList')
const PlatformTenantDetail = lazyNamed(platformArea, 'PlatformTenantDetail')
const PrintPackingList = lazyNamed(printArea, 'PrintPackingList')
const PrintReleaseNote = lazyNamed(printArea, 'PrintReleaseNote')
const Dashboard = lazyNamed(tenantAdminArea, 'Dashboard')
const StaffUserList = lazyNamed(tenantAdminArea, 'StaffUserList')
const StaffUserDetail = lazyNamed(tenantAdminArea, 'StaffUserDetail')
const AdminCustomerList = lazyNamed(tenantAdminArea, 'AdminCustomerList')
const AdminCustomerDetail = lazyNamed(tenantAdminArea, 'AdminCustomerDetail')
const CompanySettings = lazyNamed(tenantAdminArea, 'CompanySettings')
const ConfigLayout = lazyNamed(tenantAdminArea, 'ConfigLayout')
const ActivityLog = lazyNamed(tenantAdminArea, 'ActivityLog')
const DollarRateConfig = lazyNamed(tenantAdminArea, 'DollarRateConfig')
const CbmRateConfig = lazyNamed(tenantAdminArea, 'CbmRateConfig')
const ChargeTypes = lazyNamed(tenantAdminArea, 'ChargeTypes')
const ContainerCapacities = lazyNamed(tenantAdminArea, 'ContainerCapacities')
const Warehouses = lazyNamed(tenantAdminArea, 'Warehouses')
const NotificationLog = lazyNamed(tenantAdminArea, 'NotificationLog')
const NotificationTemplates = lazyNamed(tenantAdminArea, 'NotificationTemplates')
const PaymentGatewayConfig = lazyNamed(tenantAdminArea, 'PaymentGatewayConfig')
const TenantReports = lazyNamed(tenantAdminArea, 'TenantReports')
const WebhookConfig = lazyNamed(tenantAdminArea, 'WebhookConfig')
const AnnouncementsPage = lazyNamed(tenantAdminArea, 'AnnouncementsPage')
const StaffProfile = lazyNamed(tenantAdminArea, 'StaffProfile')
const WarehouseDashboard = lazyNamed(warehouseArea, 'WarehouseDashboard')
const StaffLayout = lazyNamed(staffLayout, 'StaffLayout')
const CustomerLayout = lazyNamed(customerLayout, 'CustomerLayout')


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
    // A public screen that is not in the entry chunk loads on demand, on the same spinner the session restore uses.
    return <Suspense fallback={<SessionLoading />}>{PUBLIC_SCREENS[route.path] ?? page}</Suspense>
  }

  // Two boundaries. The outer one covers the layout's own chunk (the first guarded page of a session); the inner one
  // covers the page's chunk, so moving between areas keeps the sidebar or top bar on screen while the page loads.
  const content = <Suspense fallback={<SessionLoading inline />}>{page}</Suspense>
  const guarded = (
    <RoleGuard allow={route.allow}>
      <Suspense fallback={<SessionLoading />}>
        {route.layout === 'customer' ? (
          <CustomerLayout>{content}</CustomerLayout>
        ) : route.layout === 'none' ? (
          // Guarded but shell-less — print/document views (14.12).
          content
        ) : (
          <StaffLayout>{content}</StaffLayout>
        )}
      </Suspense>
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
