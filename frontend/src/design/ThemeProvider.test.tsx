import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ThemeProvider } from './ThemeProvider'

const STATUS_VARS = [
  '--color-success',
  '--color-success-strong',
  '--color-success-soft',
  '--color-warning',
  '--color-warning-strong',
  '--color-warning-soft',
  '--color-error',
  '--color-error-strong',
  '--color-error-soft',
  '--color-info',
  '--color-info-strong',
  '--color-info-soft',
] as const

describe('ThemeProvider', () => {
  it('scopes the override to its own [data-tenant-theme] element', () => {
    const { container } = render(
      <ThemeProvider primaryColor="#1a5276">
        <span>child</span>
      </ThemeProvider>,
    )
    const scope = container.querySelector('[data-tenant-theme]') as HTMLElement
    expect(scope).not.toBeNull()
    expect(scope.style.getPropertyValue('--color-primary')).toBe('#1a5276')
  })

  it('never sets status color custom properties, regardless of input', () => {
    // Status colors are not even a parameter of ThemeProvider — this asserts
    // the implementation has no code path that writes them, by checking the
    // scoped element's own inline style never carries one of these properties,
    // even when an out-of-contract value is forced in via a type-unsafe cast.
    const maliciousProps = { primaryColor: '#1a5276', '--color-error': '#000000' } as Record<
      string,
      unknown
    >
    const { container } = render(
      <ThemeProvider {...maliciousProps}>
        <span>child</span>
      </ThemeProvider>,
    )
    const scope = container.querySelector('[data-tenant-theme]') as HTMLElement
    for (const cssVar of STATUS_VARS) {
      expect(scope.style.getPropertyValue(cssVar)).toBe('')
    }
  })

  it('removes the override and falls back to the canonical palette when primaryColor is absent', () => {
    const { container } = render(
      <ThemeProvider>
        <span>child</span>
      </ThemeProvider>,
    )
    const scope = container.querySelector('[data-tenant-theme]') as HTMLElement
    expect(scope.style.getPropertyValue('--color-primary')).toBe('')
  })

  it('ignores an invalid hex color rather than applying it', () => {
    const { container } = render(
      <ThemeProvider primaryColor="not-a-color">
        <span>child</span>
      </ThemeProvider>,
    )
    const scope = container.querySelector('[data-tenant-theme]') as HTMLElement
    expect(scope.style.getPropertyValue('--color-primary')).toBe('')
  })
})
