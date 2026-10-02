import type { JSX, SVGProps } from 'react'

// Line-icon set ported from screens/shared/components.jsx. IconName is a
// closed string union (not `string`) so an unknown icon name fails at compile
// time rather than silently rendering an empty <svg>.
export type IconName =
  | 'grid'
  | 'building'
  | 'users'
  | 'user'
  | 'settings'
  | 'log'
  | 'home'
  | 'container'
  | 'package'
  | 'file'
  | 'truck'
  | 'coin'
  | 'card'
  | 'bell'
  | 'search'
  | 'menu'
  | 'lock'
  | 'plus'
  | 'minus'
  | 'chevdown'
  | 'chevup'
  | 'chevleft'
  | 'chevright'
  | 'arrowup'
  | 'arrowdown'
  | 'arrowleft'
  | 'arrowright'
  | 'download'
  | 'upload'
  | 'check'
  | 'x'
  | 'alert'
  | 'info'
  | 'warn'
  | 'dot3'
  | 'logout'
  | 'calendar'
  | 'filter'
  | 'edit'
  | 'eye'
  | 'eyeoff'
  | 'mail'
  | 'phone'
  | 'pause'
  | 'refresh'
  | 'map'
  | 'chart'
  | 'pie'
  | 'ship'
  | 'clock'
  | 'qr'
  | 'flag'
  | 'shield'
  | 'star'
  | 'suspend'
  | 'sun'
  | 'moon'
  | 'monitor'

export interface IconProps {
  name: IconName
  size?: number
  color?: string
  stroke?: number
  fill?: string
}

const PATHS: Record<IconName, JSX.Element> = {
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  building: (
    <path d="M3 21V7l9-4 9 4v14M9 9h.01M15 9h.01M9 13h.01M15 13h.01M9 17h.01M15 17h.01" />
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="4" />
      <path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M17 11a4 4 0 1 0 0-8M22 21v-2a4 4 0 0 0-3-3.87" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  settings: (
    <>
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8L4.2 7a2 2 0 0 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8h0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  log: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </>
  ),
  home: <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2h-4v-7H10v7H6a2 2 0 0 1-2-2z" />,
  container: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="1" />
      <path d="M7 6v13M11 6v13M15 6v13M19 6v13" />
    </>
  ),
  package: (
    <>
      <path d="M21 16V8a2 2 0 0 0-1-1.73L13 2.27a2 2 0 0 0-2 0L4 6.27A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="M3.27 7L12 12l8.73-5M12 22V12" />
    </>
  ),
  file: (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </>
  ),
  truck: (
    <>
      <rect x="1" y="6" width="14" height="11" rx="1" />
      <path d="M15 9h4l3 4v4h-7M5.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />
    </>
  ),
  coin: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6v12M9 9.5a2.5 2.5 0 0 1 5 0M9 14.5a2.5 2.5 0 0 0 5 0" />
    </>
  ),
  card: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
    </>
  ),
  bell: <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 0 0 4 0" />,
  menu: <path d="M3 6h18M3 12h18M3 18h18" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </>
  ),
  lock: (
    <>
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  chevdown: <polyline points="6 9 12 15 18 9" />,
  chevup: <polyline points="18 15 12 9 6 15" />,
  chevleft: <polyline points="15 18 9 12 15 6" />,
  chevright: <polyline points="9 18 15 12 9 6" />,
  arrowup: <path d="M12 19V5M5 12l7-7 7 7" />,
  arrowdown: <path d="M12 5v14M5 12l7 7 7-7" />,
  arrowleft: <path d="M19 12H5M12 19l-7-7 7-7" />,
  arrowright: <path d="M5 12h14M12 5l7 7-7 7" />,
  download: <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />,
  upload: <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />,
  check: <polyline points="20 6 9 17 4 12" />,
  x: <path d="M18 6L6 18M6 6l12 12" />,
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 16v-4M12 8h.01" />
    </>
  ),
  warn: <path d="M12 2L2 22h20L12 2zM12 9v5M12 18h.01" />,
  dot3: (
    <>
      <circle cx="5" cy="12" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="19" cy="12" r="1.5" />
    </>
  ),
  logout: <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />,
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 9h18M8 3v4M16 3v4" />
    </>
  ),
  filter: <path d="M3 6h18M7 12h10M11 18h2" />,
  edit: <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z" />,
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  eyeoff: (
    <>
      <path d="M1 1l22 22" />
      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c6.5 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
      <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3.5 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
  phone: (
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
  ),
  pause: (
    <>
      <path d="M6 4h4v16H6z" />
      <path d="M14 4h4v16h-4z" />
    </>
  ),
  refresh: <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" />,
  map: (
    <>
      <polygon points="1 6 8 3 16 6 23 3 23 18 16 21 8 18 1 21 1 6" />
      <line x1="8" y1="3" x2="8" y2="18" />
      <line x1="16" y1="6" x2="16" y2="21" />
    </>
  ),
  chart: <path d="M3 3v18h18M7 15l4-4 4 4 5-7" />,
  pie: (
    <>
      <path d="M21 12a9 9 0 1 1-9-9v9z" />
      <path d="M21 12a9 9 0 0 0-9-9" />
    </>
  ),
  ship: (
    <path d="M3 16l1-2h16l1 2M5 16v2c0 1 1 2 2 2h10c1 0 2-1 2-2v-2M12 4v8M8 8h8M9 12V8M15 12V8" />
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  qr: (
    <>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <path d="M14 14h3v3M17 17v3h3M20 14h-3" />
    </>
  ),
  flag: <path d="M4 21V4M4 4h13l-2 4 2 4H4" />,
  shield: <path d="M12 2l9 4v6c0 5-3.5 9-9 10-5.5-1-9-5-9-10V6l9-4z" />,
  star: <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9 12 2" />,
  suspend: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9v6M15 9v6" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  monitor: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
}

export function Icon({
  name,
  size = 16,
  color = 'currentColor',
  stroke = 2,
  fill = 'none',
}: IconProps): JSX.Element {
  const props: SVGProps<SVGSVGElement> = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill,
    stroke: color,
    strokeWidth: stroke,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  }
  return (
    <svg {...props} style={{ flexShrink: 0, display: 'block' }} aria-hidden="true">
      {PATHS[name]}
    </svg>
  )
}
