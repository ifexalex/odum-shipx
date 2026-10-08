import { colors } from '../theme'

export interface KolaMarkProps {
  size?: number
  color?: string
}

// The Odum three-lobed kola-nut mark. Ported from
// Shipx_frontend_design/assets/odum-mark.svg / screens/shared/components.jsx.
// Minimum render size 16px; one lobe-width of clear space on all sides; never
// recolor lobes individually, stretch, skew, or rotate.
export function KolaMark({ size = 32, color = colors.primary }: KolaMarkProps): JSX.Element {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill={color} aria-hidden="true">
      <g transform="rotate(0 50 50)">
        <rect x="36" y="6" width="28" height="48" rx="14" />
      </g>
      <g transform="rotate(120 50 50)">
        <rect x="36" y="6" width="28" height="48" rx="14" />
      </g>
      <g transform="rotate(240 50 50)">
        <rect x="36" y="6" width="28" height="48" rx="14" />
      </g>
    </svg>
  )
}
