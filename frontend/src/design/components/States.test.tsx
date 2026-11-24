/**
 * FD-20: empty, loading and error states say what is going on and what to do next.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LinesSkeleton, PageSkeleton } from './Skeleton'

const apiError = (status: number, detail: string, requestId: string | null = 'req-42'): ApiError =>
  new ApiError({ type: 'about:blank', title: 'x', status, detail, error_code: 'X' }, requestId)

describe('EmptyState', () => {
  it('on first use, offers the next step', () => {
    render(
      <MemoryRouter>
        <EmptyState
          title="No warehouses yet"
          body="Add one so packing lists can name it."
          action={{ label: 'Add a warehouse', to: '/admin/config/warehouses' }}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('No warehouses yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add a warehouse' })).toHaveAttribute(
      'href',
      '/admin/config/warehouses',
    )
  })

  it('with no results, offers to clear the filters', async () => {
    const clear = vi.fn()
    render(<EmptyState title="No invoices match these filters" onClearFilters={clear} />)
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(clear).toHaveBeenCalledOnce()
  })
})

describe('ErrorState', () => {
  it('shows plain words, a retry, and the reference — never the server text for a system error', async () => {
    const retry = vi.fn()
    render(
      <ErrorState
        title="Couldn't load this invoice"
        error={apiError(
          403,
          'Insufficient permissions for this operation. Required role: platform_admin',
        )}
        onRetry={retry}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent("You don't have permission to do this.")
    expect(screen.queryByText(/platform_admin/)).toBeNull()
    expect(screen.getByText('Reference: req-42')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it("keeps a business rule's own words", () => {
    render(
      <ErrorState title="Couldn't save" error={apiError(422, 'The file is larger than 5 MB.')} />,
    )
    expect(screen.getByText('The file is larger than 5 MB.')).toBeInTheDocument()
  })
})

describe('skeletons', () => {
  it('announce what is loading, once, and hide their shapes', () => {
    render(
      <>
        <PageSkeleton kind="detail" label="Loading invoice" />
        <LinesSkeleton label="Loading templates" />
      </>,
    )
    expect(screen.getByRole('status', { name: 'Loading invoice' })).toHaveAttribute(
      'aria-busy',
      'true',
    )
    expect(screen.getByRole('status', { name: 'Loading templates' })).toBeInTheDocument()
  })
})
