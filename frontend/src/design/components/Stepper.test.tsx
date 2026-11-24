import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Stepper, type StepperStep } from './Stepper'

const STEPS: StepperStep[] = [
  { key: 'a', label: 'Loading', sub: 'China warehouse', tone: 'china' },
  { key: 'b', label: 'In transit', sub: 'At sea', tone: 'china' },
  { key: 'c', label: 'Arrived in Nigeria', tone: 'nigeria' },
  { key: 'd', label: 'Fully released', tone: 'nigeria' },
]

function stubWidth(width: number): void {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width,
    height: 80,
    top: 0,
    left: 0,
    right: width,
    bottom: 80,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}

const item = (name: string): HTMLElement => screen.getByText(name).closest('li')!

describe('Stepper (FD-09)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('is a named list with the current step marked and the rest stated', () => {
    render(<Stepper steps={STEPS} current={1} label="Container progress" />)
    const list = screen.getByRole('list', { name: 'Container progress' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(4)
    expect(item('Loading')).toHaveTextContent(/done/)
    expect(item('In transit')).toHaveAttribute('aria-current', 'step')
    expect(item('Arrived in Nigeria')).toHaveTextContent(/not started/)
  })

  it('marks every step done when the pipeline is complete', () => {
    render(<Stepper steps={STEPS} current={3} complete label="Container progress" />)
    for (const s of STEPS) expect(item(s.label)).toHaveTextContent(/done/)
    expect(screen.queryByRole('listitem', { current: 'step' })).toBeNull()
  })

  it('shows where a refused process stopped', () => {
    render(<Stepper steps={STEPS} current={1} failed label="Refund progress" />)
    expect(item('In transit')).toHaveAttribute('aria-current', 'step')
    expect(item('In transit')).toHaveTextContent(/stopped here/)
  })

  it('numbers the steps in wizard mode', () => {
    render(<Stepper mode="wizard" steps={STEPS} current={0} label="Form steps" />)
    expect(screen.getByText('Step 2')).toBeInTheDocument()
    expect(item('In transit')).toHaveTextContent('2')
  })

  it('collapses to the current step, its position and a bar when narrow', () => {
    stubWidth(390)
    render(<Stepper steps={STEPS} current={1} label="Shipment progress" />)
    expect(screen.queryByRole('list')).toBeNull()
    expect(screen.getByText('In transit')).toBeInTheDocument()
    expect(screen.getByText('2 of 4')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Shipment progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '1')
    expect(bar).toHaveAttribute('aria-valuetext', 'In transit, 2 of 4')
  })

  it('stays in the full form above 600 px', () => {
    stubWidth(601)
    render(<Stepper steps={STEPS} current={1} label="Shipment progress" />)
    expect(screen.getByRole('list', { name: 'Shipment progress' })).toBeInTheDocument()
  })
})
