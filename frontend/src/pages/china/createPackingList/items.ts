import { type KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { PackingListItemInput } from '../../../api/packingList'

/** Turn an expanded batch back into the one line that produced it.
 *
 *  The API returns a bulk line already expanded — 100 rows for `quantity: 100`
 *  — because that is what it stores. Rendering those 100 rows is what "the
 *  quantity is not being retained" looked like from the warehouse: you type one
 *  line, save, reopen, and get a hundred rows back with the number you entered
 *  nowhere on screen.
 *
 *  Collapsing is lossless: the server re-expands on save from the same
 *  `batch_ref`, so the round trip reproduces the identical rows rather than
 *  duplicating cargo.
 *
 *  Only collapsed when every row in the group still matches. If one package of
 *  a batch was edited directly, the rows stay expanded — folding them would
 *  silently discard that edit, which is worse than showing more rows than
 *  expected.
 */
export function collapseBatches(items: PackingListItemInput[]): PackingListItemInput[] {
  const out: PackingListItemInput[] = []
  const seen = new Set<string>()

  for (const item of items) {
    const ref = item.batch_ref
    if (!ref) {
      out.push(item)
      continue
    }
    if (seen.has(ref)) continue
    seen.add(ref)

    const group = items.filter((other) => other.batch_ref === ref)
    const matchesFirst = (other: PackingListItemInput): boolean =>
      other.description === item.description &&
      other.package_unit === item.package_unit &&
      other.length_cm === item.length_cm &&
      other.width_cm === item.width_cm &&
      other.height_cm === item.height_cm &&
      other.weight_dispatch_kg === item.weight_dispatch_kg &&
      other.weight_actual_kg === item.weight_actual_kg &&
      other.declared_value_usd === item.declared_value_usd &&
      other.received_date === item.received_date

    if (group.length > 1 && group.every(matchesFirst)) {
      out.push({ ...item, quantity: group.length, identical_confirmed: true })
    } else {
      out.push(...group)
    }
  }
  return out
}

/** Keep a typed quantity at or above 1, tolerating an emptied field (no upper cap — container CBM capacity guards the total). */
export function clampQuantity(raw: string): number | undefined {
  // An emptied field stays empty rather than snapping to 1. Coercing it meant
  // clearing the box left a "1" behind, so typing "40" produced 140 — caught
  // by a test, and it would have been a daily irritation in the warehouse.
  // `undefined` reads as one package everywhere (see qtyOf).
  if (raw.trim() === '') return undefined
  const n = Number.parseInt(raw, 10)
  if (!Number.isFinite(n)) return undefined
  return Math.max(n, 1)
}

export function emptyItem(): PackingListItemInput {
  return { description: '', package_unit: 'carton' }
}

// Numeric cell helpers: these fields are quantities (weights, dimensions,
// value) — never negative and never alphabetic. type="number" alone still
// lets the user type 'e'/'+'/'-'; block those keys and reject any parsed
// value that isn't a non-negative finite number.
export function blockInvalidNumberKeys(e: ReactKeyboardEvent<HTMLInputElement>): void {
  if (['e', 'E', '+', '-'].includes(e.key)) e.preventDefault()
}

export function sanitizeNumber(raw: string): number | undefined {
  if (raw.trim() === '') return undefined
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0) return undefined
  return n
}
