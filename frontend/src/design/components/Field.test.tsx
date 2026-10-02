import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useForm } from 'react-hook-form'
import { describe, expect, it, vi } from 'vitest'
import { Field } from './Field'

describe('Field', () => {
  it('renders a label and associates it with the input', () => {
    render(<Field label="Email" name="email" />)
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  it('shows the error message instead of helper text', () => {
    render(<Field label="Email" name="email" error="Required" helper="We never share this" />)
    expect(screen.getByText('Required')).toBeInTheDocument()
    expect(screen.queryByText('We never share this')).toBeNull()
  })

  it('renders a textarea when multiline is set', () => {
    render(<Field label="Notes" name="notes" multiline />)
    expect(screen.getByLabelText('Notes').tagName).toBe('TEXTAREA')
  })

  it('integrates directly with react-hook-form register() via spread', async () => {
    function Form(): JSX.Element {
      const { register, handleSubmit } = useForm<{ email: string }>()
      const onSubmit = vi.fn()
      return (
        <form onSubmit={handleSubmit(onSubmit)}>
          <Field label="Email" {...register('email', { required: true })} />
          <button type="submit">Submit</button>
        </form>
      )
    }
    render(<Form />)
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.com')
    expect(screen.getByLabelText('Email')).toHaveValue('a@b.com')
  })

  it('accepts an interactive element as trailing content, not just an icon', async () => {
    const onToggle = vi.fn()
    render(
      <Field
        label="Password"
        name="password"
        type="password"
        trailing={
          <button type="button" aria-label="Show password" onClick={onToggle}>
            eye
          </button>
        }
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(onToggle).toHaveBeenCalledOnce()
  })
})
