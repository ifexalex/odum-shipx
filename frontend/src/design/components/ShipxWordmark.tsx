import type { JSX } from 'react'
import { colors, fonts } from '../theme'

export interface ShipxWordmarkProps {
  size?: number
  color?: string
  xColor?: string
  /** Renders the small "by Odum" co-mark below the wordmark — pre-auth/marketing surfaces only. */
  showBy?: boolean
}

// "shipx" lowercase wordmark, ported from screens/shared/components.jsx.
// The product is "ShipX" standalone inside the app — the Odum co-mark only
// appears on marketing-adjacent surfaces (login, public tracking, footer).
export function ShipxWordmark({
  size = 22,
  color = '#fff',
  xColor = colors.accent,
  showBy = false,
}: ShipxWordmarkProps): JSX.Element {
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1 }}>
      <span
        style={{
          fontFamily: fonts.display,
          fontWeight: 700,
          fontSize: size,
          letterSpacing: 'var(--tracking-tight)',
          color,
          lineHeight: 1,
        }}
      >
        ship<span style={{ color: xColor }}>x</span>
      </span>
      {showBy && (
        <span
          style={{
            fontFamily: fonts.body,
            fontSize: Math.max(9, size * 0.4),
            fontWeight: 600,
            letterSpacing: 'var(--tracking-label)',
            textTransform: 'uppercase',
            color,
            opacity: 0.6,
            marginTop: 2,
          }}
        >
          by Odum
        </span>
      )}
    </span>
  )
}
