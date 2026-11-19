import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { usersApi, type TenantUser, type TenantUserRole } from '../../api/tenantManagement'
import { staffKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import {
  Action,
  Banner,
  Button,
  Card,
  Kvp,
  LocaleCard,
  type StaffLocale,
  RoleBadge,
  StatusBadge,
} from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { ActivityFeed } from '../../shell/ActivityFeed'
import { SectionHead } from '../../shell/SectionHead'
import { RoleCheckboxList } from './RoleCheckboxList'
import styles from './admin.module.css'
import { formatDate } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { roleLabel } from '../../design/status'


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
  const stateUser = (location.state as { user?: TenantUser } | null)?.user ?? null

  const qc = useQueryClient()

  const { data: user = null, isLoading: loading, error: loadError } = useQuery({
    queryKey: staffKeys.detail(id ?? ''),
    queryFn: () => usersApi.get(id!),
    enabled: !!id,
    ...(stateUser ? { initialData: stateUser } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(user?.full_name)

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

  async function handleAction(action: 'resend' | 'activate' | 'reset' | 'deactivate'): Promise<void> {
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
      } else {
        await usersApi.deactivate(user.id)
        applyUser({ ...user, status: 'inactive' })
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

  if (loading && !user) return <div style={{ padding: 'var(--space-12)', color: 'var(--color-ink-4)' }}>Loading…</div>
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
      <Card padding="default">
        <Kvp label="Email" value={user.email} />
        <Kvp label="Roles" value={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              {(user.roles.length > 0 ? user.roles : [user.role]).map((r) => (
                <span key={r} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)' }}>
                  <RoleBadge role={r} />
                  {r === user.role && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>Primary</span>}
                </span>
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
                  roleLabel={roleLabel}
                />
                <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
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
        <Kvp label="Status" value={<StatusBadge kind="staffUser" status={user.status} />} />
        <Kvp label="Member since" value={formatDate(user.created_at)} divider={false} />
      </Card>

      <SectionHead title="Permissions" sub="What this role can and cannot do — fixed per role, enforced server-side" />
      <Card padding="default">
        {ROLE_PERMISSIONS[user.role]?.map((p, i, arr) => (
          <div key={p.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', padding: 'var(--space-2) 0', borderBottom: i < arr.length - 1 ? '1px dashed var(--color-line-soft)' : 'none' }}>
            <span style={{
              width: 22, height: 22, borderRadius: 'var(--radius-md)', flexShrink: 0,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              background: p.allowed ? 'var(--color-success-soft)' : 'var(--color-error-soft)',
              color: p.allowed ? 'var(--color-success)' : 'var(--color-error)',
              fontSize: 'var(--text-xs)', fontWeight: 700,
            }}>{p.allowed ? '✓' : '✕'}</span>
            <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)' }}>{p.label}</span>
          </div>
        ))}
      </Card>

      <SectionHead title="Recent activity" sub="What this user has done across the tenant" />
      <Card padding="default">
        <ActivityFeed actorId={user.id} limit={10} showActor={false} />
      </Card>

      <SectionHead title="Actions" />
      <Card padding="default">
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('activate')}>
            Resend activation link
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('resend')}>
            Resend invite
          </Button>
          <Button variant="secondary" size="sm" loading={saving} onClick={() => void handleAction('reset')}>
            Reset password
          </Button>
          {user.status === 'active' && (
            <Button variant="danger-outline" size="sm" loading={saving} onClick={() => void handleAction('deactivate')}>
              Deactivate user
            </Button>
          )}
        </div>
      </Card>

      <SectionHead title="Notification language" />
      <Card padding="default">
        <LocaleCard value={locale} onChange={setLocaleDraft} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-4)' }}>
          <Action variant="primary" size="sm" loading={savingLocale} onClick={() => void handleSaveLocale()}>
            Save language
          </Action>
        </div>
      </Card>

    </div>
  )
}
