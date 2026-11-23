import { applyMinCbm, computeCbm } from '../../../api/packingListRules'
import { BULK_CONFIRM_THRESHOLD, type PackingListItemInput } from '../../../api/packingList'
import { type CbmRateCurrency } from '../../../api/tenantManagement'
import { useCbmRate, useDollarRate } from '../../../hooks/useConfig'

/**
 * Pricing for the packing-list wizard: the tenant's CBM and dollar rates, per-line CBM and quantity, the totals, the
 * lines big enough to confirm, and the live shipping estimate in USD and NGN.
 */
export function usePackingListPricing(items: PackingListItemInput[]) {
  // Tenant rates for the live pricing estimate (Step 2), re-read when the form opens. Null until fetched or if the
  // current role can't read them — the pricing card degrades to "—"; pricing is a non-blocking nicety. This wizard
  // doesn't collect a per-item package type, so it can only ever estimate with one representative rate — carton_rate,
  // the same rate any unrecognized package type bills at (shared/cbm_rate.py).
  const cbmRateQuery = useCbmRate({ freshOnOpen: true })
  const dollarRateQuery = useDollarRate({ freshOnOpen: true })
  const cbmRate: number | null = cbmRateQuery.data?.carton_rate ?? null
  const cbmCurrency: CbmRateCurrency = cbmRateQuery.data?.currency ?? 'usd'
  const fxRate: number | null = dollarRateQuery.data?.rate ?? null
  // Minimum billable CBM per item (tenant setting) — tiny parcels are floored to this value, mirroring the backend,
  // so the wizard shows the real value.
  const tenantMinCbm = cbmRateQuery.data?.min_cbm_per_item ?? 0
  const minCbm = tenantMinCbm > 0 ? tenantMinCbm : 0.1

  // Raw CBM from dimensions (0 when incomplete); the billable value floors it.
  function rawCbm(item: PackingListItemInput): number {
    return item.length_cm != null && item.width_cm != null && item.height_cm != null
      ? computeCbm(item.length_cm, item.width_cm, item.height_cm)
      : 0
  }

  /** Packages this line stands for. The server expands a quantity line into
   *  this many rows, so every total below must scale by it. */
  function qtyOf(item: PackingListItemInput): number {
    const q = item.quantity ?? 1
    return Number.isFinite(q) && q > 0 ? Math.floor(q) : 1
  }

  // Multiplied by quantity throughout. These totals are the real safeguard: a
  // quantity typed as 1000 instead of 100 is hard to see in the input and
  // impossible to miss in the CBM and the live shipping price beneath it.
  const totals = items.reduce(
    (acc, item) => {
      const q = qtyOf(item)
      return {
        cartons: acc.cartons + q,
        weightDispatch: acc.weightDispatch + (item.weight_dispatch_kg ?? 0) * q,
        weight: acc.weight + (item.weight_actual_kg ?? 0) * q,
        // Floored per package, matching the server: it applies the minimum to
        // each expanded row, not once to the line.
        cbm: acc.cbm + applyMinCbm(rawCbm(item), minCbm) * q,
        declaredUsd: acc.declaredUsd + (item.declared_value_usd ?? 0) * q,
      }
    },
    { cartons: 0, weightDispatch: 0, weight: 0, cbm: 0, declaredUsd: 0 },
  )

  /** Lines whose quantity is large enough to warrant a second look on save. */
  const bulkLines = items
    .map((item, index) => ({ item, index, qty: qtyOf(item) }))
    .filter(({ qty }) => qty >= BULK_CONFIRM_THRESHOLD)

  // Live pricing: CBM × rate, in whichever currency the tenant configured —
  // then derive the other currency's tile via the FX rate. Null rates
  // degrade to "—".
  const cbmCharge = cbmRate != null ? totals.cbm * cbmRate : null
  const shippingUsd =
    cbmCharge == null
      ? null
      : cbmCurrency === 'usd'
        ? cbmCharge
        : fxRate != null
          ? cbmCharge / fxRate
          : null
  const shippingNgn =
    cbmCharge == null
      ? null
      : cbmCurrency === 'ngn'
        ? cbmCharge
        : fxRate != null
          ? cbmCharge * fxRate
          : null

  return {
    cbmRateQuery,
    dollarRateQuery,
    cbmRate,
    cbmCurrency,
    fxRate,
    tenantMinCbm,
    minCbm,
    rawCbm,
    qtyOf,
    totals,
    bulkLines,
    cbmCharge,
    shippingUsd,
    shippingNgn,
  }
}
