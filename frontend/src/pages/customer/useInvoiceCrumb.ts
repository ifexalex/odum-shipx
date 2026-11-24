import { useQuery } from '@tanstack/react-query'
import { billingApi, type Billing } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

/**
 * Names the invoice in the breadcrumb of a page under it ("Billing / INV-0042 / Request a refund", FD-46). Reads the
 * same cache slot as the invoice page, so arriving from there costs no request, and returns the billing record for
 * context panels on child pages.
 */
export function useInvoiceCrumb(billingId: string | undefined): Billing | undefined {
  const { data: billing } = useQuery({
    queryKey: billingKeys.detail(billingId ?? ''),
    queryFn: () => billingApi.get(billingId!),
    enabled: !!billingId,
    staleTime: STALE_30S,
  })
  useBreadcrumbLabel(billing?.invoice_number, '/my-billing/:id')
  return billing
}
