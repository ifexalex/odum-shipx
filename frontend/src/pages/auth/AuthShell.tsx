/**
 * AuthShell — shared split-panel layout for all pre-auth screens
 * (login, register, forgot/reset password), per Section 1 of the prototype:
 * brand panel (forest dark, hidden <920px) + centered form panel.
 *
 * Reuses LoginScreen.module.css so the brand panel renders identically on
 * every auth screen.
 */
import type { JSX, ReactNode } from 'react'
import { KolaMark, ShipxWordmark } from '../../design/components'
import { colors } from '../../design/theme'
import styles from './LoginScreen.module.css'

function BrandIllustration(): JSX.Element {
  return (
    <div className={styles.illustration}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: 0.18,
        }}
      >
        <KolaMark size={280} color={colors.primaryBright} />
      </div>
      <svg viewBox="0 0 400 400" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        <defs>
          <linearGradient id="routeGradShell" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={colors.primaryBright} stopOpacity="0.2" />
            <stop offset="0.5" stopColor={colors.primaryBright} stopOpacity="1" />
            <stop offset="1" stopColor={colors.accentHover} stopOpacity="0.9" />
          </linearGradient>
        </defs>
        <circle cx="80" cy="130" r="10" fill={colors.primaryBright} />
        <circle cx="80" cy="130" r="22" fill={colors.primaryBright} fillOpacity="0.18" />
        <circle cx="320" cy="280" r="10" fill={colors.accentHover} />
        <circle cx="320" cy="280" r="22" fill={colors.accentHover} fillOpacity="0.22" />
        <path d="M80 130 Q200 60 320 280" fill="none" stroke="url(#routeGradShell)" strokeWidth="3" strokeDasharray="6 6" />
        <g transform="translate(195 145) rotate(28)">
          <rect x="-22" y="-13" width="44" height="26" rx="6" fill={colors.primaryBright} />
          <rect x="-18" y="-9" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
          <rect x="-18" y="-2" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
          <rect x="-18" y="5" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
        </g>
        <text x="80" y="105" textAnchor="middle" style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fill: colors.primaryBright, letterSpacing: 'var(--tracking-label)' }}>
          CN · GZG
        </text>
        <text x="320" y="312" textAnchor="middle" style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', fill: colors.accentHover, letterSpacing: 'var(--tracking-label)' }}>
          NG · LOS
        </text>
      </svg>
    </div>
  )
}

export interface AuthShellProps {
  children: ReactNode
}

export function AuthShell({ children }: AuthShellProps): JSX.Element {
  return (
    <div className={styles.shell}>
      <div className={styles.brandPanel}>
        <div className={styles.glow} />
        <div className={styles.brandTop}>
          <KolaMark size={26} color="#fff" />
          <ShipxWordmark size={22} showBy />
        </div>
        <div className={styles.tagline}>
          <BrandIllustration />
          {/* The brand line, not the page's heading: the form's title is the h1 (FD-49). */}
          <p className={styles.heroHeading}>
            Cargo logistics,
            <br />
            <span className={styles.heroAccent}>engineered to move.</span>
          </p>
          <p className={styles.heroSub}>
            Guangzhou to Lagos. End-to-end. Unstoppable. Built for the operators, customers, and developers
            who lead every shipment.
          </p>
        </div>
        <div className={styles.brandFooter}>
          <div className={styles.footerCopy}>© 2026 ShipX Platform</div>
          <div className={styles.statusRow}>
            <span className={styles.statusDot} />
            <span className={styles.statusText}>All systems operational</span>
          </div>
        </div>
      </div>

      <div className={styles.formPanel}>
        <div className={styles.formWrap}>
          <div className={styles.mobileBrand}>
            <KolaMark size={24} color="var(--color-primary)" />
            <ShipxWordmark size={18} />
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}

export interface FormHeadProps {
  title: string
  sub?: string
}

export function FormHead({ title, sub }: FormHeadProps): JSX.Element {
  return (
    <div className={styles.formHead}>
      <h1 className={styles.formTitle}>{title}</h1>
      {sub && <p className={styles.formSub}>{sub}</p>}
    </div>
  )
}

/** Password strength meter — 4 bars, per prototype PasswordStrength. */
export function PasswordStrength({ password }: { password: string }): JSX.Element | null {
  const level = scorePassword(password)
  if (level === 0) return null
  const labels = ['', 'Weak', 'Fair', 'Strong', 'Excellent']
  const barColors = ['', 'var(--color-error)', 'var(--color-warning)', 'var(--color-success)', 'var(--color-success)']
  return (
    <div style={{ marginTop: 'var(--space-2)' }}>
      <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: 4,
              borderRadius: 'var(--radius-sm)',
              background: i <= level ? barColors[level] : 'var(--color-line-soft)',
            }}
          />
        ))}
      </div>
      <div style={{ marginTop: 'var(--space-1)', fontSize: 'var(--text-xs)', fontWeight: 600, color: barColors[level] }}>
        Password strength: {labels[level]}
      </div>
    </div>
  )
}

export function scorePassword(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0
  const hasMinLen = pw.length >= 12
  const hasMixedCase = /[a-z]/.test(pw) && /[A-Z]/.test(pw)
  const hasNumber = /\d/.test(pw)
  const hasSpecial = /[^A-Za-z0-9]/.test(pw)
  const checks = [hasMinLen, hasMixedCase, hasNumber, hasSpecial].filter(Boolean).length

  // Never report "Strong" or "Excellent" until the 12-character policy floor is met.
  if (!hasMinLen) {
    return (pw.length >= 8 && checks >= 2 ? 2 : 1) as 1 | 2
  }
  if (checks === 4) return 4
  if (checks === 3) return 3
  return 2
}
