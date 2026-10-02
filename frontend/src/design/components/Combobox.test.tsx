import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Combobox, type ComboboxOption } from './Combobox'

const OPTIONS: ComboboxOption[] = [
  { value: 'a', label: '40ft High Cube', meta: '76 CBM' },
  { value: 'b', label: '20ft Standard', meta: '33 CBM' },
  { value: 'c', label: '45ft High Cube', meta: '86 CBM' },
]

function Harness({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState('')
  return (
    <div>
      <Combobox ariaLabel="Capacity" options={OPTIONS} value={value} onChange={setValue} disabled={disabled} />
      <span data-testid="value">{value}</span>
    </div>
  )
}

describe('Combobox', () => {
  it('opens, filters by typed text, and selects an option', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Capacity' }))
    await userEvent.type(screen.getByRole('combobox'), '45')
    // Only the matching option remains.
    expect(screen.queryByRole('option', { name: /40ft High Cube/ })).toBeNull()
    await userEvent.click(screen.getByRole('option', { name: /45ft High Cube/ }))
    await waitFor(() => expect(screen.getByTestId('value')).toHaveTextContent('c'))
  })

  it('filters on the meta text too', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Capacity' }))
    await userEvent.type(screen.getByRole('combobox'), '33 CBM')
    expect(screen.getByRole('option', { name: /20ft Standard/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /45ft High Cube/ })).toBeNull()
  })

  it('shows the empty text when nothing matches', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Capacity' }))
    await userEvent.type(screen.getByRole('combobox'), 'zzz')
    expect(screen.getByText('No matches')).toBeInTheDocument()
  })

  it('does not open when disabled', async () => {
    render(<Harness disabled />)
    await userEvent.click(screen.getByRole('button', { name: 'Capacity' }))
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('selects the active option with the keyboard', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Capacity' }))
    const search = screen.getByRole('combobox')
    await userEvent.type(search, '{ArrowDown}{Enter}') // move to 2nd option, select
    await waitFor(() => expect(screen.getByTestId('value')).toHaveTextContent('b'))
  })
})
