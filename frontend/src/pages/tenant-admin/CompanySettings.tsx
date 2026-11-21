/**
 * 4.1 — Company Settings (prototype tenant-config-screens.jsx CompanySettings).
 *
 * Audit gap A1: tenant admins previously had no way to set their company
 * identity at all — /admin/config was only a navigation hub. This page owns
 * `tenant.branding_config` (PUT /v1/tenant/config {branding}): company
 * identity, warehouse/contact details, and the document footer, with a live
 * preview of how branding renders on generated documents. Consumers:
 * the generated PDFs (services/excel/pdf_theme.py: brand block and footer) and StaffLayout's
 * ThemeProvider (primary_color).
 *
 * Renders inside ConfigLayout (persistent config sub-nav rail — routes.tsx).
 *
 * The logo (FD-29) is an uploaded image (PNG, JPEG or WebP, up to 1 MB) through
 * the tenant-scoped logo endpoints, saved as soon as it is chosen rather than with
 * the form; until one is uploaded, the initials on the brand colour stand in.
 * `TenantLogo` draws it here, in the live preview and on the printed documents.
 */
import { useMemo, useRef, useState, type JSX } from 'react'
import { type BrandingConfig } from '../../api/tenantManagement'
import { isValidHexColor } from '../../design/deriveBrandShades'
import { ApiError } from '../../api/client'
import { LogoFileError } from '../../api/uploads'
import { Banner, Button, Card, Field, PhoneField, Pressable, ColorField, ConfirmDialog, ErrorState, FileInput } from '../../design/components'
import { useBranding, useSaveBranding, useTenantLogo } from '../../hooks/useConfig'
import { TenantLogo } from '../../shell/TenantLogo'
import { PageHeader } from '../../shell/PageHeader'
import { UnsavedChangesGuard } from '../../shell/UnsavedChangesGuard'
import { SectionHead } from '../../shell/SectionHead'
import styles from './CompanySettings.module.css'
import { toast } from '../../design/toast'

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

// The logo is not a form field: it is uploaded and saved on its own (FD-29).
type FormState = Required<{ [K in Exclude<keyof BrandingConfig, 'logo_url'>]: string }>

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


// ---------------------------------------------------------------------------
// Live document preview (prototype DocPreview) — driven by the form state so
// edits render immediately. Mirrors the real print layouts
// (services/excel/pdf_theme.py), which read the same branding fields.
// ---------------------------------------------------------------------------

function DocPreview({ form, doc, logoUrl }: { form: FormState; doc: 'pl' | 'rn'; logoUrl?: string }): JSX.Element {
  const name = form.display_name.trim() || 'Your company name'
  const footerLines = form.document_footer.trim()
    ? form.document_footer.trim().split('\n')
    : ['Set a document footer to see it here.']

  return (
    <div className={styles.docPreview} data-testid="doc-preview">
      <div className={styles.docHead}>
        <div className={styles.docBrand}>
          <TenantLogo name={name} color={form.primary_color} logoUrl={logoUrl} className={styles.docLogo} />
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
// Logo (FD-29): uploaded and saved on its own, not with the form
// ---------------------------------------------------------------------------

function LogoBlock({
  name,
  color,
  logoUrl,
  disabled,
}: {
  name: string
  color: string
  logoUrl?: string
  disabled: boolean
}): JSX.Element {
  const { upload, remove } = useTenantLogo()
  const fileInput = useRef<HTMLInputElement>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  async function handleFile(file: File | undefined): Promise<void> {
    if (!file) return
    setProblem(null)
    try {
      await upload.mutateAsync(file)
      toast.success(logoUrl ? 'Logo replaced' : 'Logo uploaded', 'Your documents show it from now on.')
    } catch (err) {
      setProblem(
        err instanceof LogoFileError || err instanceof ApiError ? err.message : 'The logo could not be uploaded. Try again.',
      )
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function handleRemove(): Promise<void> {
    await remove.mutateAsync()
    setConfirmRemove(false)
    toast.success('Logo removed', 'Your initials on your brand colour are used instead.')
  }

  return (
    <div className={styles.logoBlock}>
      <TenantLogo name={name} color={color} logoUrl={logoUrl} className={styles.logoTile} />
      <div className={styles.logoMeta}>
        <div className={styles.logoTitle}>Logo</div>
        <div className={styles.logoDesc}>
          {logoUrl
            ? 'Shown on your packing lists and release notes.'
            : 'Until you upload one, your initials on your brand colour are used.'}{' '}
          PNG, JPEG or WebP, up to 1 MB. Saved as soon as you choose it.
        </div>
        {problem && (
          <p className={styles.logoProblem} role="alert">
            {problem}
          </p>
        )}
      </div>
      <div className={styles.logoActions}>
        <FileInput
          ref={fileInput}
          label="Logo file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => void handleFile(e.target.files?.[0])}
        />
        <Button
          variant="secondary"
          icon="upload"
          loading={upload.isPending}
          disabled={disabled}
          onClick={() => fileInput.current?.click()}
        >
          {logoUrl ? 'Replace logo' : 'Upload logo'}
        </Button>
        {logoUrl && (
          <Button variant="danger-ghost" disabled={disabled} onClick={() => setConfirmRemove(true)}>
            Remove logo
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirmRemove}
        title="Remove your logo?"
        confirmLabel="Remove logo"
        undo="You can upload it again at any time."
        busy={remove.isPending}
        error={remove.error ? (remove.error instanceof ApiError ? remove.error.message : 'The logo could not be removed.') : null}
        onConfirm={handleRemove}
        onCancel={() => setConfirmRemove(false)}
      >
        Documents will show your initials on your brand colour instead.
      </ConfirmDialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/**
 * Owns the editable form state, seeded from the branding it is given.
 *
 * Split out so the parent can re-seed it by changing `key` instead of by
 * running an effect. The old shape hydrated the form with
 * `useEffect(() => setForm(formFromBranding(branding)), [branding])`, which
 * rendered once with the stale form and then cascaded a second render — and,
 * because `branding` is a TanStack Query result, any invalidation of the
 * config cache while someone was mid-edit silently replaced what they had
 * typed. Remounting makes the same re-sync explicit and keeps it in one place.
 */
function CompanySettingsForm({
  branding,
  loadError,
  isLoading,
}: {
  branding: BrandingConfig | null
  loadError: Error | null
  isLoading: boolean
}): JSX.Element {
  const save = useSaveBranding()

  const [form, setForm] = useState<FormState>(() => formFromBranding(branding))
  const [previewDoc, setPreviewDoc] = useState<'pl' | 'rn'>('pl')

  const dirty = useMemo(
    () => JSON.stringify(brandingFromForm(form)) !== JSON.stringify(brandingFromForm(formFromBranding(branding))),
    [form, branding],
  )

  const colorInvalid = form.primary_color.trim() !== '' && !isValidHexColor(form.primary_color.trim())

  function set<K extends keyof FormState>(key: K) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
    }
  }

  // Value-based counterpart for controls that emit a value rather than a DOM
  // event (PhoneField emits E.164, CountrySelect/StateSelect emit a name).
  function setValue<K extends keyof FormState>(key: K) {
    return (value: string) => {
      setForm((f) => ({ ...f, [key]: value }))
    }
  }

  async function handleSave(): Promise<void> {
    await save.mutateAsync(brandingFromForm(form))
    toast.success('Company settings saved', 'Documents and the portal show the change.')
  }

  return (
    <div>
      {/* Ask before leaving with unsaved edits (FD-54); the logo saves on its own, so it never counts. */}
      <UnsavedChangesGuard when={dirty && !save.isPending} />
      <PageHeader
        title="Company settings"
        meta="Your identity on packing lists, release notes, and the customer portal."
      />

      {loadError && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <ErrorState compact title="Couldn't load settings" error={loadError} />
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
            <LogoBlock
              name={form.display_name || '?'}
              color={form.primary_color}
              logoUrl={branding?.logo_url}
              disabled={isLoading}
            />
            <ColorField
              label="Brand colour"
              name="primary_color"
              optional
              value={form.primary_color}
              onChange={(hex) => setForm((f) => ({ ...f, primary_color: hex }))}
              error={colorInvalid ? 'Use a hex colour like #1a73e8.' : undefined}
              helper="Buttons and highlights across your workspace, and the initials tile when there is no logo."
              disabled={isLoading}
            />
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
          <Card padding="default">
            <SectionHead title="Live preview" sub="How your branding appears on documents" />
            <div style={{ height: 16 }} />
            <div className={styles.previewToggle} role="tablist">
              <Pressable
                role="tab"
                aria-selected={previewDoc === 'pl'}
                className={[styles.previewTab, previewDoc === 'pl' ? styles.previewTabActive : ''].join(' ')}
                onClick={() => setPreviewDoc('pl')}
              >
                Packing list
              </Pressable>
              <Pressable
                role="tab"
                aria-selected={previewDoc === 'rn'}
                className={[styles.previewTab, previewDoc === 'rn' ? styles.previewTabActive : ''].join(' ')}
                onClick={() => setPreviewDoc('rn')}
              >
                Release note
              </Pressable>
            </div>
            <div style={{ height: 16 }} />
            <DocPreview form={form} doc={previewDoc} logoUrl={branding?.logo_url} />
          </Card>
        </div>
      </div>
    </div>
  )
}

export function CompanySettings(): JSX.Element {
  const { branding, isLoading, error: loadError } = useBranding()

  // Keyed on whether branding has ARRIVED, not on its contents: the form needs
  // seeding exactly once, when the fetch resolves. Keying on the contents would
  // remount after every save — the save invalidates the config cache — which
  // threw away the "Saved" confirmation along with the rest of the state.
  //
  // Re-syncing after a save is not needed: a successful save means the form
  // already holds precisely what was persisted.
  return (
    <CompanySettingsForm
      key={branding === null ? 'empty' : 'loaded'}
      branding={branding}
      loadError={loadError}
      isLoading={isLoading}
    />
  )
}
