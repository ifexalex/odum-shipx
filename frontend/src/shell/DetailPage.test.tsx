import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DetailPage } from './DetailPage'
import { Section } from './Section'

describe('DetailPage and Section (FD-19)', () => {
  it('lays a record out as header, notices, progress, then sections beside the summary', () => {
    render(
      <DetailPage
        header={<h1>Invoice INV-A-002</h1>}
        notices={<p>Notice</p>}
        progress={<p>Stepper</p>}
        aside={<Section title="Summary">Totals</Section>}
      >
        <Section title="Invoice breakdown">Rows</Section>
      </DetailPage>,
    )
    const order = ['Invoice INV-A-002', 'Notice', 'Stepper'].map((t) => screen.getByText(t))
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    expect(screen.getByRole('complementary')).toHaveTextContent('Totals')
  })

  it('a section is a region named by its heading, the heading inside its card', () => {
    render(
      <Section title="Carton tags" sub="2 tags">
        <span>ACME-001</span>
      </Section>,
    )
    const region = screen.getByRole('region', { name: 'Carton tags' })
    expect(region.querySelector('[data-surface="card"] h2')).toHaveTextContent('Carton tags')
    expect(region).toHaveTextContent('ACME-001')
  })
})
