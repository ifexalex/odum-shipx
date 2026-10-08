import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KolaMark } from './KolaMark'

describe('KolaMark', () => {
  it('renders an svg sized to the requested px', () => {
    const { container } = render(<KolaMark size={48} />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('width')).toBe('48')
    expect(svg?.getAttribute('height')).toBe('48')
  })

  it('renders without throwing at the 16px–64px range', () => {
    for (const size of [16, 24, 32, 48, 64]) {
      const { unmount } = render(<KolaMark size={size} />)
      unmount()
    }
  })

  it('accepts a custom color', () => {
    const { container } = render(<KolaMark color="#2dc438" />)
    expect(container.querySelector('svg')?.getAttribute('fill')).toBe('#2dc438')
  })
})
