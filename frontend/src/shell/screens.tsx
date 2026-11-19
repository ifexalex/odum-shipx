import type { JSX } from 'react'
import { lazyNamed } from '../lib/lazyPage'
import { AuthCallback } from '../pages/auth/AuthCallback'
import { LoginScreen } from '../pages/auth/LoginScreen'
import { PublicTrack } from '../pages/customer/PublicTrack'
import type { RouteDef } from './routeTable'

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

const RegisterScreen = lazyNamed(accountScreensArea, 'RegisterScreen')
const RequestOnboardingScreen = lazyNamed(accountScreensArea, 'RequestOnboardingScreen')
const InviteClaimScreen = lazyNamed(accountScreensArea, 'InviteClaimScreen')
const ActivateScreen = lazyNamed(accountScreensArea, 'ActivateScreen')
const ForgotPasswordScreen = lazyNamed(accountScreensArea, 'ForgotPasswordScreen')
const ResetPasswordScreen = lazyNamed(accountScreensArea, 'ResetPasswordScreen')
const ChinaWorkQueue = lazyNamed(chinaArea, 'ChinaWorkQueue')
const ContainerDetail = lazyNamed(chinaArea, 'ContainerDetail')
const ContainerList = lazyNamed(chinaArea, 'ContainerList')
const CreateContainer = lazyNamed(chinaArea, 'CreateContainer')
const CreatePackingList = lazyNamed(chinaArea, 'CreatePackingList')
const ImportPackingLists = lazyNamed(chinaArea, 'ImportPackingLists')
const PackingListDetail = lazyNamed(chinaArea, 'PackingListDetail')
const PackingListList = lazyNamed(chinaArea, 'PackingListList')
const DisputeDetail = lazyNamed(chinaArea, 'DisputeDetail')
const Account = lazyNamed(customerArea, 'Account')
const MyClaimDetail = lazyNamed(customerArea, 'MyClaimDetail')
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

// The screen for every route in routeTable.ts, split by guard: PUBLIC_SCREENS for `allow: 'public'` routes (rendered
// with no RoleGuard), GUARDED_SCREENS for the rest (staff and customer pages alike; the route's `layout` picks the
// shell). Each route path appears in exactly one map, which `routes.test.tsx` checks both ways: a route with no screen,
// a screen with no route, or a screen in the wrong map fails the build. Route order does not matter; React Router
// ranks paths by specificity, so '/billing/disputes' wins over '/billing/:id' wherever either is declared.
export const PUBLIC_SCREENS: Record<string, JSX.Element> = {
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

export const GUARDED_SCREENS: Record<string, JSX.Element> = {
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
  '/work-queue': <ChinaWorkQueue />,
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
  '/my-claims/:id': <MyClaimDetail />,
  '/account': <Account />,
}

/** The screen a route renders, from the map its guard says it belongs in; undefined if none was registered. */
export function screenForRoute(route: RouteDef): JSX.Element | undefined {
  return (route.allow === 'public' ? PUBLIC_SCREENS : GUARDED_SCREENS)[route.path]
}
