import { describe, expect, it } from 'vitest'
import {
  canAdvanceContainerStatus,
  containerAdvanceRequirementHint,
  nextContainerStatus,
} from './containerRules'

describe('nextContainerStatus', () => {
  it('walks the 8-stage pipeline in order', () => {
    expect(nextContainerStatus('loading')).toBe('sealed')
    expect(nextContainerStatus('sealed')).toBe('in_transit')
    expect(nextContainerStatus('cleared')).toBe('at_warehouse')
    expect(nextContainerStatus('at_warehouse')).toBe('fully_released')
  })

  it('is null at the terminal stage', () => {
    expect(nextContainerStatus('fully_released')).toBeNull()
  })
})

describe('canAdvanceContainerStatus', () => {
  it('lets china_office_staff advance china-owned stages', () => {
    expect(canAdvanceContainerStatus('china_office_staff', 'loading')).toBe(true)
    expect(canAdvanceContainerStatus('china_office_staff', 'sealed')).toBe(true)
  })

  it('blocks nigeria_office_staff from china-owned stages', () => {
    expect(canAdvanceContainerStatus('nigeria_office_staff', 'loading')).toBe(false)
  })

  it('lets nigeria_office_staff advance nigeria-owned stages', () => {
    expect(canAdvanceContainerStatus('nigeria_office_staff', 'in_transit')).toBe(true)
    expect(canAdvanceContainerStatus('nigeria_office_staff', 'cleared')).toBe(true)
  })

  it('blocks china_office_staff from nigeria-owned stages', () => {
    expect(canAdvanceContainerStatus('china_office_staff', 'in_transit')).toBe(false)
  })

  it('reserves at_warehouse->fully_released for tenant_admin and warehouse_attendant', () => {
    expect(canAdvanceContainerStatus('warehouse_attendant', 'at_warehouse')).toBe(true)
    expect(canAdvanceContainerStatus('tenant_admin', 'at_warehouse')).toBe(true)
    expect(canAdvanceContainerStatus('china_office_staff', 'at_warehouse')).toBe(false)
    expect(canAdvanceContainerStatus('nigeria_office_staff', 'at_warehouse')).toBe(false)
  })

  it('tenant_admin can advance any owned stage', () => {
    expect(canAdvanceContainerStatus('tenant_admin', 'loading')).toBe(true)
    expect(canAdvanceContainerStatus('tenant_admin', 'cleared')).toBe(true)
  })

  it('nothing can advance the terminal stage', () => {
    expect(canAdvanceContainerStatus('tenant_admin', 'fully_released')).toBe(false)
  })
})

describe('containerAdvanceRequirementHint', () => {
  it('flags the sealed and in_transit pre-transition guards', () => {
    expect(containerAdvanceRequirementHint('sealed')).toMatch(/approved packing list/i)
    expect(containerAdvanceRequirementHint('in_transit')).toMatch(/ship date/i)
  })

  it('has no extra requirement for the rest', () => {
    expect(containerAdvanceRequirementHint('arrived')).toBeNull()
  })
})
