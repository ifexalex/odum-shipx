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
  ink: '#1c1b1c',
  ink2: '#374151',
  ink3: '#666666',
  ink4: '#6b7280',
  line: '#cccccc',
  lineSoft: '#e5e7eb',
  surface: '#ffffff',
  surfaceMuted: '#f9fafb',
  page: '#f3f4f6',
  success: '#16a34a',
  successStrong: '#14532d',
  successSoft: '#dcfce7',
  warning: '#d97706',
  warningStrong: '#7c2d0e',
  warningSoft: '#fef3c7',
  error: '#dc2626',
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
  roleWarehouse: '#d97706',
  roleCustomer: '#2dc438',
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

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  '2xl': 48,
  '3xl': 64,
} as const

export const layout = {
  sidebarWidth: 240,
  sidebarWidthCollapsed: 64,
  contentMaxWidth: 1280,
} as const

export const radius = {
  none: 0,
  sm: 8,
  md: 10,
  lg: 14,
  xl: 12,
  full: 9999,
} as const

export const shadows = {
  rest: '0 1px 3px rgba(11,47,13,0.08), 0 1px 2px rgba(11,47,13,0.05)',
  hover: '0 4px 12px rgba(11,47,13,0.10), 0 2px 4px rgba(11,47,13,0.06)',
  modal: '0 10px 25px rgba(11,47,13,0.18)',
  focusRing: '0 0 0 3px rgba(45,196,56,0.35)',
  scrimModal: 'rgba(11,47,13,0.55)',
} as const

export const roleColors = {
  platform: colors.rolePlatform,
  admin: colors.roleAdmin,
  china: colors.roleChina,
  nigeria: colors.roleNigeria,
  warehouse: colors.roleWarehouse,
  customer: colors.roleCustomer,
} as const satisfies Record<string, string>

export type Role = keyof typeof roleColors

export const theme = { colors, fonts, typeScale, spacing, layout, radius, shadows, roleColors } as const

export type Theme = typeof theme
