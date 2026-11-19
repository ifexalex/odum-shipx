/**
 * 2.3 — Create Tenant (Section 2 of the prototype, platform-screens.jsx:336).
 *
 * Full-page onboarding: company details + initial admin + plan radio cards,
 * then a success screen. Replaces the old modal, whose flat request body
 * didn't match the backend contract (nested initial_admin) and 422'd.
 */
import { useState, type JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { platformApi, type OnboardingRequest, type SubscriptionTier, type Tenant } from '../../api/tenantManagement'
import { Banner, Button, Card, Field, Icon, Mono, PhoneField } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'

/**
 * When provisioning is launched from a company onboarding lead, OnboardingRequests
 * navigates here with the lead in router state so the form arrives pre-filled and
 * the resulting tenant is linked back to (and closes) that lead.
 */
interface ProvisionFromLead {
  lead?: OnboardingRequest
}

const PLANS: { tier: SubscriptionTier; name: string; features: string[] }[] = [
  { tier: 'starter', name: 'Starter', features: ['10 staff users', '5 containers / month', '5 GB storage'] },
  { tier: 'business', name: 'Business', features: ['50 staff users', '25 containers / month', '25 GB storage'] },
  { tier: 'enterprise', name: 'Enterprise', features: ['Unlimited users', 'Unlimited containers', 'Unlimited storage'] },
]

function PlanRadio({ name, features, selected, onSelect }: { name: string; features: string[]; selected: boolean; onSelect: () => void }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{
        textAlign: 'left', cursor: 'pointer', flex: 1, minWidth: 180,
        border: `${selected ? 2 : 1}px solid ${selected ? 'var(--color-primary)' : 'var(--color-line-soft)'}`,
        borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)',
        background: selected ? 'var(--color-primary-tint)' : 'var(--color-surface)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
        <span style={{
          width: 18, height: 18, borderRadius: '50%',
          border: `${selected ? 5 : 1.5}px solid ${selected ? 'var(--color-primary)' : 'var(--color-line)'}`,
          background: 'var(--color-surface)', flexShrink: 0,
        }} />
        <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-lg)' }}>{name}</span>
      </div>
      <ul style={{ margin: 0, paddingLeft: 'var(--space-5)', fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', lineHeight: 'var(--leading-body)' }}>
        {features.map((f) => <li key={f}>{f}</li>)}
      </ul>
    </button>
  )
}

export function CreateTenantPage(): JSX.Element {
  const navigate = useNavigate()
  const lead = (useLocation().state as ProvisionFromLead | null)?.lead
  const [companyName, setCompanyName] = useState(lead?.company_name ?? '')
  const [contactEmail, setContactEmail] = useState(lead?.contact_email ?? '')
  const [contactPhone, setContactPhone] = useState(lead?.contact_phone ?? '')
  const [adminName, setAdminName] = useState(lead?.contact_name ?? '')
  const [adminEmail, setAdminEmail] = useState(lead?.contact_email ?? '')
  const [tier, setTier] = useState<SubscriptionTier>('starter')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<Tenant | null>(null)

  const canSubmit =
    companyName.trim().length > 0 &&
    contactEmail.trim().length > 3 &&
    adminName.trim().length > 0 &&
    adminEmail.trim().length > 3 &&
    !submitting

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const result = await platformApi.createTenant({
        company_name: companyName,
        primary_contact_email: contactEmail,
        ...(contactPhone.trim() ? { primary_contact_phone: contactPhone } : {}),
        subscription_tier: tier,
        initial_admin: { email: adminEmail, full_name: adminName },
        ...(lead ? { onboarding_request_id: lead.id } : {}),
      })
      setCreated(result.tenant)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the tenant.')
    } finally {
      setSubmitting(false)
    }
  }

  if (created) {
    return (
      <div style={{ maxWidth: 560, margin: '0 auto', textAlign: 'center', paddingTop: 'var(--space-12)' }}>
        <div style={{ width: 84, height: 84, borderRadius: '50%', background: 'var(--color-success-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto var(--space-6)' }}>
          <Icon name="check" size={42} color="var(--color-success)" stroke={2.5} />
        </div>
        <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-2xl)', margin: '0 0 var(--space-2)' }}>
          {created.company_name} is live.
        </h2>
        <p style={{ fontSize: 'var(--text-md)', color: 'var(--color-ink-3)', margin: '0 0 var(--space-6)' }}>
          Tenant <Mono>{created.slug}</Mono> created on the <strong style={{ textTransform: 'capitalize' }}>{created.subscription_tier}</strong> plan.
        </p>
        <Banner variant="info" title="Admin invite sent">
          {adminEmail} received a temporary password by email. They&apos;ll set their own password on first
          sign-in and can then invite the rest of the team.
        </Banner>
        <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'center', marginTop: 'var(--space-6)' }}>
          <Button variant="secondary" onClick={() => navigate(`/platform/tenants/${created.id}`)}>
            Open tenant
          </Button>
          <Button variant="primary" onClick={() => navigate('/platform/tenants')}>
            Back to tenants
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <PageHeader
        eyebrow="Platform"
        title="Onboard a new tenant"
        subtitle="Creates the tenant, provisions the first admin in Cognito, and applies default configuration."
      />

      {lead && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner variant="info" title="Provisioning from an onboarding request">
            Pre-filled from <strong>{lead.company_name}</strong>&apos;s request. Creating this tenant marks the
            request as <strong>provisioned</strong>. Review the details and the admin&apos;s name before creating.
          </Banner>
        </div>
      )}

      {error && <div style={{ marginBottom: 'var(--space-4)' }}><Banner variant="error" title="Could not create tenant">{error}</Banner></div>}

      <Card padding="large" style={{ marginBottom: 'var(--space-4)' }}>
        <SectionHead title="Company" />
        <div style={{ height: 12 }} />
        <Field label="Company name" name="company_name" required placeholder="Acme Logistics Ltd" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
          <Field label="Primary contact email" name="contact_email" icon="mail" required placeholder="ops@acme.com" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
          <PhoneField label="Contact phone" name="contact_phone" optional value={contactPhone} onChange={setContactPhone} />
        </div>
      </Card>

      <Card padding="large" style={{ marginBottom: 'var(--space-4)' }}>
        <SectionHead title="Initial admin" sub="Gets a temporary password by email and full tenant-admin access" />
        <div style={{ height: 12 }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
          <Field label="Full name" name="admin_name" required placeholder="Amara Okafor" value={adminName} onChange={(e) => setAdminName(e.target.value)} />
          <Field label="Email" name="admin_email" icon="mail" required placeholder="amara@acme.com" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} />
        </div>
      </Card>

      <Card padding="large">
        <SectionHead title="Plan" sub="Limits can be overridden later from Platform Settings → Plans, or per-tenant" />
        <div style={{ height: 12 }} />
        <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          {PLANS.map((p) => (
            <PlanRadio key={p.tier} name={p.name} features={p.features} selected={tier === p.tier} onSelect={() => setTier(p.tier)} />
          ))}
        </div>
      </Card>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)', marginTop: 'var(--space-5)' }}>
        <Button variant="ghost" onClick={() => navigate('/platform/tenants')} disabled={submitting}>Cancel</Button>
        <Button variant="accent" icon="plus" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
          Create tenant
        </Button>
      </div>
    </div>
  )
}
