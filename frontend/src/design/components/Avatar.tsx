import type { CSSProperties, JSX } from 'react'
import styles from './Avatar.module.css'
import { colors, roleColors, type Role } from '../theme'

export interface AvatarProps {
  name?: string
  src?: string
  size?: number
  roleColor?: Role
  color?: string
}

function initialsOf(name: string): string {
  return (
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((word) => word[0])
      .join('')
      .toUpperCase() || '?'
  )
}

export function Avatar({ name = '', src, size = 32, roleColor, color }: AvatarProps): JSX.Element {
  const tint = (roleColor && roleColors[roleColor]) || color || colors.primary
  const style: CSSProperties & Record<'--avatar-color', string> = {
    width: size,
    height: size,
    fontSize: size * 0.4,
    '--avatar-color': tint,
  }

  return (
    <span className={styles.avatar} style={style}>
      {src ? <img className={styles.image} src={src} alt={name} /> : initialsOf(name)}
    </span>
  )
}
