import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { PhoneField } from './PhoneField'

/** Controlled host, so the test exercises the real value→parse→emit loop. */
function Harness({ initial = '', onValue }: { initial?: string; onValue?: (v: string) => void }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <PhoneField
        label="Phone"
        name="phone"
        value={value}
        onChange={(next) => {
          setValue(next)
          onValue?.(next)
        }}
      />
      <output data-testid="value">{value}</output>
    </>
  )
}

describe('PhoneField', () => {
  it('defaults the country code to Nigeria', async () => {
    render(<Harness />)
    expect(await screen.findByText('+234')).toBeInTheDocument()
  })

  it('submits E.164 assembled from the picker and the typed national number', async () => {
    render(<Harness />)
    await userEvent.type(screen.getByLabelText('Phone', { selector: 'input' }), '8012345678')
    expect(screen.getByTestId('value')).toHaveTextContent('+2348012345678')
  })

  it('drops a trunk 0 instead of doubling the dial code', async () => {
    // The bug this component was built to prevent: a lone '0' must not emit a
    // bare '+234' that then reads back as national digits.
    render(<Harness />)
    await userEvent.type(screen.getByLabelText('Phone', { selector: 'input' }), '08012345678')
    expect(screen.getByTestId('value')).toHaveTextContent('+2348012345678')
  })

  it('splits an existing stored number back into country and national part', async () => {
    render(<Harness initial="+8613800138000" />)
    // Chinese number → picker shows +86, input shows only the national digits.
    expect(await screen.findByText('+86')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone', { selector: 'input' })).toHaveValue('13800138000')
  })

  it('parses a legacy local-format value so an old record can be edited', async () => {
    render(<Harness initial="08012345678" />)
    expect(await screen.findByText('+234')).toBeInTheDocument()
    expect(screen.getByLabelText('Phone', { selector: 'input' })).toHaveValue('8012345678')
  })

  it('rewrites the stored number when the country changes', async () => {
    render(<Harness initial="+2348012345678" />)
    await userEvent.click(screen.getByLabelText('Phone country code'))
    await userEvent.type(screen.getByPlaceholderText(/country or code/i), 'Ghana')
    await userEvent.click(await screen.findByText('+233'))
    // The national part is kept; only the dial code moves.
    expect(screen.getByTestId('value')).toHaveTextContent('+2338012345678')
  })

  it('finds a country by dial code as well as by name', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByLabelText('Phone country code'))
    await userEvent.type(screen.getByPlaceholderText(/country or code/i), '86')
    expect(await screen.findByText('China')).toBeInTheDocument()
  })

  it('emits empty rather than a bare dial code when cleared', async () => {
    // Otherwise every untouched optional phone field would store "+234".
    const onValue = vi.fn()
    render(<Harness initial="+2348012345678" onValue={onValue} />)
    await userEvent.clear(screen.getByLabelText('Phone', { selector: 'input' }))
    expect(screen.getByTestId('value')).toHaveTextContent('')
    expect(onValue).toHaveBeenLastCalledWith('')
  })
})
