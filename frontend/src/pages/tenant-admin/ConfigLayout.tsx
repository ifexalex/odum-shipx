/**
 * Shared layout for the /admin/config/* section (prototype ConfigSubNav —
 * tenant-config-screens.jsx). Every config screen renders inside this: the
 * left rail stays persistent while only the content area swaps, so switching
 * sections feels like tabs on one settings page while each section keeps its
 * own URL (deep links, browser back/forward, refresh-restores-position).
 *
 * Wired in routes.tsx around each config screen — the pages themselves don't
 * know the rail exists.
 */
import type { JSX, ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Card, Icon, type IconName } from '../../design/components'
import styles from './ConfigLayout.module.css'

const SUB_NAV: { icon: IconName; label: string; desc: string; path: string }[] = [
  { icon: 'settings', label: 'Company', desc: 'Identity, contact, documents', path: '/admin/config' },
  { icon: 'coin', label: 'Dollar rate', desc: 'USD → NGN', path: '/admin/config/dollar-rate' },
  { icon: 'package', label: 'CBM rate', desc: 'Price per cubic metre', path: '/admin/config/cbm-rate' },
  { icon: 'card', label: 'Charge types', desc: 'Custom misc charges', path: '/admin/config/charge-types' },
  { icon: 'container', label: 'Container capacities', desc: 'Capacity presets', path: '/admin/config/container-capacities' },
  { icon: 'building', label: 'Warehouses', desc: 'Arrival / branch locations', path: '/admin/config/warehouses' },
  { icon: 'bell', label: 'Notifications', desc: 'SMS · WhatsApp · Email', path: '/admin/config/notifications' },
  { icon: 'log', label: 'Webhooks', desc: 'Outbound integrations', path: '/admin/config/webhooks' },
  { icon: 'coin', label: 'Payments', desc: 'Connect your Paystack account', path: '/admin/config/payments' },
]

export function ConfigLayout({ children }: { children: ReactNode }): JSX.Element {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  return (
    <div className={styles.layout}>
      <nav className={styles.navCol} aria-label="Settings">
        <Card padding="default">
          <p className={styles.navHeading} aria-hidden="true">
            All settings
          </p>
          {SUB_NAV.map((item) => {
            const isActive = pathname === item.path
            return (
              <div
                key={item.path}
                className={[styles.subNavItem, isActive ? styles.subNavItemActive : ''].join(' ')}
                role="link"
                aria-current={isActive ? 'page' : undefined}
                tabIndex={0}
                onClick={() => !isActive && navigate(item.path)}
                onKeyDown={(e) => e.key === 'Enter' && !isActive && navigate(item.path)}
              >
                <div className={[styles.subNavIcon, isActive ? styles.subNavIconActive : ''].join(' ')}>
                  <Icon name={item.icon} size={14} stroke={2.2} />
                </div>
                <div className={styles.subNavText}>
                  <div className={[styles.subNavLabel, isActive ? styles.subNavLabelActive : ''].join(' ')}>
                    {item.label}
                  </div>
                  <div className={styles.subNavDesc}>{item.desc}</div>
                </div>
                {isActive && <Icon name="chevright" size={13} color="var(--color-primary)" />}
              </div>
            )
          })}
        </Card>
      </nav>
      <div className={styles.content}>{children}</div>
    </div>
  )
}
