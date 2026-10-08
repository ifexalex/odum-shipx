import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatCard } from './StatCard'

describe('StatCard', () => {
  it('renders label, value, and suffix', () => {
    render(<StatCard label="Active containers" value={42} suffix="units" />)
    expect(screen.getByText('Active containers')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('units')).toBeInTheDocument()
  })

  it('renders an upward trend and sublabel', () => {
    render(
      <StatCard
        label="Revenue"
        value="₦1.2M"
        trend={{ direction: 'up', pct: 12 }}
        sublabel="vs last month"
      />,
    )
    expect(screen.getByText('12%')).toBeInTheDocument()
    expect(screen.getByText('vs last month')).toBeInTheDocument()
  })

  it('renders a downward trend', () => {
    render(<StatCard label="Disputes" value={3} trend={{ direction: 'down', pct: 5 }} />)
    expect(screen.getByText('5%')).toBeInTheDocument()
  })

  it('renders the icon slot when icon is provided', () => {
    const { container } = render(<StatCard label="Containers" value={10} icon="container" />)
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
