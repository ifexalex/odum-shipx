import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { releaseNotesApi } from '../../api/releaseNotes'
import { withQuery } from '../../test/queryWrapper'
import { ReleaseNoteCard } from './ReleaseNoteCard'

function renderCard() {
  return render(
    withQuery(
      <MemoryRouter>
        <ReleaseNoteCard containerId="c1" />
      </MemoryRouter>,
    ),
  )
}

describe('ReleaseNoteCard (FD-53)', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows nothing while the customer has no release note', async () => {
    const list = vi.spyOn(releaseNotesApi, 'list').mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    const { container } = renderCard()
    await vi.waitFor(() => expect(list).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('says a failed load failed, with a retry, rather than hiding the note', async () => {
    vi.spyOn(releaseNotesApi, 'list').mockRejectedValue(new Error('network down'))
    renderCard()
    expect(await screen.findByText("Couldn't load your release notes")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again|retry/i })).toBeInTheDocument()
  })
})
