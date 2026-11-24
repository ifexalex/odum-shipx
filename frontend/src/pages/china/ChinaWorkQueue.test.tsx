import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { disputeApi } from '../../api/billing'
import { manifestApi } from '../../api/manifest'
import { packingListApi } from '../../api/packingList'
import { withQuery } from '../../test/queryWrapper'
import { ChinaWorkQueue } from './ChinaWorkQueue'

vi.mock('../../api/packingList', () => ({ packingListApi: { list: vi.fn() } }))
vi.mock('../../api/manifest', () => ({ manifestApi: { list: vi.fn() } }))
vi.mock('../../api/billing', () => ({ disputeApi: { list: vi.fn() }, billingApi: { list: vi.fn() } }))

const page = <T,>(data: T[], total = data.length) => ({
  data,
  meta: { pagination: { has_more: total > data.length, next_cursor: null, total_count: total } },
})

function Where(): JSX.Element {
  const location = useLocation()
  return <div data-testid="where">{location.pathname + location.search}</div>
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter initialEntries={['/work-queue']}>
        <>
          <Routes>
            <Route path="/work-queue" element={<ChinaWorkQueue />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </>
      </MemoryRouter>,
    ),
  )
}

beforeEach(() => {
  vi.mocked(packingListApi.list).mockReset()
  vi.mocked(manifestApi.list).mockReset().mockResolvedValue(page([]) as never)
  vi.mocked(disputeApi.list).mockReset().mockResolvedValue(page([]) as never)
  vi.mocked(packingListApi.list).mockImplementation(async (params) =>
    params?.status === 'rejected'
      ? (page(
          [{ id: 'pl1', reference: 'PL-0042', customer_name: 'Ngozi', container_number: 'MSCU1', updated_at: '2026-11-16T10:00:00Z' }],
          7,
        ) as never)
      : (page([]) as never),
  )
})

describe('ChinaWorkQueue (audit UX-10)', () => {
  it('reads each queue from its list endpoint with the right filter', async () => {
    renderPage()
    await waitFor(() => expect(disputeApi.list).toHaveBeenCalled())
    expect(packingListApi.list).toHaveBeenCalledWith(expect.objectContaining({ status: 'rejected' }))
    expect(packingListApi.list).toHaveBeenCalledWith(expect.objectContaining({ status: 'draft' }))
    expect(manifestApi.list).toHaveBeenCalledWith(expect.objectContaining({ verification_status: 'pending' }))
    expect(disputeApi.list).toHaveBeenCalledWith(expect.objectContaining({ status: 'escalated_china' }))
  })

  it('shows the full count, the first rows, and an empty message where there is nothing', async () => {
    renderPage()
    const rejected = await screen.findByRole('region', { name: 'Rejected packing lists' })
    expect(await within(rejected).findByText('7 to revise and resubmit')).toBeInTheDocument()
    expect(within(rejected).getByText('PL-0042')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Drafts not submitted' })).getByText('No drafts waiting.')).toBeInTheDocument()
  })

  it.each([
    ['Rejected packing lists', '/packing-lists?status=rejected'],
    ['Drafts not submitted', '/packing-lists?status=draft'],
    ['Manifests awaiting verification', '/manifests?status=pending'],
    ['Disputes escalated to China', '/billing/disputes?status=escalated_china'],
  ])('%s links to its filtered list', async (queue, url) => {
    renderPage()
    const region = await screen.findByRole('region', { name: queue })
    await userEvent.click(within(region).getByRole('button', { name: 'View all' }))
    expect(screen.getByTestId('where')).toHaveTextContent(url)
  })

  it('opens a row', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('link', { name: /PL-0042/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/packing-lists/pl1')
  })

  it('says so when a queue fails, and still shows the others', async () => {
    vi.mocked(manifestApi.list).mockRejectedValue(new Error('down'))
    renderPage()
    const manifests = await screen.findByRole('region', { name: 'Manifests awaiting verification' })
    expect(await within(manifests).findByText('This queue could not be loaded.')).toBeInTheDocument()
    expect(await screen.findByText('PL-0042')).toBeInTheDocument()
  })

  it('counts the rows when an endpoint reports no total, with + when there are more', async () => {
    // The manifest and dispute lists return has_more but no total_count.
    vi.mocked(manifestApi.list).mockResolvedValue({
      data: [{ id: 'm1', container_number: 'MSCU9', total_customers: 3, total_cartons: 40 }],
      meta: { pagination: { has_more: true, next_cursor: 'c' } },
    } as never)
    vi.mocked(disputeApi.list).mockResolvedValue({
      data: [{ id: 'd1', container_number: 'MSCU7', customer_name: 'Ada', submitted_at: '2026-11-15T09:00:00Z' }],
      meta: { pagination: { has_more: false, next_cursor: null } },
    } as never)
    renderPage()
    const manifests = await screen.findByRole('region', { name: 'Manifests awaiting verification' })
    expect(await within(manifests).findByText('1+ not yet verified in Nigeria')).toBeInTheDocument()
    const disputes = screen.getByRole('region', { name: 'Disputes escalated to China' })
    expect(await within(disputes).findByText('1 need a measurement answer')).toBeInTheDocument()
  })
})

