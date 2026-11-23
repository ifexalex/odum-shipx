import { useEffect, useState, type JSX } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { staffKeys } from '../../api/keys'
import { usersApi } from '../../api/tenantManagement'
import { useSession } from '../../auth/useSession'
import { useBranding } from '../../hooks/useConfig'
import { Banner, Kvp, LocaleCard, RoleBadge, type StaffLocale } from '../../design/components'
import { Action } from '../../design/components/Action'
import { roleLabel } from '../../design/status'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'
import { Section } from '../../shell/Section'
import { DetailPage } from '../../shell/DetailPage'

function readStoredLocale(userId: string): StaffLocale {
  try {
    const raw = window.localStorage.getItem(`shipx:staff-locale:${userId}`)
    return raw === 'zh' ? 'zh' : 'en'
  } catch {
    return 'en'
  }
}

function writeStoredLocale(userId: string, locale: StaffLocale): void {
  try {
    window.localStorage.setItem(`shipx:staff-locale:${userId}`, locale)
  } catch {
    // storage unavailable (private mode / jsdom)
  }
}

export function StaffProfile(): JSX.Element {
  const { session } = useSession()
  const userId = session?.userId ?? ''
  const isTenantAdmin = session?.roles?.includes('tenant_admin') ?? session?.role === 'tenant_admin'
  const { branding } = useBranding(Boolean(session && !session.isPlatformAdmin))

  const { data: userRecord } = useQuery({
    queryKey: staffKeys.detail(userId),
    queryFn: () => usersApi.get(userId),
    enabled: Boolean(userId && isTenantAdmin),
  })

  const serverLocale: StaffLocale | null =
    userRecord?.locale === 'en' || userRecord?.locale === 'zh' ? userRecord.locale : null
  const [storedLocale, setStoredLocale] = useState<StaffLocale>(() => (userId ? readStoredLocale(userId) : 'en'))
  const [draftLocale, setDraftLocale] = useState<StaffLocale | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const savedLocale: StaffLocale = serverLocale ?? storedLocale
  const locale: StaffLocale = draftLocale ?? savedLocale

  useEffect(() => {
    if (serverLocale && userId) {
      writeStoredLocale(userId, serverLocale)
    }
  }, [serverLocale, userId])

  if (!session) return <></>

  const roles = session.roles && session.roles.length > 0 ? session.roles : [session.role]
  const tenantDisplay = branding?.display_name ?? session.tenantName ?? (session.isPlatformAdmin ? 'ShipX Platform' : session.tenantId)
  const dirty = locale !== savedLocale

  async function handleSave(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await usersApi.updateMe(locale)
      const next: StaffLocale = updated?.locale === 'zh' ? 'zh' : locale
      setStoredLocale(next)
      setDraftLocale(null)
      writeStoredLocale(session!.userId, next)
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
        <PageHeader title="My profile" meta={[session.name, roles.map(roleLabel).join(' · ')]} />
      }
      notices={error && <Banner variant="error">{error}</Banner>}
    >
      <Section title="Profile">
        {session.name && <Kvp label="Name" value={session.name} />}
        {session.email && <Kvp label="Email" value={session.email} />}
        <Kvp
          label={roles.length > 1 ? 'Roles' : 'Role'}
          value={
            <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 'var(--space-1)', justifyContent: 'flex-end' }}>
              {roles.map((r) => (
                <RoleBadge key={r} role={r} size="sm" />
              ))}
            </span>
          }
        />
        <Kvp label="Company" value={tenantDisplay} divider={false} />
      </Section>

      <Section title="Notification language">
        <LocaleCard value={locale} onChange={setDraftLocale} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 'var(--space-4)' }}>
          <Action variant="primary" loading={saving} disabled={!dirty} onClick={() => void handleSave()}>
            Save changes
          </Action>
        </div>
      </Section>
    </DetailPage>
  )
}
