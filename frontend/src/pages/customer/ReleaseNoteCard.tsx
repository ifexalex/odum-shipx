import { useQuery } from '@tanstack/react-query'
import type { JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { releaseNoteKeys } from '../../api/keys'
import { releaseNotesApi } from '../../api/releaseNotes'
import { releaseNoteStatusLabel } from '../../api/releaseNotesRules'
import { Badge, Button, Card, Mono } from '../../design/components'
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
  const { data } = useQuery({
    queryKey: releaseNoteKeys.lookup({ container_id: containerId }),
    queryFn: () => releaseNotesApi.list({ container_id: containerId! }),
    enabled: !!containerId,
    staleTime: STALE_30S,
  })
  const notes = data?.data ?? []
  if (notes.length === 0) return null

  return (
    <Card padding={20} style={{ marginBottom: 16 }}>
      <SectionHead
        title={notes.length === 1 ? 'Your release note' : 'Your release notes'}
        sub="Show it at the warehouse to collect your goods."
      />
      {notes.map((note) => (
        <div
          key={note.id}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', paddingTop: 12 }}
        >
          <div>
            <Mono color="var(--color-ink)">{note.reference_number}</Mono>{' '}
            <Badge variant={note.status === 'active' ? 'success' : note.status === 'expired' ? 'error' : 'neutral'}>
              {releaseNoteStatusLabel(note.status)}
            </Badge>
          </div>
          <Button variant="secondary" size="sm" onClick={() => navigate(`/my-release-notes/${note.id}`)}>
            Open
          </Button>
        </div>
      ))}
    </Card>
  )
}
