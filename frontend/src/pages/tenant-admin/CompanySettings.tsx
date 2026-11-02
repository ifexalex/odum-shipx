/**
 * 4.1 — Company Settings (prototype tenant-config-screens.jsx CompanySettings).
 *
 * Audit gap A1: tenant admins previously had no way to set their company
 * identity at all — /admin/config was only a navigation hub. This page owns
 * `tenant.branding_config` (PUT /v1/tenant/config {branding}): company
 * identity, warehouse/contact details, and the document footer, with a live
 * preview of how branding renders on generated documents. Consumers:
 * PrintPackingList / PrintReleaseNote (header + footer) and StaffLayout's
 * ThemeProvider (primary_color).
 *
 * Renders inside ConfigLayout (persistent config sub-nav rail — routes.tsx).
 *
 * Divergence from the prototype (documented in AUDIT_GAPS.md): the logo is an
 * initials tile + brand colour, not an uploaded image — there is no
 * tenant-scoped upload endpoint yet (the only presigned-upload route is
 * claim-scoped). The tile mirrors exactly what TenantBrand renders in-app.
 */
import { useEffect, useMemo, useState, type JSX } from 'react'
import { type BrandingConfig } from '../../api/tenantManagement'
import { isValidHexColor } from '../../design/deriveBrandShades'
import { Banner, Button, Card, Field, PhoneField } from '../../design/components'
import { useBranding, useSaveBranding } from '../../hooks/useConfig'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './CompanySettings.module.css'

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

type FormState = Required<{ [K in keyof BrandingConfig]: string }>

const EMPTY_FORM: FormState = {
  display_name: '',
  tagline: '',
  primary_color: '',
  warehouse_address: '',
  pickup_hours: '',
  pickup_phone: '',
  support_email: '',
  support_whatsapp: '',
  document_footer: '',
}

function formFromBranding(branding: BrandingConfig | null): FormState {
  const next = { ...EMPTY_FORM }
  if (branding) {
    for (const key of Object.keys(next) as (keyof FormState)[]) {
      next[key] = branding[key] ?? ''
    }
  }
  return next
}

/** Drops empty strings so `branding_config` stores only what's actually set. */
function brandingFromForm(form: FormState): BrandingConfig {
  const out: BrandingConfig = {}
  for (const [key, value] of Object.entries(form) as [keyof FormState, string][]) {
    if (value.trim()) out[key] = value.trim()
  }
  return out
}

function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')
}

// ---------------------------------------------------------------------------
// Live document preview (prototype DocPreview) — driven by the form state so
// edits render immediately. Mirrors the real print layouts
// (PrintPackingList/PrintReleaseNote), which read the same branding fields.
// ---------------------------------------------------------------------------

function DocPreview({ form, doc }: { form: FormState; doc: 'pl' | 'rn' }): JSX.Element {
  const name = form.display_name.trim() || 'Your company name'
  const brandColor = isValidHexColor(form.primary_color) ? form.primary_color : 'var(--color-primary)'
  const footerLines = form.document_footer.trim()
    ? form.document_footer.trim().split('\n')
    : ['Set a document footer to see it here.']

  return (
    <div className={styles.docPreview} data-testid="doc-preview">
      <div className={styles.docHead}>
        <div className={styles.docBrand}>
          <div className={styles.docLogo} style={{ background: brandColor }}>
            {initialsFor(name)}
          </div>
          <div>
            <div className={styles.docCompany}>{name}</div>
            {form.tagline.trim() && <div className={styles.docTagline}>{form.tagline}</div>}
          </div>
        </div>
        <div className={styles.docTitleBlock}>
          <div className={styles.docTitle}>{doc === 'pl' ? 'PACKING LIST' : 'RELEASE NOTE'}</div>
          <div className={styles.docRef}>{doc === 'pl' ? 'PL-20260415-001' : 'RN-20260415-001'}</div>
        </div>
      </div>

      {doc === 'pl' ? (
        <>
          <div className={styles.docMetaGrid}>
            <div>
              <div className={styles.docMetaLabel}>Customer</div>
              <div className={styles.docMetaStrong}>Ngozi Okonkwo</div>
              <div className={styles.docMetaMono}>+234 801 234 5678</div>
            </div>
            <div>
              <div className={styles.docMetaLabel}>Container</div>
              <div className={styles.docMetaMono}>MSCU1234567</div>
              <div className={styles.docMetaDim}>Origin: Guangzhou</div>
            </div>
          </div>
          <div className={styles.docTableHead}>
            <span>Tag</span>
            <span>Description</span>
            <span className={styles.right}>CBM</span>
          </div>
          {[
            ['SHX-00001', 'Electronics (mixed)', '0.030'],
            ['SHX-00002', 'Clothing (assorted)', '0.021'],
            ['SHX-00003', 'Phone accessories', '0.018'],
          ].map((row) => (
            <div key={row[0]} className={styles.docTableRow}>
              <span className={styles.docMetaMono}>{row[0]}</span>
              <span>{row[1]}</span>
              <span className={`${styles.right} ${styles.docMetaMono}`}>{row[2]}</span>
            </div>
          ))}
          <div className={styles.docTotals}>3 cartons · 0.069 CBM</div>
        </>
      ) : (
        <>
          <div className={styles.docMetaGrid}>
            <div>
              <div className={styles.docMetaLabel}>Released to</div>
              <div className={styles.docMetaStrong}>Ngozi Okonkwo</div>
              <div className={styles.docMetaMono}>4 cartons</div>
            </div>
            <div>
              <div className={styles.docMetaLabel}>Pickup at</div>
              <div className={styles.docMetaDim} style={{ whiteSpace: 'pre-line' }}>
                {form.warehouse_address.trim() || 'Set your warehouse address'}
              </div>
              {form.pickup_hours.trim() && <div className={styles.docMetaDim}>{form.pickup_hours}</div>}
            </div>
          </div>
          <div className={styles.docQrRow}>
            <div className={styles.docQr} aria-hidden="true" />
            <div className={styles.docMetaDim}>
              Present this note and a valid ID at the warehouse.
              {form.pickup_phone.trim() && (
                <>
                  <br />
                  Pickup enquiries: {form.pickup_phone}
                </>
              )}
            </div>
          </div>
        </>
      )}

      <div className={styles.docFooter}>
        {footerLines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function CompanySettings(): JSX.Element {
  const { branding, isLoading, error: loadError } = useBranding()
  const save = useSaveBranding()

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saved, setSaved] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<'pl' | 'rn'>('pl')

  // Hydrate the form once branding arrives (and re-sync after saves).
  useEffect(() => {
    setForm(formFromBranding(branding))
  }, [branding])

  const dirty = useMemo(
    () => JSON.stringify(brandingFromForm(form)) !== JSON.stringify(brandingFromForm(formFromBranding(branding))),
    [form, branding],
  )

  const colorInvalid = form.primary_color.trim() !== '' && !isValidHexColor(form.primary_color.trim())

  function set<K extends keyof FormState>(key: K) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setSaved(false)
      setForm((f) => ({ ...f, [key]: e.target.value }))
    }
  }

  // Value-based counterpart for controls that emit a value rather than a DOM
  // event (PhoneField emits E.164, CountrySelect/StateSelect emit a name).
  function setValue<K extends keyof FormState>(key: K) {
    return (value: string) => {
      setSaved(false)
      setForm((f) => ({ ...f, [key]: value }))
    }
  }

  async function handleSave(): Promise<void> {
    setSaved(false)
    await save.mutateAsync(brandingFromForm(form))
    setSaved(true)
  }

  return (
    <div>
      <PageHeader
        title="Company settings"
        subtitle="Your identity on packing lists, release notes, and the customer portal."
      />

      {loadError && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="error" title="Couldn't load settings">{loadError.message}</Banner>
        </div>
      )}

      <div className={styles.grid}>
        <div className={styles.formCol}>
          <Card>
            <SectionHead title="Company identity" sub="Shown on documents and the customer portal" />
            <div style={{ height: 16 }} />
            <Field
              label="Company name"
              name="display_name"
              required
              value={form.display_name}
              onChange={set('display_name')}
              helper="Used everywhere a company name appears."
              disabled={isLoading}
            />
            <Field
              label="Display tagline"
              name="tagline"
              optional
              value={form.tagline}
              onChange={set('tagline')}
              helper="Shown beneath the logo on documents."
              disabled={isLoading}
            />
            <div className={styles.logoRow}>
              <div
                className={styles.logoTile}
                style={{ background: isValidHexColor(form.primary_color) ? form.primary_color : 'var(--color-primary)' }}
              >
                {initialsFor(form.display_name || '?')}
              </div>
              <div className={styles.logoMeta}>
                <div className={styles.logoTitle}>Logo mark</div>
                <div className={styles.logoDesc}>
                  Your initials on your brand colour — used in the sidebar and on documents. Image
                  upload is coming once file storage for branding lands.
                </div>
              </div>
              <div className={styles.colorField}>
                <Field
                  label="Brand colour"
                  name="primary_color"
                  optional
                  placeholder="#1a73e8"
                  value={form.primary_color}
                  onChange={set('primary_color')}
                  error={colorInvalid ? 'Use a hex colour like #1a73e8.' : undefined}
                  disabled={isLoading}
                />
              </div>
            </div>
          </Card>

          <Card>
            <SectionHead title="Warehouse & contact" sub="Where customers collect goods and reach you" />
            <div style={{ height: 16 }} />
            <Field
              label="Warehouse address"
              name="warehouse_address"
              multiline
              rows={3}
              value={form.warehouse_address}
              onChange={set('warehouse_address')}
              helper="Printed on release notes for customer pickup."
              disabled={isLoading}
            />
            <div className={styles.grid2}>
              <Field label="Pickup hours" name="pickup_hours" optional placeholder="Mon–Sat · 8:00 AM – 5:00 PM" value={form.pickup_hours} onChange={set('pickup_hours')} disabled={isLoading} />
              <PhoneField label="Pickup contact phone" name="pickup_phone" optional value={form.pickup_phone} onChange={setValue('pickup_phone')} disabled={isLoading} />
            </div>
            <div className={styles.grid2}>
              <Field label="Support email" name="support_email" optional type="email" icon="mail" value={form.support_email} onChange={set('support_email')} disabled={isLoading} />
              <PhoneField label="Support WhatsApp" name="support_whatsapp" optional value={form.support_whatsapp} onChange={setValue('support_whatsapp')} disabled={isLoading} />
            </div>
          </Card>

          <Card>
            <SectionHead title="Document footer" sub="Boilerplate at the bottom of generated documents" />
            <div style={{ height: 16 }} />
            <Field
              label="Footer text"
              name="document_footer"
              multiline
              rows={3}
              optional
              value={form.document_footer}
              onChange={set('document_footer')}
              helper="Appears at the bottom of every packing list and release note."
              disabled={isLoading}
            />
          </Card>

          {save.error && (
            <Banner variant="error" title="Couldn't save">{save.error.message}</Banner>
          )}
          {saved && (
            <Banner variant="success" title="Saved">
              Branding updated — documents and the app theme now use it.
            </Banner>
          )}

          <div className={styles.saveBar}>
            <Button
              variant="ghost"
              disabled={!dirty || save.isPending}
              onClick={() => setForm(formFromBranding(branding))}
            >
              Discard
            </Button>
            <Button
              variant="primary"
              icon="check"
              loading={save.isPending}
              disabled={!dirty || colorInvalid || !form.display_name.trim()}
              onClick={() => void handleSave()}
            >
              Save changes
            </Button>
          </div>
        </div>

        <div className={styles.previewCol}>
          <Card padding={20}>
            <SectionHead title="Live preview" sub="How your branding appears on documents" />
            <div style={{ height: 16 }} />
            <div className={styles.previewToggle} role="tablist">
              <button
                role="tab"
                aria-selected={previewDoc === 'pl'}
                className={[styles.previewTab, previewDoc === 'pl' ? styles.previewTabActive : ''].join(' ')}
                onClick={() => setPreviewDoc('pl')}
              >
                Packing list
              </button>
              <button
                role="tab"
                aria-selected={previewDoc === 'rn'}
                className={[styles.previewTab, previewDoc === 'rn' ? styles.previewTabActive : ''].join(' ')}
                onClick={() => setPreviewDoc('rn')}
              >
                Release note
              </button>
            </div>
            <div style={{ height: 16 }} />
            <DocPreview form={form} doc={previewDoc} />
          </Card>
        </div>
      </div>
    </div>
  )
}
