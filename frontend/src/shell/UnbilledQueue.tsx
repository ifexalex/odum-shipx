import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { billingApi } from '../api/billing'
import { groupUnbilledByContainer } from '../api/billingRules'
import { ApiError } from '../api/client'
import { billingKeys } from '../api/keys'
import { Banner, Button, Card, Mono, Table } from '../design/components'
import { STALE_30S } from '../lib/queryClient'
import { SectionHead } from './SectionHead'
import styles from './UnbilledQueue.module.css'

function customersLabel(names: string[]): string {
  if (names.length <= 3) return names.join(', ')
  return `${names.slice(0, 3).join(', ')} +${names.length - 3} more`
}

/**
 * Customers on a cleared container who have cargo to bill and no invoice.
 *
 * Clearing a container invoices everyone on it, but a customer can be skipped (rates not
 * set yet) or fail transiently. This queue is how that is found again later, instead of
 * the customer simply never being billed. Renders nothing when there is nothing to do.
 * "Generate invoices" is idempotent, so pressing it twice is harmless.
 */
export function UnbilledQueue(): JSX.Element | null {
  const navigate = useNavigate()
  const [busyContainer, setBusyContainer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const unbilledQ = useQuery({
    queryKey: billingKeys.unbilled(),
    queryFn: () => billingApi.unbilled(),
    staleTime: STALE_30S,
  })

  const groups = useMemo(() => groupUnbilledByContainer(unbilledQ.data ?? []), [unbilledQ.data])
  if (groups.length === 0) return null

  async function generate(containerId: string): Promise<void> {
    setBusyContainer(containerId)
    setError(null)
    try {
      // A successful POST /v1/billing refreshes every billing query, this one included.
      await billingApi.generateForContainer(containerId)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate the invoices.')
    } finally {
      setBusyContainer(null)
    }
  }

  return (
    <div className={styles.wrap}>
      <Card padding={0}>
        <div className={styles.header}>
          <SectionHead
            title="Customers not invoiced"
            sub="On cleared containers, with cargo to bill. Generate the invoice, or open the container."
          />
        </div>
        {error && (
          <div className={styles.error}>
            <Banner variant="error" title="Could not generate">
              {error}
            </Banner>
          </div>
        )}
        <Table
          dense
          cardBreakpoint={600}
          columns={[{ title: 'Container' }, { title: 'Customers' }, { title: '', width: '260px' }]}
          rows={groups.map((group) => ({
            cells: [
              <Mono key="container">{group.containerNumber}</Mono>,
              <span key="customers" className={styles.customers}>
                {customersLabel(group.customers.map((c) => c.name))}
              </span>,
              <span key="actions">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busyContainer === group.containerId}
                  onClick={() => void generate(group.containerId)}
                >
                  Generate invoices
                </Button>{' '}
                <Button variant="ghost" size="sm" onClick={() => navigate(`/containers/${group.containerId}`)}>
                  Open container
                </Button>
              </span>,
            ],
          }))}
        />
      </Card>
    </div>
  )
}
