import { useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { type Billing } from '../../../api/billing'
import { releaseNotesApi } from '../../../api/releaseNotes'
import { useWarehouses } from '../../../hooks/useWarehouses'
import { Action, Banner, Button, Field, DialogGuard, Select, CheckboxField, DateField } from '../../../design/components'
import styles from '../BillingDetail.module.css'
import { toast } from '../../../design/toast'

// ---------------------------------------------------------------------------
// GenerateReleaseNoteModal
// ---------------------------------------------------------------------------

export interface GenerateReleaseNoteModalProps {
  billing: Billing
  onCancel: () => void
  onSuccess: () => void
}

export function GenerateReleaseNoteModal({
  billing,
  onCancel,
  onSuccess,
}: GenerateReleaseNoteModalProps): JSX.Element {
  const [releaseMode, setReleaseMode] = useState<'tags' | 'count'>('tags')
  const [tagsRaw, setTagsRaw] = useState('')
  const [packagesReleased, setPackagesReleased] = useState('')
  const [packageUnit, setPackageUnit] = useState('cartons')
  const [releaseWithOutstanding, setReleaseWithOutstanding] = useState(false)
  const [approvalNotes, setApprovalNotes] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [physicalDocumentNumber, setPhysicalDocumentNumber] = useState('')
  const [invoiceNumbersRaw, setInvoiceNumbersRaw] = useState('')
  const [creditGrantedByName, setCreditGrantedByName] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: warehouses = [] } = useWarehouses()

  // Parse comma/newline/space separated tags from the textarea
  const cartonTags = tagsRaw
    .split(/[\n,\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)
  const invoiceNumbers = invoiceNumbersRaw
    .split(/[\n,]+/)
    .map((t) => t.trim())
    .filter(Boolean)
  const packagesReleasedCount = Number(packagesReleased)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await releaseNotesApi.create({
        billing_id: billing.id,
        carton_tags: releaseMode === 'tags' ? cartonTags : [],
        packages_released: releaseMode === 'count' ? packagesReleasedCount : undefined,
        package_unit: releaseMode === 'count' ? packageUnit.trim() : undefined,
        release_with_outstanding: releaseWithOutstanding,
        approval_notes: approvalNotes || undefined,
        warehouse_id: warehouseId || undefined,
        physical_document_number: physicalDocumentNumber.trim() || undefined,
        packing_list_invoice_numbers: invoiceNumbers.length > 0 ? invoiceNumbers : undefined,
        credit_granted_by_name: releaseWithOutstanding
          ? creditGrantedByName.trim() || undefined
          : undefined,
        due_date: releaseWithOutstanding ? dueDate || undefined : undefined,
      })
      toast.success('Release note generated')
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate release note.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit =
    (releaseMode === 'tags'
      ? cartonTags.length > 0
      : packagesReleasedCount > 0 && packageUnit.trim().length > 0) &&
    (!releaseWithOutstanding || approvalNotes.trim().length > 0) &&
    !submitting

  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div
        className={styles.modalPanel}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className={styles.modalTitle}>Generate release note</h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error" title="Action failed">
              {error}
            </Banner>
          </div>
        )}

        <div>
          <label
            style={{
              fontWeight: 600,
              fontSize: 'var(--text-md)',
              display: 'block',
              marginBottom: 'var(--space-2)',
            }}
          >
            Release by
          </label>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button
              variant={releaseMode === 'tags' ? 'primary' : 'ghost'}
              onClick={() => setReleaseMode('tags')}
            >
              Carton tags
            </Button>
            <Button
              variant={releaseMode === 'count' ? 'primary' : 'ghost'}
              onClick={() => setReleaseMode('count')}
            >
              Count
            </Button>
          </div>
        </div>

        {releaseMode === 'tags' ? (
          <>
            <Field
              label="Carton tags to release"
              name="carton_tags"
              required
              multiline
              placeholder={'One tag per line, or comma-separated\ne.g. ACME-001-001, ACME-001-002'}
              value={tagsRaw}
              onChange={(e) => setTagsRaw(e.target.value)}
            />
            {cartonTags.length > 0 && (
              <p
                style={{
                  fontSize: 'var(--text-sm)',
                  color: 'var(--color-ink-4)',
                  margin: 0,
                }}
              >
                {cartonTags.length} tag(s) parsed
              </p>
            )}
          </>
        ) : (
          <>
            <Field
              label="Packages released"
              name="packages_released"
              type="number"
              required
              placeholder="e.g. 5"
              value={packagesReleased}
              onChange={(e) => setPackagesReleased(e.target.value)}
            />
            <Field
              label="Package unit"
              name="package_unit"
              required
              placeholder="e.g. cartons, bags"
              value={packageUnit}
              onChange={(e) => setPackageUnit(e.target.value)}
            />
          </>
        )}

        {warehouses.length > 0 && (
          <div className={styles.selectField}>
            <Select label="Warehouse / branch" optional
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
            >
              <option value="">Use tenant default…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                  {w.is_default ? ' (default)' : ''}
                </option>
              ))}
            </Select>
          </div>
        )}

        <Field
          label="Physical document number"
          name="physical_document_number"
          optional
          placeholder="Pre-printed serial off a physical release-note booklet, if used"
          value={physicalDocumentNumber}
          onChange={(e) => setPhysicalDocumentNumber(e.target.value)}
        />

        <Field
          label="Packing list invoice numbers"
          name="packing_list_invoice_numbers"
          optional
          placeholder="Comma-separated, e.g. #53534, #53535"
          value={invoiceNumbersRaw}
          onChange={(e) => setInvoiceNumbersRaw(e.target.value)}
        />

        <CheckboxField
          label="Release with outstanding balance (waive payment requirement)"
          checked={releaseWithOutstanding}
          onChange={setReleaseWithOutstanding}
        />

        {releaseWithOutstanding && (
          <>
            <Field
              label="Approval notes"
              name="approval_notes"
              required
              multiline
              placeholder="Manager authorisation reference or reason…"
              value={approvalNotes}
              onChange={(e) => setApprovalNotes(e.target.value)}
            />
            <Field
              label="Credit granted by"
              name="credit_granted_by_name"
              optional
              placeholder="Name of the staff member authorising this credit release"
              value={creditGrantedByName}
              onChange={(e) => setCreditGrantedByName(e.target.value)}
            />
            <DateField
              label="Debt payment date"
              name="due_date"
              optional
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </>
        )}

        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Action
            variant="primary"
            loading={submitting}
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            Generate release note
          </Action>
        </div>
      </div>
    </div>
  )
}
