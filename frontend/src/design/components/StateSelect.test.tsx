import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { CountrySelect } from './CountrySelect'
import { StateSelect } from './StateSelect'

function StateHarness({ country, initial = '' }: { country: string; initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <StateSelect country={country} name="state" value={value} onChange={setValue} />
      <output data-testid="value">{value}</output>
    </>
  )
}

describe('StateSelect', () => {
  it('offers Nigerian states as a searchable list', async () => {
    render(<StateHarness country="Nigeria" />)
    await userEvent.click(screen.getByLabelText('State'))
    await userEvent.type(screen.getByPlaceholderText('Search…'), 'anamb')
    await userEvent.click(await screen.findByText('Anambra'))
    expect(screen.getByTestId('value')).toHaveTextContent('Anambra')
  })

  it('calls a Chinese subdivision a Province', () => {
    // A Chinese origin address asks for a Province, not a State.
    render(<StateHarness country="China" />)
    expect(screen.getByLabelText('Province')).toBeInTheDocument()
  })

  it('calls a Ghanaian subdivision a Region', () => {
    render(<StateHarness country="Ghana" />)
    expect(screen.getByLabelText('Region')).toBeInTheDocument()
  })

  it('falls back to a text input for a country with no list on file', async () => {
    // An empty dropdown would make the field impossible to fill, which is
    // strictly worse than typing.
    render(<StateHarness country="Kenya" />)
    const input = screen.getByLabelText(/state \/ province/i, { selector: 'input' })
    await userEvent.type(input, 'Nairobi')
    expect(screen.getByTestId('value')).toHaveTextContent('Nairobi')
    expect(screen.getByText(/no state \/ province list on file for Kenya/i)).toBeInTheDocument()
  })

  it('keeps a stored value that is not in the list rather than blanking it', async () => {
    // A row typed before this picker existed must not silently lose its state.
    render(<StateHarness country="Nigeria" initial="Old Province Name" />)
    expect(screen.getByLabelText('State')).toHaveTextContent('Old Province Name')
  })

  it('matches a stored value case-insensitively', () => {
    render(<StateHarness country="Nigeria" initial="lagos" />)
    expect(screen.getByLabelText('State')).toHaveTextContent('Lagos')
  })
})

function CountryHarness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <CountrySelect label="Country" name="country" value={value} onChange={setValue} />
      <output data-testid="value">{value}</output>
    </>
  )
}

describe('CountrySelect', () => {
  it('stores the country name, since that is what the database holds', async () => {
    render(<CountryHarness />)
    await userEvent.click(screen.getByLabelText('Country'))
    await userEvent.type(screen.getByPlaceholderText(/search by name or dial code/i), 'niger')
    await userEvent.click(await screen.findByText('Nigeria'))
    expect(screen.getByTestId('value')).toHaveTextContent('Nigeria')
  })

  it('is searchable by dial code too', async () => {
    render(<CountryHarness />)
    await userEvent.click(screen.getByLabelText('Country'))
    await userEvent.type(screen.getByPlaceholderText(/search by name or dial code/i), '233')
    expect(await screen.findByText('Ghana')).toBeInTheDocument()
  })

  it('shows the operating markets first', async () => {
    render(<CountryHarness />)
    await userEvent.click(screen.getByLabelText('Country'))
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveTextContent('Nigeria')
  })

  it('preserves an unrecognised stored country instead of dropping it', () => {
    render(<CountryHarness initial="Dahomey" />)
    expect(screen.getByLabelText('Country')).toHaveTextContent('Dahomey')
  })

  it('normalises the displayed spelling of a valid stored name', () => {
    render(<CountryHarness initial="  nigeria " />)
    expect(screen.getByLabelText('Country')).toHaveTextContent('Nigeria')
  })
})
