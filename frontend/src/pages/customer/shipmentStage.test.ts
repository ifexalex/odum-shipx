import { describe, expect, it } from 'vitest'
import { activeSummary, arrivalLabel, shipmentStage } from './shipmentStage'

const TODAY = '2026-11-21'

describe('shipment stage by container status (FD-27)', () => {
  it.each([
    ['loading', 'in_transit'],
    ['sealed', 'in_transit'],
    ['in_transit', 'in_transit'],
    ['arrived', 'in_transit'],
    ['customs_clearance', 'in_transit'],
    ['cleared', 'in_transit'],
    ['at_warehouse', 'ready_for_pickup'],
    ['fully_released', 'complete'],
    ['cancelled', 'complete'],
  ])('%s is %s', (status, stage) => {
    expect(shipmentStage(status)).toBe(stage)
  })

  it('counts only what is really on its way as in transit', () => {
    expect(activeSummary(['in_transit', 'sealed', 'loading', 'at_warehouse', 'at_warehouse'])).toBe(
      '3 in transit, 2 ready for pickup',
    )
    expect(activeSummary(['at_warehouse'])).toBe('1 ready for pickup')
    expect(activeSummary(['fully_released'])).toBeNull()
  })
})

describe('arrival label by container status (FD-27)', () => {
  it.each(['loading', 'sealed', 'in_transit'])('%s with a future date: Expected arrival', (status) => {
    expect(arrivalLabel(status, '2026-12-09', TODAY)?.label).toBe('Expected arrival')
  })

  it.each(['loading', 'sealed', 'in_transit'])('%s with a past date: Delayed, not a stale expectation', (status) => {
    const label = arrivalLabel(status, '2026-09-09', TODAY)
    expect(label?.label).toBe('Delayed')
    expect(label?.detail).toMatch(/^Was expected /)
  })

  it.each(['arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released'])(
    '%s: Arrived, with no expected date',
    (status) => {
      expect(arrivalLabel(status, '2026-09-09', TODAY)).toEqual({ label: 'Arrived', detail: null })
    },
  )

  it('shows nothing before a date is known', () => {
    expect(arrivalLabel('loading', null, TODAY)).toBeNull()
  })
})
