// TypeScript mirror of tokens.css — for JS-driven styles (charts, computed values)
// that cannot consume CSS custom properties directly. CSS is the source of truth;
// keep these in sync with tokens.css by hand when either changes.

export const colors = {
  primary: '#1c7922',
  primaryDeep: '#14471a',
  primaryStrong: '#155f1b',
  primaryBright: '#2dc438',
  primarySoft: '#d6f5da',
  primaryTint: '#f3fcf4',
  forestDark: '#0b2f0d',
  accent: '#9a3412',
  accentDeep: '#7c2d12',
  accentHover: '#c2410c',
  accentSoft: '#fed7aa',
  ink: '#1f2329',
  ink2: '#374151',
  ink3: '#4b5563',
  ink4: '#5f6672',
  line: '#d1d5db',
  lineSoft: '#e5e7eb',
  surface: '#ffffff',
  surfaceMuted: '#f9fafb',
  page: '#f3f4f6',
  success: '#15803d',
  successStrong: '#14532d',
  successSoft: '#dcfce7',
  warning: '#b45309',
  warningStrong: '#7c2d0e',
  warningSoft: '#fef3c7',
  error: '#c81e1e',
  errorStrong: '#991b1b',
  errorSoft: '#fee2e2',
  info: '#2563eb',
  infoStrong: '#1e3a8a',
  infoSoft: '#dbeafe',
  rolePlatform: '#7c3aed',
  rolePlatformSoft: '#ede9fe',
  roleAdmin: '#1c7922',
  roleChina: '#4f46e5',
  roleNigeria: '#9a3412',
  roleWarehouse: '#b45309',
  roleCustomer: '#1a7f26',
} as const satisfies Record<string, string>

export const fonts = {
  display: '"ShipX Naira", "Manrope Variable", sans-serif',
  body: '"ShipX Naira", "Kumbh Sans Variable", sans-serif',
  mono: '"ShipX Naira", "JetBrains Mono Variable", monospace',
} as const

export interface TypeStyle {
  fontFamily: string
  fontSize: number
  fontWeight: number
  lineHeight: number
  letterSpacing?: string
  textTransform?: 'uppercase'
}

export const typeScale = {
  displayLg: { fontFamily: fonts.display, fontSize: 32, fontWeight: 700, lineHeight: 1.25 },
  displayMd: { fontFamily: fonts.display, fontSize: 24, fontWeight: 700, lineHeight: 1.33 },
  headlineLg: { fontFamily: fonts.display, fontSize: 20, fontWeight: 600, lineHeight: 1.4 },
  headlineMd: { fontFamily: fonts.display, fontSize: 16, fontWeight: 600, lineHeight: 1.5 },
  bodyLg: { fontFamily: fonts.body, fontSize: 16, fontWeight: 400, lineHeight: 1.5 },
  bodyMd: { fontFamily: fonts.body, fontSize: 14, fontWeight: 400, lineHeight: 1.43 },
  bodySm: { fontFamily: fonts.body, fontSize: 12, fontWeight: 400, lineHeight: 1.33 },
  labelMd: { fontFamily: fonts.body, fontSize: 14, fontWeight: 500, lineHeight: 1.43 },
  labelSm: {
    fontFamily: fonts.body,
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.33,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  mono: { fontFamily: fonts.mono, fontSize: 13, fontWeight: 400, lineHeight: 1.54 },
} as const satisfies Record<string, TypeStyle>

/** The spacing scale in px, mirroring --space-* in tokens.css (FD-02). */
export const spacing = {
  '0-5': 2,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  12: 48,
  16: 64,
} as const

export const layout = {
  sidebarWidth: 232,
  sidebarWidthCollapsed: 60,
  contentMaxWidth: 1320,
} as const

export const radius = {
  none: 0,
  sm: 4,
  md: 6,
  lg: 10,
  xl: 14,
  full: 9999,
} as const

export const shadows = {
  control: '0 1px 2px rgba(11,47,13,0.06), 0 1px 1px rgba(11,47,13,0.04)',
  rest: '0 7px 14px 0 rgba(11,47,13,0.06), 0 3px 6px 0 rgba(11,47,13,0.04)',
  hover: '0 10px 22px 0 rgba(11,47,13,0.10), 0 4px 8px 0 rgba(11,47,13,0.06)',
  modal: '0 20px 44px 0 rgba(11,47,13,0.20), 0 6px 16px 0 rgba(11,47,13,0.10)',
  focusRing: '0 0 0 3px rgba(45,196,56,0.32)',
  scrimModal: 'rgba(11,47,13,0.55)',
} as const

/**
 * Role colours as CSS variables, so a role-tinted element (an avatar's initials) follows the theme; the dark theme
 * lightens them to stay readable (FD-03). `colors.role*` stay fixed hex values for the always-dark sidebar.
 */
export const roleColors = {
  platform: 'var(--color-role-platform)',
  admin: 'var(--color-role-admin)',
  china: 'var(--color-role-china)',
  nigeria: 'var(--color-role-nigeria)',
  warehouse: 'var(--color-role-warehouse)',
  customer: 'var(--color-role-customer)',
} as const satisfies Record<string, string>

export type Role = keyof typeof roleColors

export const theme = { colors, fonts, typeScale, spacing, layout, radius, shadows, roleColors } as const

export type Theme = typeof theme
