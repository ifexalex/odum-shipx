/**
 * 14.12 / F-B2 — Printable A4 release note (prototype reports-screens.jsx:870).
 * Pickup authorisation the customer presents at the warehouse.
 */
import { type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { Button } from '../../design/components'
import { useBranding } from '../../hooks/useConfig'
import { useReleaseNote } from '../../hooks/useReleaseNotes'
import { PrintBrandFoot, PrintBrandHead } from './PrintBrand'
import styles from './print.module.css'
import { formatDate, formatAmount } from '../../lib/format'

export function PrintReleaseNote(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: note, error: loadError } = useReleaseNote(id ?? '')
  const { branding } = useBranding()

  if (loadError) {
    return (
      <div className={styles.loading}>
        {loadError instanceof ApiError ? loadError.message : 'Could not load this release note.'}
      </div>
    )
  }
  if (!note) return <div className={styles.loading}>Preparing document…</div>

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate(`/release-notes/${note.id}`)}>
          Back
        </Button>
        <Button variant="primary" icon="file" onClick={() => window.print()}>
          Print / Save as PDF
        </Button>
      </div>

      <div className={styles.head}>
        <PrintBrandHead branding={branding} />
        <div style={{ textAlign: 'right' }}>
          <h1 className={styles.docTitle}>Release Note</h1>
          <div className={styles.docRef}>{note.reference_number}</div>
        </div>
      </div>

      {note.status === 'expired' && (
        <div style={{ border: '2px solid #dc2626', color: '#dc2626', borderRadius: 8, padding: '10px 14px', fontWeight: 700, textAlign: 'center', marginBottom: 16, letterSpacing: '0.2em', textTransform: 'uppercase' }}>
          Expired — not valid for pickup
        </div>
      )}

      <div className={styles.metaGrid}>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Customer</span>
          <span className={styles.metaValue}>{note.customer_name ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Container</span>
          <span className={`${styles.metaValue} ${styles.mono}`}>{note.container_number ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Issued</span>
          <span className={styles.metaValue}>{formatDate(note.authorized_at)}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Valid until</span>
          <span className={styles.metaValue}>{note.valid_until ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Cartons authorised</span>
          <span className={`${styles.metaValue} ${styles.mono}`}>
            {note.carton_count} of {note.total_cartons_for_customer}
            {note.is_partial_release ? ' (partial release)' : ''}
          </span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Payment status</span>
          <span className={styles.metaValue} style={{ textTransform: 'capitalize' }}>{note.payment_status.replace(/_/g, ' ')}</span>
        </div>
        {/* Ground-truth gap found live, against a real paper "Goods Release
            Note" reference: this read the tenant-wide branding.warehouse_address
            singleton instead of the release note's own linked warehouse — a
            multi-branch tenant would print every note with the same one
            address regardless of which office actually issued it. Falls back
            to the tenant-wide address only when this note has no warehouse
            linked at all (older notes, or a tenant with none configured). */}
        {(note.warehouse_address ?? branding?.warehouse_address)?.trim() && (
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Warehouse address</span>
            <span className={styles.metaValue} style={{ whiteSpace: 'pre-line' }}>
              {note.warehouse_name ? `${note.warehouse_name}\n` : ''}
              {note.warehouse_address ?? branding?.warehouse_address}
              {note.warehouse_phone ? `\n${note.warehouse_phone}` : branding?.pickup_hours?.trim() ? `\n${branding.pickup_hours}` : ''}
            </span>
          </div>
        )}
        {note.physical_document_number && (
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Physical document no.</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{note.physical_document_number}</span>
          </div>
        )}
        {note.packing_list_invoice_numbers.length > 0 && (
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Packing list invoice no.</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{note.packing_list_invoice_numbers.join(', ')}</span>
          </div>
        )}
        {note.packages_balance != null && note.packages_balance > 0 && (
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Balance of cartons</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{note.packages_balance}</span>
          </div>
        )}
      </div>

      {/* Amount paid / balance owed / debt payment date — the paper form's
          own three-column payment block, shown only when there's something
          to report (a fully-paid release with nothing outstanding has no
          need for it). */}
      {(Number(note.amount_paid_ngn) > 0 || Number(note.balance_ngn) > 0 || note.is_on_credit) && (
        <div className={styles.metaGrid}>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Amount paid (₦)</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{formatAmount(note.amount_paid_ngn)}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Balance owed (₦)</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{formatAmount(note.balance_ngn)}</span>
          </div>
          {note.is_on_credit && (
            <div className={styles.metaRow}>
              <span className={styles.metaLabel}>{note.receipt_number ? 'Receipt no.' : 'Status'}</span>
              <span className={styles.metaValue}>{note.receipt_number ?? 'ON CREDIT'}</span>
            </div>
          )}
          {note.credit_granted_by_name && (
            <div className={styles.metaRow}>
              <span className={styles.metaLabel}>Credit granted by</span>
              <span className={styles.metaValue}>{note.credit_granted_by_name}</span>
            </div>
          )}
          {note.debt_due_date && (
            <div className={styles.metaRow}>
              <span className={styles.metaLabel}>Debt payment date</span>
              <span className={styles.metaValue}>{note.debt_due_date}</span>
            </div>
          )}
        </div>
      )}

      <table className={styles.table}>
        <thead>
          <tr>
            <th>#</th>
            <th>Carton tag</th>
            <th className={styles.right}>Collected (✓)</th>
          </tr>
        </thead>
        <tbody>
          {note.carton_tags.map((tag, i) => (
            <tr key={tag}>
              <td className={styles.mono}>{i + 1}</td>
              <td className={styles.mono}>{tag}</td>
              <td className={styles.right} style={{ width: 90 }}>☐</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Four named sign-off lines, matching the paper form exactly: the
          customer's rep (self or delegate) with a phone line, then three
          staff signatories. Blank at issuance time — this print view is the
          document staff hand over before pickup, not a post-pickup receipt,
          so none of these names are known yet; the equivalent filled-in
          values live in the pickup record shown on the detail page instead. */}
      <div className={styles.signatures}>
        <div className={styles.sigLine}>Customer's Rep — name, signature &amp; date</div>
        <div className={styles.sigLine}>Tel.</div>
        <div className={styles.sigLine}>Customer Service Officer — name, signature &amp; date</div>
        <div className={styles.sigLine}>Accounting Officer — name, signature &amp; date</div>
        <div className={styles.sigLine}>Warehouse Attendant — name, signature &amp; date</div>
      </div>

      <p className={styles.footNote} style={{ fontWeight: 700, textAlign: 'center' }}>
        All goods released must be confirmed by the customer before leaving our warehouse — management will not be
        held responsible for any shortage or damage thereafter.
      </p>

      <PrintBrandFoot branding={branding} />
      <p className={styles.footNote}>
        Present this note with a valid ID at the warehouse. Delegates must carry the delegate details recorded
        at issue. Generated by ShipX on{' '}
        {formatDate(new Date(), 'long')} · {note.reference_number}
      </p>
    </div>
  )
}
