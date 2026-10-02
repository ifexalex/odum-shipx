import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AnnouncementBanner } from './AnnouncementBanner'

describe('AnnouncementBanner', () => {
  it('renders nothing when there is no banner', () => {
    const { container } = render(<AnnouncementBanner banner={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing while loading (undefined)', () => {
    const { container } = render(<AnnouncementBanner banner={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the title and body', () => {
    render(<AnnouncementBanner banner={{ id: 'a1', title: 'Office closed', body: 'Back Monday.' }} />)
    expect(screen.getByText('Office closed')).toBeInTheDocument()
    expect(screen.getByText('Back Monday.')).toBeInTheDocument()
  })

  it('renders with no body text when body is null', () => {
    render(<AnnouncementBanner banner={{ id: 'a1', title: 'Office closed', body: null }} />)
    expect(screen.getByText('Office closed')).toBeInTheDocument()
  })

  it('dismissing hides the banner', async () => {
    render(<AnnouncementBanner banner={{ id: 'a1', title: 'Office closed', body: null }} />)
    await userEvent.click(screen.getByRole('button', { name: /dismiss|close/i }))
    expect(screen.queryByText('Office closed')).toBeNull()
  })

  it('a different banner id shows again even after the previous one was dismissed', () => {
    const { rerender } = render(<AnnouncementBanner banner={{ id: 'a1', title: 'First', body: null }} />)
    rerender(<AnnouncementBanner banner={{ id: 'a2', title: 'Second', body: null }} />)
    expect(screen.getByText('Second')).toBeInTheDocument()
  })
})
