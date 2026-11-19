// Shared formatter for DECIMAL-backed API fields. shared/responses.py's
// json.dumps(body, default=str) has no native Decimal encoder, so every
// DECIMAL column (packing_list.total_cbm, manifest.total_cbm, etc.)
// serializes as a string on the wire — never a number. Components must
// route through this helper instead of calling .toFixed() directly.
//
// The implementation lives with the other display formatters in lib/format.ts.
export { formatCbm } from '../lib/format'
