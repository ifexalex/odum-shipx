import { Suspense, type JSX } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { RoleGuard } from '../auth/RoleGuard'
import { SessionLoading } from '../auth/SessionLoading'
import { useSession } from '../auth/useSession'
import { lazyNamed } from '../lib/lazyPage'
import { LandingPage } from '../pages/marketing/LandingPage'
import { NotFoundPage } from './NotFoundPage'
import { routeTable, type RouteDef } from './routeTable'
import { screenForRoute } from './screens'

// Layouts load on demand too: the first guarded page of a session fetches its shell.
const staffLayout = () => import('./StaffLayout')
const customerLayout = () => import('./CustomerLayout')
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

function elementForRoute(route: RouteDef): JSX.Element {
  // A route without a screen is a build error (routes.test.tsx). Should one ship anyway, say "not found" honestly
  // rather than render a placeholder that looks like a page.
  const page = screenForRoute(route) ?? <NotFoundPage />

  if (route.allow === 'public') {
    // A public screen that is not in the entry chunk loads on demand, on the same spinner the session restore uses.
    return <Suspense fallback={<SessionLoading />}>{page}</Suspense>
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
