import type { JSX } from 'react'
import { useColorScheme, type ColorSchemePreference } from '../colorScheme'
import { Icon, type IconName } from './Icon'
import styles from './ThemeToggle.module.css'

const NEXT_LABEL: Record<ColorSchemePreference, string> = {
  system: 'Switch to light mode',
  light: 'Switch to dark mode',
  dark: 'Use system theme',
}

const ICON: Record<ColorSchemePreference, IconName> = {
  system: 'monitor',
  light: 'sun',
  dark: 'moon',
}

export interface ThemeToggleProps {
  /** Override the default pill styling — e.g. to match a dark header bar. */
  className?: string
}

/**
 * Single-button theme control: cycles System → Light → Dark → System.
 * The icon shows the current preference; the tooltip says what a click does.
 */
export function ThemeToggle({ className }: ThemeToggleProps = {}): JSX.Element {
  const { preference, cycle } = useColorScheme()
  return (
    <button
      type="button"
      className={className ?? styles.toggle}
      onClick={cycle}
      aria-label={NEXT_LABEL[preference]}
      title={NEXT_LABEL[preference]}
    >
      <Icon name={ICON[preference]} size={17} stroke={2} />
    </button>
  )
}
