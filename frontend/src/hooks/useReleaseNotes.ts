import { useQuery } from '@tanstack/react-query'
import { releaseNotesApi, type ReleaseNoteListParams } from '../api/releaseNotes'
import { releaseNoteKeys } from '../api/keys'
import { STALE_30S, STALE_5_MIN } from '../lib/queryClient'
import { useCursorPagination } from './useCursorPagination'

export function useReleaseNoteList(params: ReleaseNoteListParams = {}) {
  return useCursorPagination(
    releaseNoteKeys.list(params as Record<string, unknown>),
    (cursor) => releaseNotesApi.list({ ...params, cursor }),
  )
}

/** One release note. Shares its cache entry with the detail page, so the print view opens instantly from it. */
export function useReleaseNote(id: string) {
  return useQuery({
    queryKey: releaseNoteKeys.detail(id),
    queryFn: () => releaseNotesApi.get(id),
    enabled: !!id,
    staleTime: STALE_30S,
  })
}

/** Per-status counts for the release-note list's stats row. A child of `releaseNoteKeys.all`, so a pickup refreshes it. */
export function useReleaseNoteStats() {
  return useQuery({ queryKey: releaseNoteKeys.stats(), queryFn: () => releaseNotesApi.stats(), staleTime: STALE_5_MIN })
}
