import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packingListApi, type PackingList } from '../../api/packingList'
import { withQuery } from '../../test/queryWrapper'
import { ShipmentDocumentsCard } from './ShipmentDocumentsCard'

function makePl(overrides: Partial<PackingList> = {}): PackingList {
  return {
    id: 'pl-1',
    tenant_id: 't-1',
    reference: 'PL-20261127-001',
    loading_receipt_number: 'LR-20261127-001',
    container_id: 'c-1',
    container_number: 'MSKU1234567',
    customer_id: 'cust-1',
    customer_name: 'Nne Gold',
    customer_phone: '+2348084907055',
    status: 'approved',
    items: [],
    total_cbm: '0.390',
    total_weight_kg: '25.0',
    carton_count: 2,
    created_by: 'u-1',
    approved_by: 'u-2',
    approved_at: '2026-11-27T10:00:00Z',
    rejected_by: null,
    rejected_at: null,
    approval_comments: null,
    created_at: '2026-11-27T09:00:00Z',
    updated_at: '2026-11-27T10:00:00Z',
    ...overrides,
  }
}

describe('ShipmentDocumentsCard (ENG-4 & ENG-5)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('defaults Loading Receipt to Chinese (zh) and Packing List to English (en) with independent downloads', async () => {
    const user = userEvent.setup()
    vi.spyOn(packingListApi, 'documents').mockResolvedValue({
      packing_list_id: 'pl-1',
      customer_phone: '+2348084907055',
      customer_whatsapp: '+2348084907055',
      loading_receipt: {
        available: true,
        reference: 'LR-20261127-001',
        lang: 'zh',
        page_count: 1,
        image_eligible: true,
        image_disabled_reason: null,
      },
      packing_list: {
        available: true,
        finalized: true,
        reference: 'PL-20261127-001',
        ship_date: '2026-11-10',
        estimated_arrival_date: '2026-12-25',
        lang: 'en',
        page_count: 1,
        image_eligible: true,
        image_disabled_reason: null,
      },
    })
    const lrPdfSpy = vi.spyOn(packingListApi, 'loadingReceiptPdf').mockResolvedValue()
    const plImgSpy = vi.spyOn(packingListApi, 'image').mockResolvedValue()

    render(withQuery(<ShipmentDocumentsCard packingList={makePl()} canShareWhatsApp />))

    await waitFor(() => {
      expect(screen.getByText('LR-20261127-001')).toBeInTheDocument()
    })

    const pdfButtons = screen.getAllByRole('button', { name: /Download PDF/i })
    const imgButtons = screen.getAllByRole('button', { name: /Download Image \(PNG\)/i })
    await user.click(pdfButtons[0]!)
    expect(lrPdfSpy).toHaveBeenCalledWith('pl-1', 'zh')

    await user.click(imgButtons[1]!)
    expect(plImgSpy).toHaveBeenCalledWith('pl-1', 'en')
  })

  it('disables Image export and shows the multi-page guardrail notice when page_count > 1', async () => {
    const reason =
      'Image export is disabled for multi-page documents (3 pages) to preserve readability. Please download and use the PDF version instead.'
    vi.spyOn(packingListApi, 'documents').mockResolvedValue({
      packing_list_id: 'pl-1',
      customer_phone: '+2348084907055',
      loading_receipt: {
        available: true,
        reference: 'LR-20261127-001',
        lang: 'zh',
        page_count: 3,
        image_eligible: false,
        image_disabled_reason: reason,
      },
      packing_list: {
        available: true,
        finalized: false,
        reference: 'PL-20261127-001',
        lang: 'en',
        page_count: 2,
        image_eligible: false,
        image_disabled_reason:
          'Image export is disabled for multi-page documents (2 pages) to preserve readability. Please download and use the PDF version instead.',
      },
    })

    render(withQuery(<ShipmentDocumentsCard packingList={makePl()} canShareWhatsApp />))

    await waitFor(() => {
      expect(screen.getByText(reason)).toBeInTheDocument()
    })

    const imgButtons = screen.getAllByRole('button', { name: /Download Image \(PNG\)/i })
    expect(imgButtons[0]).toBeDisabled()
    expect(imgButtons[1]).toBeDisabled()
    expect(screen.getByRole('button', { name: /Send on WhatsApp \(PDF · 3p\)/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Send on WhatsApp \(PDF · 2p\)/i })).toBeInTheDocument()
  })
})
