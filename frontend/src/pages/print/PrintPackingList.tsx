/**
 * 14.12 / F-B1 — Printable A4 packing list (prototype reports-screens.jsx:787).
 * Rendered outside the app shell (layout: 'none'); the toolbar disappears in
 * print. Reached from PackingListDetail's Print button.
 */
import { useEffect, useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { packingListApi, type PackingList } from '../../api/packingList'
import { buildPackageMix, formatPackageMix, packagesInRow, totalPackages } from '../../api/packingListRules'
import { Button } from '../../design/components'
import { useBranding } from '../../hooks/useConfig'
import { PrintBrandFoot, PrintBrandHead } from './PrintBrand'
import styles from './print.module.css'
import { formatDate } from '../../lib/format'

export function PrintPackingList(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [pl, setPl] = useState<PackingList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { branding } = useBranding()

  useEffect(() => {
    if (!id) return
    void (async () => {
      try {
        setPl(await packingListApi.get(id))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Could not load this packing list.')
      }
    })()
  }, [id])

  if (error) return <div className={styles.loading}>{error}</div>
  if (!pl) return <div className={styles.loading}>Preparing document…</div>

  const totalCbm = pl.items.reduce((s, i) => s + Number(i.cbm ?? 0), 0)
  const totalWeight = pl.items.reduce((s, i) => s + Number(i.weight_dispatch_kg ?? 0), 0)
  const totalWeightActual = pl.items.reduce((s, i) => s + Number(i.weight_actual_kg ?? 0), 0)

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate(`/packing-lists/${pl.id}`)}>
          Back
        </Button>
        <Button variant="primary" icon="file" onClick={() => window.print()}>
          Print / Save as PDF
        </Button>
      </div>

      <div className={styles.head}>
        <PrintBrandHead branding={branding} />
        <div style={{ textAlign: 'right' }}>
          <h1 className={styles.docTitle}>Packing List</h1>
          <div className={styles.docRef}>{pl.reference ?? pl.id}</div>
        </div>
      </div>

      <div className={styles.metaGrid}>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Customer</span>
          <span className={styles.metaValue}>{pl.customer_name ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Container</span>
          <span className={`${styles.metaValue} ${styles.mono}`}>{pl.container_number ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Status</span>
          <span className={styles.metaValue} style={{ textTransform: 'capitalize' }}>{pl.status.replace(/_/g, ' ')}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Created</span>
          <span className={styles.metaValue}>{formatDate(pl.created_at)}</span>
        </div>
        {/* Loading and delivery dates are captured on the form and were on no
            document at all, so the printed list could not answer when the
            cargo loads or lands — the two dates a customer actually asks
            about. The arrival warehouse is captured alongside them and was
            likewise absent. */}
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Loading date</span>
          <span className={styles.metaValue}>{pl.loading_date ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Delivery date</span>
          <span className={styles.metaValue}>{pl.delivery_date ?? '—'}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.metaLabel}>Arrival warehouse</span>
          <span className={styles.metaValue}>{pl.arrival_warehouse_name ?? '—'}</span>
        </div>
      </div>

      <table className={styles.table}>
        <thead>
          <tr>
            <th>#</th>
            <th>Carton tag</th>
            <th>Description</th>
            {/* Type and Qty were absent, so a printed list could not say
                whether a line was cartons or bales, nor how many packages it
                stood for — and for an imported manifest row, one line can mean
                fifty. Both are on the document now. */}
            <th>Type</th>
            <th className={styles.right}>Qty</th>
            <th className={styles.right}>Dimensions (cm)</th>
            <th className={styles.right}>CBM</th>
            <th className={styles.right}>Wt disp. (kg)</th>
            <th className={styles.right}>Wt act. (kg)</th>
            <th className={styles.right}>Received</th>
          </tr>
        </thead>
        <tbody>
          {pl.items.map((item, i) => (
            <tr key={item.id}>
              <td className={styles.mono}>{i + 1}</td>
              <td className={styles.mono}>{item.carton_tag ?? '—'}</td>
              <td>{item.description}</td>
              <td>{item.package_unit ?? '—'}</td>
              <td className={`${styles.right} ${styles.mono}`}>{packagesInRow(item)}</td>
              <td className={`${styles.right} ${styles.mono}`}>
                {item.length_cm && item.width_cm && item.height_cm
                  ? `${Number(item.length_cm)}×${Number(item.width_cm)}×${Number(item.height_cm)}`
                  : '—'}
              </td>
              <td className={`${styles.right} ${styles.mono}`}>{item.cbm ? Number(item.cbm).toFixed(3) : '—'}</td>
              <td className={`${styles.right} ${styles.mono}`}>{item.weight_dispatch_kg ? Number(item.weight_dispatch_kg).toFixed(1) : '—'}</td>
              <td className={`${styles.right} ${styles.mono}`}>{item.weight_actual_kg ? Number(item.weight_actual_kg).toFixed(1) : '—'}</td>
              <td className={`${styles.right} ${styles.mono}`}>{item.received_date ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className={styles.totals}>
        <div className={styles.totalsBox}>
          <div className={styles.metaRow}>
            {/* Was `pl.items.length`, which counts ROWS. A row has meant "N
                packages" since migration 040, so an imported manifest line of
                50 cartons printed as "Total cartons: 1". */}
            <span className={styles.metaLabel}>Total packages</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{totalPackages(pl.items)}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Package mix</span>
            <span className={styles.metaValue}>{formatPackageMix(buildPackageMix(pl.items))}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Total CBM</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{totalCbm.toFixed(3)}</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Total weight (dispatch)</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{totalWeight.toFixed(1)} kg</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaLabel}>Total weight (actual)</span>
            <span className={`${styles.metaValue} ${styles.mono}`}>{totalWeightActual.toFixed(1)} kg</span>
          </div>
        </div>
      </div>

      <div className={styles.signatures}>
        <div className={styles.sigLine}>Packed by (China Office)</div>
        <div className={styles.sigLine}>Approved by</div>
      </div>

      <PrintBrandFoot branding={branding} />
      <p className={styles.footNote}>
        Generated by ShipX on {formatDate(new Date(), 'long')} · {pl.reference ?? pl.id}
      </p>
    </div>
  )
}
