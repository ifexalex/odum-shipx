/**
 * The Field family (FD-11, FD-50): every control is named, messages are wired to it, an empty choice says why and
 * where to fix it, and a date is repeated in words.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { ColorField } from './ColorField'
import { DateField } from './DateField'
import { DateRangeFilter } from './DateRangeFilter'
import { Field } from './Field'
import { RadioGroup } from './RadioGroup'
import { SearchField } from './SearchField'
import { Select } from './Select'

describe('Field', () => {
  it('is named by its label even when the label is hidden, and links its error', () => {
    render(<Field label="Search staff" hideLabel name="q" error="Too short" />)
    const box = screen.getByRole('textbox', { name: 'Search staff' })
    expect(box).toHaveAttribute('aria-invalid', 'true')
    expect(box).toHaveAccessibleDescription('Too short')
  })

  it('marks an optional field, and a required one not at all', () => {
    render(
      <>
        <Field label="Notes" name="notes" optional />
        <Field label="Name" name="name" required />
      </>,
    )
    // Shown beside the label, and read as the field's description rather than part of its name.
    expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveAccessibleDescription('Optional')
    expect(screen.queryByText('*')).toBeNull()
  })
})

describe('Select', () => {
  it('is a named dropdown', () => {
    render(
      <Select
        label="Payment method"
        name="method"
        options={[{ value: 'cash', label: 'Cash' }]}
        onChange={vi.fn()}
        value="cash"
      />,
    )
    expect(screen.getByRole('combobox', { name: 'Payment method' })).toHaveValue('cash')
  })

  it('says why there is nothing to choose, and links to the fix', () => {
    render(
      <MemoryRouter>
        <Select
          label="Warehouse"
          name="w"
          options={[]}
          empty={{
            message: 'No warehouses yet.',
            action: { label: 'Add a warehouse', to: '/admin/config/warehouses' },
          }}
        />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText('No warehouses yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add a warehouse' })).toHaveAttribute(
      'href',
      '/admin/config/warehouses',
    )
  })
})

describe('DateField', () => {
  it('repeats the chosen date in words', () => {
    render(<DateField label="Ship date" name="ship" value="2026-11-13" onChange={vi.fn()} />)
    expect(screen.getByLabelText('Ship date')).toHaveValue('2026-11-13')
    expect(screen.getByText(/13 Nov(ember)? 2026/)).toBeInTheDocument()
  })
})

describe('ColorField', () => {
  it('takes a typed hex code once it is whole', async () => {
    const onChange = vi.fn()
    render(<ColorField label="Brand colour" name="c" value="#1c7922" onChange={onChange} />)
    const code = screen.getByLabelText('Brand colour')
    await userEvent.clear(code)
    await userEvent.type(code, '#abc')
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.type(code, 'def')
    expect(onChange).toHaveBeenLastCalledWith('#abcdef')
    expect(screen.getByLabelText('Brand colour: pick a colour')).toBeInTheDocument()
  })
})

describe('SearchField', () => {
  it('is named, and clears', async () => {
    function Harness(): JSX.Element {
      const [q, setQ] = useState('ngozi')
      return <SearchField label="Search customers" value={q} onChange={setQ} />
    }
    render(<Harness />)
    expect(screen.getByRole('searchbox', { name: 'Search customers' })).toHaveValue('ngozi')
    await userEvent.click(screen.getByRole('button', { name: 'Clear search customers' }))
    expect(screen.getByRole('searchbox', { name: 'Search customers' })).toHaveValue('')
  })
})

describe('RadioGroup', () => {
  it('is a named group of choices', async () => {
    const onChange = vi.fn()
    render(
      <RadioGroup
        label="Refund preference"
        name="c"
        value="a"
        onChange={onChange}
        options={[
          { value: 'a', label: 'Bank' },
          { value: 'b', label: 'Credit', hint: 'Next shipment' },
        ]}
      />,
    )
    expect(screen.getByRole('group', { name: 'Refund preference' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /Credit/ }))
    expect(onChange).toHaveBeenCalledWith('b')
  })
})

describe('DateRangeFilter (one date control per filter bar)', () => {
  it('holds presets and a custom range in one popover, and says what is applied', async () => {
    function Harness(): JSX.Element {
      const range = useDateRangeFilter()
      return <DateRangeFilter label="Billed" range={range} />
    }
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Billed: All time' }))
    expect(screen.getByRole('option', { name: 'Last 7 days' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('From'), '2026-11-12')
    expect(screen.getByRole('button', { name: /Billed: Since 12 Nov/ })).toBeInTheDocument()
  })
})
