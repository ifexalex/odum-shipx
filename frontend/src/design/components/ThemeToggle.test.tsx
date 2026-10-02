import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ColorSchemeProvider } from '../colorScheme'
import { ThemeToggle } from './ThemeToggle'

function renderToggle() {
  return render(
    <ColorSchemeProvider>
      <ThemeToggle />
    </ColorSchemeProvider>,
  )
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('cycles the theme and updates its accessible label', async () => {
    renderToggle()
    // Starts on 'system' → label offers light next.
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button', { name: /switch to dark mode/i })).toBeInTheDocument()
    expect(document.documentElement.dataset.theme).toBe('light')

    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button', { name: /use system theme/i })).toBeInTheDocument()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
