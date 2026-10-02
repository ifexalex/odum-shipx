import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ColorSchemeProvider, useColorScheme } from './colorScheme'

function Probe(): JSX.Element {
  const { preference, resolved, cycle, setPreference } = useColorScheme()
  return (
    <div>
      <span data-testid="pref">{preference}</span>
      <span data-testid="resolved">{resolved}</span>
      <button onClick={cycle}>cycle</button>
      <button onClick={() => setPreference('dark')}>force-dark</button>
    </div>
  )
}

function mockMatchMedia(dark: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: dark,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

describe('colorScheme', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
    mockMatchMedia(false)
  })
  afterEach(() => {
    localStorage.clear()
  })

  it('defaults to system and resolves to the OS preference', () => {
    mockMatchMedia(true) // OS is dark
    render(
      <ColorSchemeProvider>
        <Probe />
      </ColorSchemeProvider>,
    )
    expect(screen.getByTestId('pref')).toHaveTextContent('system')
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('cycles system → light → dark → system and writes data-theme', async () => {
    render(
      <ColorSchemeProvider>
        <Probe />
      </ColorSchemeProvider>,
    )
    const cycle = screen.getByText('cycle')
    expect(screen.getByTestId('pref')).toHaveTextContent('system')

    await userEvent.click(cycle)
    expect(screen.getByTestId('pref')).toHaveTextContent('light')
    expect(document.documentElement.dataset.theme).toBe('light')

    await userEvent.click(cycle)
    expect(screen.getByTestId('pref')).toHaveTextContent('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    await userEvent.click(cycle)
    expect(screen.getByTestId('pref')).toHaveTextContent('system')
  })

  it('persists an explicit preference to localStorage', async () => {
    render(
      <ColorSchemeProvider>
        <Probe />
      </ColorSchemeProvider>,
    )
    await userEvent.click(screen.getByText('force-dark'))
    expect(localStorage.getItem('shipx-color-scheme')).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('reads a stored preference on mount', () => {
    localStorage.setItem('shipx-color-scheme', 'dark')
    mockMatchMedia(false) // OS is light, but stored pref wins
    render(
      <ColorSchemeProvider>
        <Probe />
      </ColorSchemeProvider>,
    )
    expect(screen.getByTestId('pref')).toHaveTextContent('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('works standalone (no provider): toggling still writes data-theme', async () => {
    render(<Probe />)
    expect(screen.getByTestId('pref')).toHaveTextContent('system')
    await userEvent.click(screen.getByText('force-dark'))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('shipx-color-scheme')).toBe('dark')
  })
})
