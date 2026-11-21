import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { usersApi } from '../../api/tenantManagement'
import { useSession } from '../../auth/useSession'
import { Banner, Kvp, LocaleCard, type StaffLocale } from '../../design/components'
import { Action } from '../../design/components/Action'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'
import { Section } from '../../shell/Section'
import { DetailPage } from '../../shell/DetailPage'

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
    <DetailPage
      header={
        <PageHeader title="My profile" meta={[session.name, session.role.replace(/_/g, ' ')]} />
      }
    >
      {error && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      <Section title="Profile">
        {session.name && <Kvp label="Name" value={session.name} />}
        <Kvp label="Role" value={session.role.replace(/_/g, ' ')} />
        <Kvp label="Tenant" value={session.tenantName ?? session.tenantId} divider={false} />
      </Section>

      <Section title="Notification language">
        <LocaleCard value={locale} onChange={setLocale} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-4)' }}>
          <Action variant="primary" loading={saving} onClick={() => void handleSave()}>
            Save changes
          </Action>
        </div>
      </Section>
    </DetailPage>
  )
}
