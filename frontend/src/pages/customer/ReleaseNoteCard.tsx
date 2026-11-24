import { useQuery } from '@tanstack/react-query'
import type { JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { releaseNoteKeys } from '../../api/keys'
import { releaseNotesApi } from '../../api/releaseNotes'
import { } from '../../api/releaseNotesRules'
import { Button, Card, Mono, StatusBadge, ErrorState } from '../../design/components'
import { STALE_30S } from '../../lib/queryClient'
import { SectionHead } from '../../shell/SectionHead'

/**
 * "Your release note", for a customer's invoice or shipment page, once one exists for that container.
 *
 * Renders nothing until then, and on any failure: it is a convenience on a page that already works, and a
 * customer with no note yet has nothing to be told. The list is already scoped to the signed-in customer.
 */
export function ReleaseNoteCard({ containerId }: { containerId: string | null | undefined }): JSX.Element | null {
  const navigate = useNavigate()
  const { data, error, refetch } = useQuery({
    queryKey: releaseNoteKeys.lookup({ container_id: containerId }),
    queryFn: () => releaseNotesApi.list({ container_id: containerId! }),
    enabled: !!containerId,
    staleTime: STALE_30S,
  })
  // Not hidden when the load fails (FD-53): this is the note a customer shows to collect their goods, so a failure
  // says so with a retry instead of looking like "no release note yet".
  if (error) {
    return (
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <ErrorState compact title="Couldn't load your release notes" error={error} onRetry={() => void refetch()} />
      </div>
    )
  }
  const notes = data?.data ?? []
  if (notes.length === 0) return null

  return (
    <Card padding="none" style={{ marginBottom: 'var(--space-4)' }}>
      <div
        style={{
          padding: 'var(--space-4) var(--space-5)',
          background: 'var(--color-surface-muted)',
          borderBottom: '1px solid var(--color-line-soft)',
          borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
        }}
      >
        <SectionHead
          title={notes.length === 1 ? 'Your release note' : 'Your release notes'}
          sub="Show it at the warehouse to collect your goods."
        />
      </div>
      <div>
        {notes.map((note, idx) => (
          <div
            key={note.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 'var(--space-3)',
              flexWrap: 'wrap',
              padding: 'var(--space-3) var(--space-5)',
              borderTop: idx > 0 ? '1px solid var(--color-line-soft)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <Mono color="var(--color-ink)">{note.reference_number}</Mono>
              <StatusBadge kind="releaseNote" status={note.status} audience="customer" />
            </div>
            <Button variant="secondary" size="sm" trailingIcon="arrowright" onClick={() => navigate(`/my-release-notes/${note.id}`)}>
              Open
            </Button>
          </div>
        ))}
      </div>
    </Card>
  )
}
