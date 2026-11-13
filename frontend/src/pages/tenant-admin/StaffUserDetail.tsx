import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { usersApi, type TenantUser, type TenantUserRole } from '../../api/tenantManagement'
import { staffKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Action, Badge, Banner, Button, Card, Kvp, LocaleCard, type BadgeVariant, type StaffLocale } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { ActivityFeed } from '../../shell/ActivityFeed'
import { SectionHead } from '../../shell/SectionHead'
import { RoleCheckboxList } from './RoleCheckboxList'
import styles from './admin.module.css'

const ROLE_VARIANT: Record<TenantUserRole, BadgeVariant> = {
  tenant_admin: 'error',
  china_office_staff: 'info',
  nigeria_office_staff: 'success',
  warehouse_attendant: 'warning',
  customer: 'neutral',
}

const ROLE_OPTIONS: TenantUserRole[] = [
  'tenant_admin', 'china_office_staff', 'nigeria_office_staff', 'warehouse_attendant',
]

// Prototype 3.4 — per-role capability summary. Mirrors the backend role
// gates (handlers' assert_role lists); purely informational here.
const ROLE_PERMISSIONS: Record<string, { label: string; allowed: boolean }[]> = {
  tenant_admin: [
    { label: 'Manage staff users and roles', allowed: true },
    { label: 'Edit rates, charge types, and notification templates', allowed: true },
    { label: 'Approve refunds above the staff threshold', allowed: true },
    { label: 'Cancel billing and exempt carryovers', allowed: true },
    { label: 'GDPR erasure of customer records', allowed: true },
  ],
  china_office_staff: [
    { label: 'Create containers and packing lists', allowed: true },
    { label: 'Update China-side container stages', allowed: true },
    { label: 'View manifests and CBM disputes', allowed: true },
    { label: 'Record payments or issue release notes', allowed: false },
    { label: 'Manage staff users or tenant config', allowed: false },
  ],
  nigeria_office_staff: [
    { label: 'Verify manifests and update Nigeria-side stages', allowed: true },
    { label: 'Record payments and issue release notes', allowed: true },
    { label: 'Handle claims, disputes, and refunds (within threshold)', allowed: true },
    { label: 'Approve refunds above the configured threshold', allowed: false },
    { label: 'Manage staff users or tenant config', allowed: false },
  ],
  warehouse_attendant: [
    { label: 'View active release notes', allowed: true },
    { label: 'Record cartons picked up (incl. delegates)', allowed: true },
    { label: 'Create or edit billing, claims, or refunds', allowed: false },
    { label: 'Manage users or configuration', allowed: false },
  ],
  customer: [
    { label: 'Track own shipments and billing', allowed: true },
    { label: 'File CBM disputes and damage claims', allowed: true },
    { label: 'See other customers\' data', allowed: false },
  ],
}

export function StaffUserDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const { session } = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const stateUser = (location.state as { user?: TenantUser } | null)?.user ?? null

  const qc = useQueryClient()

  const { data: user = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: staffKeys.detail(id ?? ''),
    queryFn: () => usersApi.get(id!),
    enabled: !!id,
    ...(stateUser ? { initialData: stateUser } : {}),
    staleTime: STALE_30S,
  })

  const [editRoles, setEditRoles] = useState<TenantUserRole[] | null>(null)
  const [editPrimaryRole, setEditPrimaryRole] = useState<TenantUserRole | null>(null)
  const [saving, setSaving] = useState(false)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [savingLocale, setSavingLocale] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load user.'
      : null)

  // The locale select is an *editable* field previously seeded from inside the
  // fetch (`setLocale(result.locale …)`). Deriving it outright would discard a
  // half-made choice whenever the query refetched — the CompanySettings bug
  // class from 7.149. So `localeDraft` holds only a choice the user has
  // actually made, and the server value shows through until then; saving clears
  // the draft so the refetched value takes over again.
  const [localeDraft, setLocaleDraft] = useState<StaffLocale | null>(null)
  const locale: StaffLocale = localeDraft ?? (user?.locale === 'zh' ? 'zh' : 'en')

  const applyUser = (updated: TenantUser): void => {
    qc.setQueryData(staffKeys.detail(id ?? ''), updated)
  }

  async function handleSaveRoles(): Promise<void> {
    if (!user || !editRoles || editRoles.length === 0) return
    setSaving(true)
    setActionError(null)
    try {
      const updated = await usersApi.update(user.id, {
        roles: editRoles,
        primary_role: editPrimaryRole ?? editRoles[0],
      })
      applyUser(updated)
      setEditRoles(null)
      setEditPrimaryRole(null)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not update roles.')
    } finally {
      setSaving(false)
    }
  }

  async function handleAction(
    action: 'resend' | 'activate' | 'reset' | 'deactivate' | 'reactivate',
  ): Promise<void> {
    if (!user) return
    setSaving(true)
    setActionError(null)
    try {
      if (action === 'resend') {
        await usersApi.resendInvite(user.id)
        setActionMsg('Invite email resent.')
      } else if (action === 'activate') {
        await usersApi.resendActivation(user.id)
        setActionMsg('Activation link sent.')
      } else if (action === 'reset') {
        await usersApi.resetPassword(user.id)
        setActionMsg('Password reset email sent.')
      } else if (action === 'reactivate') {
        // Returns the updated row, so take the server's word for the status
        // rather than assuming it.
        const updated = await usersApi.reactivate(user.id)
        applyUser({ ...user, ...updated })
        setActionMsg('User reactivated — they can sign in again.')
      } else {
        await usersApi.deactivate(user.id)
        // 'deactivated', not 'inactive'. The DELETE returns 204 with no body,
        // so this optimistic value is all the UI has until a refetch — and it
        // previously wrote a status the database cannot hold, which meant the
        // reactivate control below would never appear.
        applyUser({ ...user, status: 'deactivated' })
        setActionMsg('User deactivated.')
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Action failed.')
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveLocale(): Promise<void> {
    if (!user) return
    setSavingLocale(true)
    setActionError(null)
    try {
      const updated = await usersApi.update(user.id, { locale })
      applyUser(updated)
      setLocaleDraft(null)
      setActionMsg('Notification language updated.')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not update locale.')
    } finally {
      setSavingLocale(false)
    }
  }

  if (loading && !user) return <div style={{ padding: 48, color: 'var(--color-text-muted)' }}>Loading…</div>
  if (error && !user) return <div className={styles.banner}><Banner variant="error">{error}</Banner></div>
  if (!user) return <></>

  return (
    <div>
      <PageHeader title={user.full_name} subtitle={user.email} />

      {session?.readOnly && (
        <div className={styles.banner}>
          <Banner variant="warning" icon="eye" title="Read-only session">
            You're viewing this tenant as their Tenant Admin for support. Data is fully visible, but every create, edit, approve, and delete action is disabled. The session ends automatically after 30 minutes or when you exit.
          </Banner>
        </div>
      )}
      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}
      {actionMsg && <div className={styles.banner}><Banner variant="success">{actionMsg}</Banner></div>}

      <SectionHead title="Profile" />
      <Card padding={20}>
        <Kvp label="Email" value={user.email} />
        <Kvp label="Roles" value={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {(user.roles.length > 0 ? user.roles : [user.role]).map((r) => (
                <Badge key={r} variant={ROLE_VARIANT[r]}>
                  {r.replace(/_/g, ' ')}{r === user.role ? ' · primary' : ''}
                </Badge>
              ))}
              {editRoles === null && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditRoles(user.roles.length > 0 ? user.roles : [user.role])
                    setEditPrimaryRole(user.role)
                  }}
                >
                  Change
                </Button>
              )}
            </div>
            {editRoles !== null && (
              <div>
                <RoleCheckboxList
                  options={ROLE_OPTIONS}
                  selected={editRoles}
                  primary={editPrimaryRole}
                  onChange={(nextRoles, nextPrimary) => {
                    setEditRoles(nextRoles)
                    setEditPrimaryRole(nextPrimary)
                  }}
                  roleLabel={(r) => r.replace(/_/g, ' ')}
                />
                <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                  <Action variant="primary" size="sm" loading={saving} disabled={editRoles.length === 0} onClick={() => void handleSaveRoles()}>
                    Save
                  </Action>
                  <Button variant="ghost" size="sm" onClick={() => { setEditRoles(null); setEditPrimaryRole(null) }}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        } />
        <Kvp label="Status" value={<Badge variant={user.status === 'active' ? 'success' : 'neutral'}>{user.status}</Badge>} />
        <Kvp label="Member since" value={user.created_at.slice(0, 10)} divider={false} />
      </Card>

      <SectionHead title="Permissions" sub="What this role can and cannot do — fixed per role, enforced server-side" />
      <Card padding={20}>
        {ROLE_PERMISSIONS[user.role]?.map((p, i, arr) => (
          <div key={p.label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: i < arr.length - 1 ? '1px dashed var(--color-line-soft)' : 'none' }}>
            <span style={{
              width: 22, height: 22, borderRadius: 6, flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              background: p.allowed ? 'var(--color-success-soft)' : 'var(--color-error-soft)',
              color: p.allowed ? 'var(--color-success)' : 'var(--color-error)',
              fontSize: 12, fontWeight: 700,
            }}>{p.allowed ? '✓' : '✕'}</span>
            <span style={{ fontSize: 13, color: 'var(--color-ink-2)' }}>{p.label}</span>
          </div>
        ))}
      </Card>

      <SectionHead title="Recent activity" sub="What this user has done across the tenant" />
      <Card padding={20}>
        <ActivityFeed actorId={user.id} limit={10} showActor={false} />
      </Card>

      <SectionHead title="Actions" />
      <Card padding={20}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('activate')}>
            Resend activation link
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('resend')}>
            Resend invite
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('reset')}>
            Reset password
          </Button>
          {user.status === 'active' ? (
            <Button variant="danger-outline" size="sm" loading={saving} onClick={() => void handleAction('deactivate')}>
              Deactivate user
            </Button>
          ) : (
            /* Deactivation used to be a one-way door: this branch did not
               exist, so the button simply vanished and left no way back. */
            <Button variant="primary" size="sm" loading={saving} onClick={() => void handleAction('reactivate')}>
              Reactivate user
            </Button>
          )}
        </div>
      </Card>

      <SectionHead title="Notification language" />
      <Card padding={20}>
        <LocaleCard value={locale} onChange={setLocaleDraft} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Action variant="primary" size="sm" loading={savingLocale} onClick={() => void handleSaveLocale()}>
            Save language
          </Action>
        </div>
      </Card>

      <div style={{ marginTop: 24 }}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/admin/users')}>Back to users</Button>
      </div>
    </div>
  )
}
