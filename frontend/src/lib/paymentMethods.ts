/** Payment method labels (FD-13): one place says how `payment.payment_method` reads on screen. */

/** The payment methods staff can record (`payment.payment_method`), in the order the form offers them. */
export const PAYMENT_METHODS = ['bank_transfer', 'cash', 'online', 'card', 'other'] as const

const PAYMENT_METHOD_LABELS: Record<string, string> = {
  bank_transfer: 'Bank transfer',
  cash: 'Cash',
  online: 'Online',
  card: 'Card',
  other: 'Other',
}

/** How a payment method reads on screen: "Bank transfer", not "bank_transfer". Unknown values show as stored. */
export function paymentMethodLabel(method: string | null | undefined): string {
  if (!method) return '—'
  return PAYMENT_METHOD_LABELS[method] ?? method
}
