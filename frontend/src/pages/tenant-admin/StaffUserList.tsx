import { useMemo, useState, type JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { useQueryClient } from '@tanstack/react-query'
import {
  usersApi,
  type CreateUserInput,
  type TenantUser,
  type TenantUserRole,
} from '../../api/tenantManagement'
import { staffKeys } from '../../api/keys'
import { useStaffList } from '../../hooks/useStaff'
import {
  Badge,
  Banner,
  Button,
  Card,
  Chip,
  Field,
  Icon,
  Table,
  ViewLink,
  DialogGuard,
  type BadgeVariant,
} from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import { RoleCheckboxList } from './RoleCheckboxList'
import styles from './admin.module.css'

const ROLE_VARIANT: Record<TenantUserRole, BadgeVariant> = {
  tenant_admin: 'error',
  china_office_staff: 'info',
  nigeria_office_staff: 'success',
  warehouse_attendant: 'warning',
  customer: 'neutral',
}

function roleLabel(r: TenantUserRole): string {
  const map: Record<TenantUserRole, string> = {
    tenant_admin: 'Admin',
    china_office_staff: 'China',
    nigeria_office_staff: 'Nigeria',
    warehouse_attendant: 'Warehouse',
    customer: 'Customer',
  }
  return map[r]
}

const ROLES: TenantUserRole[] = [
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
]

interface InviteModalProps {
  onCancel: () => void
  onSuccess: (user: TenantUser) => void
}

function InviteModal({ onCancel, onSuccess }: InviteModalProps): JSX.Element {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [roles, setRoles] = useState<TenantUserRole[]>(['nigeria_office_staff'])
  const [primaryRole, setPrimaryRole] = useState<TenantUserRole | null>('nigeria_office_staff')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    if (roles.length === 0) return
    setSubmitting(true)
    setError(null)
    try {
      const body: CreateUserInput = {
        email: email.trim(),
        full_name: name.trim(),
        roles,
        primary_role: primaryRole ?? roles[0],
      }
      const user = await usersApi.create(body)
      onSuccess(user)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not invite user.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Invite staff member</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}
        <Field
          label="Email"
          name="email"
          required
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Full name"
          name="full_name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <div>
          <label
            style={{
              fontWeight: 600,
              fontSize: '0.875rem',
              display: 'block',
              marginBottom: 6,
            }}
          >
            Roles <span style={{ color: 'var(--color-error)' }}>*</span>
          </label>
          <RoleCheckboxList
            options={ROLES}
            selected={roles}
            primary={primaryRole}
            onChange={(nextRoles, nextPrimary) => {
              setRoles(nextRoles)
              setPrimaryRole(nextPrimary)
            }}
            roleLabel={roleLabel}
          />
        </div>
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={!email.trim() || !name.trim() || roles.length === 0}
            onClick={() => void handleSubmit()}
          >
            Send invite
          </Button>
        </div>
      </div>
    </div>
  )
}

export function StaffUserList(): JSX.Element {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  // Dashboard "Invite staff" quick action deep-links here with openInvite state (§3.1).
  const [showInvite, setShowInvite] = useState(
    (location.state as { openInvite?: boolean } | null)?.openInvite === true,
  )
  const [roleFilter, setRoleFilter] = useState<TenantUserRole | null>(null)
  const [query, setQuery] = useState('')
  const { data: users = [], isLoading: loading, error } = useStaffList()

  // Staff only — the roster excludes customer-role rows everywhere.
  const staff = useMemo(() => users.filter((u) => u.role !== 'customer'), [users])

  const counts = useMemo(() => {
    const map: Record<string, number> = {}
    for (const u of staff) map[u.role] = (map[u.role] ?? 0) + 1
    return map
  }, [staff])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return staff.filter((u) => {
      if (roleFilter && u.role !== roleFilter) return false
      if (!q) return true
      return u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    })
  }, [staff, roleFilter, query])

  useTopBarSlot({
    subtitle: 'Manage team members and their access roles.',
    actions: (
      <Button variant="primary" icon="plus" onClick={() => setShowInvite(true)}>
        Invite user
      </Button>
    ),
  })

  return (
    <div>
      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error.message}</Banner>
        </div>
      )}

      <Card padding={16}>
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={roleFilter === null} onClick={() => setRoleFilter(null)}>
              All <span style={{ opacity: 0.6 }}>{staff.length}</span>
            </Chip>
            {ROLES.map((r) => (
              <Chip
                key={r}
                active={roleFilter === r}
                onClick={() => setRoleFilter(roleFilter === r ? null : r)}
              >
                {roleLabel(r)} <span style={{ opacity: 0.6 }}>{counts[r] ?? 0}</span>
              </Chip>
            ))}
          </div>
          <div className={styles.searchWrap}>
            <Icon name="search" size={14} color="var(--color-ink-4)" />
            <input
              className={styles.searchInput}
              aria-label="Search staff"
              placeholder="Search by name or email…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding={0}>
          <Table
            columns={[
              { title: 'Name' },
              { title: 'Email' },
              { title: 'Role' },
              { title: 'Status' },
              { title: 'Created' },
              { title: '', width: '60px' },
            ]}
            rows={visible.map((u) => ({
              cells: [
                <span key="name">{u.full_name}</span>,
                <span key="email">{u.email}</span>,
                <Badge key="role" variant={ROLE_VARIANT[u.role]}>
                  {roleLabel(u.role)}
                </Badge>,
                <Badge key="status" variant={u.status === 'active' ? 'success' : 'neutral'}>
                  {u.status}
                </Badge>,
                <span key="created" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
                  {u.created_at?.slice(0, 10) ?? '—'}
                </span>,
                <ViewLink
                  key="view"
                  onClick={() => navigate(`/admin/users/${u.id}`, { state: { user: u } })}
                />,
              ],
            }))}
            loading={loading}
            emptyState={
              !loading && visible.length === 0 ? (
                <span>
                  {staff.length === 0 ? 'No staff members yet.' : 'No staff match this filter.'}
                </span>
              ) : undefined
            }
          />
        </Card>
      </div>

      {showInvite && (
        <InviteModal
          onCancel={() => setShowInvite(false)}
          onSuccess={() => {
            setShowInvite(false)
            void queryClient.invalidateQueries({ queryKey: staffKeys.list() })
          }}
        />
      )}
    </div>
  )
}
