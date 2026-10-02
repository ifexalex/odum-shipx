import type { JSX } from 'react'
import { useLocalRole, type DevIdentityKey } from './LocalRoleContext'
import { useSession } from './SessionContext'
import styles from './RoleSwitcher.module.css'

const IDENTITIES: DevIdentityKey[] = [
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
  'nigeria_warehouse',
]

// Floating dev-only widget — flips the active dev identity instantly for UI
// development against the local Flask dev server (see LocalAuthProvider).
// 'nigeria_warehouse' is the one multi-role identity, letting the new
// role-switch toggle (TopBar user menu) be exercised locally.
export function RoleSwitcher(): JSX.Element {
  const { identity, setIdentity } = useLocalRole()
  // After an explicit logout (LocalAuthProvider), status is genuinely
  // 'unauthenticated' even though `identity` still remembers whatever dev
  // role was last active — so re-picking that SAME option from the <select>
  // would fire no onChange at all (its value never actually changes) and the
  // switcher would look inert right after logging out. A distinct "logged
  // out" placeholder value makes any real selection a genuine change.
  const { status } = useSession()
  const loggedOut = status === 'unauthenticated'

  return (
    // Stable id (not the hashed CSS-module class) so e2e tests can
    // suppress this panel's pointer events once the role is set — it is a
    // fixed, high-z-index overlay that otherwise intercepts clicks on real
    // page content it happens to sit on top of (e2e/support/roleSwitch.ts).
    <div id="dev-role-switcher-panel" className={styles.panel}>
      <label htmlFor="local-role-switcher" className={styles.label}>
        Dev role
      </label>
      <select
        id="local-role-switcher"
        className={styles.select}
        value={loggedOut ? '' : identity}
        onChange={(event) => setIdentity(event.target.value as DevIdentityKey)}
      >
        {loggedOut && (
          <option value="" disabled>
            — logged out —
          </option>
        )}
        {IDENTITIES.map((id) => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
    </div>
  )
}
