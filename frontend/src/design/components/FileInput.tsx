/**
 * FileInput — the hidden file picker behind an upload button (FD-11). The visible control is a Button that calls
 * `ref.current.click()`; this keeps the input itself out of the layout and named for assistive technology.
 */
import { forwardRef, type InputHTMLAttributes } from 'react'
import styles from './Field.module.css'

export interface FileInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'aria-label'> {
  label: string
}

export const FileInput = forwardRef<HTMLInputElement, FileInputProps>(function FileInput({ label, className, ...rest }, ref) {
  return <input ref={ref} type="file" aria-label={label} className={[styles.visuallyHidden, className].filter(Boolean).join(' ')} {...rest} />
})
