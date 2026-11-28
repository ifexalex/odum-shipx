/**
 * Platform admins (platform audit Phase 1, C-28, decision D2): who can run the console and with which role.
 *
 * Roles: owner (everything, including this page's changes), admin (everything except managing admins), support
 * (read, impersonate, onboarding leads) and finance (read only). Owners invite, re-role, disable and re-enable;
 * everyone else sees the list. Nobody changes their own row here, and the last active owner cannot be demoted or
 * disabled (the API refuses both). Each change asks for re-authentication.
 */
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { platformSecurityApi, type PlatformAdmin, type PlatformRole } from '../../api/platformSecurity'
import { Banner, Button, EmptyState, Field, Modal, Select, StatusBadge, Table } from '../../design/components'
import { toast } from '../../design/toast'
import { useCanPlatform, usePlatformAdmins, usePlatformMe } from '../../hooks/usePlatformSecurity'
import { formatDate, formatDateTime } from '../../lib/format'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'
import styles from './admin.module.css'

const ROLE_OPTIONS: { value: PlatformRole; label: string; description: string }[] = [
  { value: 'owner', label: 'Owner', description: 'Everything, including inviting and removing admins' },
  { value: 'admin', label: 'Admin', description: 'Run tenants, plans and settings; approve requests' },
  { value: 'support', label: 'Support', description: 'Read everything, impersonate (read-only), work leads' },
  { value: 'finance', label: 'Finance', description: 'Read only' },
]

const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS.map((r) => [r.value, r.label])) as Record<PlatformRole, string>

function InviteModal({ onClose }: { onClose: () => void }): JSX.Element {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<PlatformRole>('support')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = email.includes('@') && name.trim().length > 0

  async function submit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const created = await platformSecurityApi.inviteAdmin({ email: email.trim(), name: name.trim(), role })
      toast.success('Invitation sent', `${created.name} will get a temporary password by email.`)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send the invitation.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Invite a platform admin" size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        <Field label="Name" name="admin_name" required value={name} onChange={(e) => setName(e.target.value)} />
        <Field
          label="Email"
          name="admin_email"
          type="email"
          icon="mail"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          helper="Their sign-in. It cannot already be a tenant user's."
        />
        <Select
          label="Role"
          value={role}
          onChange={(e) => setRole(e.target.value as PlatformRole)}
          options={ROLE_OPTIONS.map((r) => ({ value: r.value, label: `${r.label}: ${r.description}` }))}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void submit()}>
            Send invitation
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function EditModal({ admin, onClose }: { admin: PlatformAdmin; onClose: () => void }): JSX.Element {
  const [role, setRole] = useState<PlatformRole>(admin.role)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const disabled = admin.status === 'disabled'

  async function save(change: { role?: PlatformRole; disabled?: boolean }, done: string): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await platformSecurityApi.updateAdmin(admin.id, change)
      toast.success(done, admin.name)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the change.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={`${admin.name}`} size="sm">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error">{error}</Banner>}
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>{admin.email}</div>
        <Select
          label="Role"
          value={role}
          disabled={disabled}
          onChange={(e) => setRole(e.target.value as PlatformRole)}
          options={ROLE_OPTIONS.map((r) => ({ value: r.value, label: `${r.label}: ${r.description}` }))}
        />
        <div className={styles.modalActions}>
          {disabled ? (
            <Button variant="secondary" loading={submitting} onClick={() => void save({ disabled: false }, 'Access restored')}>
              Re-enable
            </Button>
          ) : (
            <Button
              variant="danger-ghost"
              loading={submitting}
              onClick={() => void save({ disabled: true }, 'Access disabled')}
            >
              Disable access
            </Button>
          )}
          <span style={{ flex: 1 }} />
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Close
          </Button>
          <Button
            variant="primary"
            loading={submitting}
            disabled={disabled || role === admin.role}
            onClick={() => void save({ role }, 'Role changed')}
          >
            Save role
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function PlatformAdmins(): JSX.Element {
  const { data, isLoading, error } = usePlatformAdmins()
  const { data: me } = usePlatformMe()
  const canManage = useCanPlatform('admins')
  const [inviting, setInviting] = useState(false)
  const [editing, setEditing] = useState<PlatformAdmin | null>(null)
  const admins = data ?? []

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Platform admins"
            meta="Who can run the ShipX console, and with which role."
            primary={
              canManage ? (
                <Button variant="primary" icon="plus" onClick={() => setInviting(true)}>
                  Invite admin
                </Button>
              ) : undefined
            }
          />
        }
        notices={<>{error && <Banner variant="error">{error.message}</Banner>}</>}
      >
        <Table
          columns={[
            { title: 'Admin' },
            { title: 'Role' },
            { title: 'Status', type: 'status' },
            { title: 'Last seen', type: 'date' },
            { title: 'Added', type: 'date' },
            { title: '', type: 'action', width: '120px' },
          ]}
          rows={admins.map((a) => {
            const self = me?.id === a.id
            return {
              cells: [
                <div key="admin" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                    {a.name}
                    {self && <span style={{ color: 'var(--color-ink-4)', fontWeight: 400 }}> (you)</span>}
                  </div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>{a.email}</div>
                </div>,
                <span key="role" style={{ fontSize: 'var(--text-sm)' }}>
                  {ROLE_LABEL[a.role]}
                </span>,
                <StatusBadge key="status" kind="platformAdmin" status={a.status} />,
                <span key="seen" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {a.last_seen_at ? formatDateTime(a.last_seen_at) : 'Never'}
                </span>,
                <span key="added" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                  {formatDate(a.created_at)}
                  {a.invited_by_name ? ` · by ${a.invited_by_name}` : ''}
                </span>,
                <div key="actions" style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  {canManage && !self && (
                    <Button variant="ghost" size="sm" onClick={() => setEditing(a)}>
                      Manage
                    </Button>
                  )}
                </div>,
              ],
            }
          })}
          loading={isLoading}
          emptyState={!isLoading && admins.length === 0 ? <EmptyState compact title="No platform admins yet" /> : undefined}
        />
      </ListPage>
      {inviting && <InviteModal onClose={() => setInviting(false)} />}
      {editing && <EditModal admin={editing} onClose={() => setEditing(null)} />}
    </>
  )
}
