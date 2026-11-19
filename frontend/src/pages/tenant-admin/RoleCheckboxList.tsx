import type { JSX } from 'react'
import type { TenantUserRole } from '../../api/tenantManagement'
import { Check } from '../../design/components'

export interface RoleCheckboxListProps {
  /** Assignable roles, in display order. */
  options: TenantUserRole[]
  selected: TenantUserRole[]
  /** Which of `selected` is primary. Null only when `selected` is empty. */
  primary: TenantUserRole | null
  onChange: (selected: TenantUserRole[], primary: TenantUserRole | null) => void
  roleLabel: (role: TenantUserRole) => string
}

// Shared role-assignment control for the staff invite/edit flows — a
// checkbox per assignable role plus a radio marking which checked role is
// primary (services/tenant_management/models.py CreateTenantUserRequest /
// UpdateTenantUserRequest: `roles` + `primary_role`). Reused by
// StaffUserList's invite modal and StaffUserDetail's edit-roles flow so the
// two don't duplicate this wiring.
export function RoleCheckboxList({ options, selected, primary, onChange, roleLabel }: RoleCheckboxListProps): JSX.Element {
  function toggleRole(role: TenantUserRole, checked: boolean): void {
    const nextSelected = checked ? [...selected, role] : selected.filter((r) => r !== role)
    // Losing the primary role reassigns it to whatever's left; checking the
    // very first role auto-primaries it so a single-role selection never
    // needs a separate radio click.
    let nextPrimary = primary
    if (!checked && primary === role) {
      nextPrimary = nextSelected[0] ?? null
    } else if (checked && nextSelected.length === 1) {
      nextPrimary = role
    }
    onChange(nextSelected, nextPrimary)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {options.map((role) => {
        const checked = selected.includes(role)
        return (
          <div key={role} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Check checked={checked} onChange={(next) => toggleRole(role, next)} />
            <span style={{ flex: 1, fontSize: 'var(--text-md)', cursor: 'pointer' }} onClick={() => toggleRole(role, !checked)}>
              {roleLabel(role)}
            </span>
            {checked && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', cursor: 'pointer' }}>
                <input type="radio" name="primary-role" checked={primary === role} onChange={() => onChange(selected, role)} />
                Primary
              </label>
            )}
          </div>
        )
      })}
    </div>
  )
}
