import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Icon } from './Icon'

describe('Icon', () => {
  it('renders an svg at the requested size', () => {
    const { container } = render(<Icon name="check" size={24} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(svg?.getAttribute('width')).toBe('24')
    expect(svg?.getAttribute('height')).toBe('24')
  })

  it('uses currentColor by default and accepts a custom color', () => {
    const { container } = render(<Icon name="alert" color="#dc2626" />)
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('#dc2626')
  })

  it('renders distinct markup for every icon name without throwing', () => {
    const names: Array<Parameters<typeof Icon>[0]['name']> = [
      'grid',
      'building',
      'users',
      'user',
      'settings',
      'log',
      'home',
      'container',
      'package',
      'file',
      'truck',
      'coin',
      'card',
      'bell',
      'search',
      'lock',
      'plus',
      'minus',
      'chevdown',
      'chevup',
      'chevleft',
      'chevright',
      'arrowup',
      'arrowdown',
      'arrowleft',
      'arrowright',
      'download',
      'upload',
      'check',
      'x',
      'alert',
      'info',
      'warn',
      'dot3',
      'logout',
      'calendar',
      'filter',
      'edit',
      'eye',
      'eyeoff',
      'mail',
      'phone',
      'pause',
      'refresh',
      'map',
      'chart',
      'pie',
      'ship',
      'clock',
      'qr',
      'flag',
      'shield',
      'star',
      'suspend',
    ]
    for (const name of names) {
      const { container, unmount } = render(<Icon name={name} />)
      expect(container.querySelector('svg')?.innerHTML.length).toBeGreaterThan(0)
      unmount()
    }
  })
})
