import { releaseNotesApi, type ReleaseNoteListParams } from '../api/releaseNotes'
import { releaseNoteKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useReleaseNoteList(params: ReleaseNoteListParams = {}) {
  return useCursorPagination(
    releaseNoteKeys.list(params as Record<string, unknown>),
    (cursor) => releaseNotesApi.list({ ...params, cursor }),
  )
}
