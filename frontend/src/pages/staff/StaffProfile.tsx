import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { usersApi } from '../../api/tenantManagement'
import { useSession } from '../../auth/useSession'
import { Banner, Card, Kvp, LocaleCard, type StaffLocale } from '../../design/components'
import { Action } from '../../design/components/Action'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import { toast } from '../../design/toast'

export function StaffProfile(): JSX.Element {
  const { session } = useSession()
  const [locale, setLocale] = useState<StaffLocale>('en')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!session) return <></>

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      await usersApi.updateMe(locale)
      toast.success('Notification language updated')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update language preference.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={session.name ?? 'My profile'}
        subtitle={session.role.replace(/_/g, ' ')}
      />

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error">{error}</Banner></div>}

      <SectionHead title="Profile" />
      <Card padding="default" style={{ marginBottom: 'var(--space-6)' }}>
        {session.name && <Kvp label="Name" value={session.name} />}
        <Kvp label="Role" value={session.role.replace(/_/g, ' ')} />
        <Kvp label="Tenant" value={session.tenantName ?? session.tenantId} divider={false} />
      </Card>

      <SectionHead title="Notification language" />
      <Card padding="default">
        <LocaleCard value={locale} onChange={setLocale} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-4)' }}>
          <Action variant="primary" loading={saving} onClick={() => void handleSave()}>
            Save changes
          </Action>
        </div>
      </Card>
    </div>
  )
}
