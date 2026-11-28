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
import { NavLink } from 'react-router-dom'
import type { TenantConfig } from '../../api/tenantManagement'
import { Card, Icon, type IconName } from '../../design/components'
import { useTenantConfig } from '../../hooks/useConfig'
import styles from './ConfigLayout.module.css'

type ConfigHealth = 'ok' | 'warn' | null

interface SubNavItem {
  icon: IconName
  label: string
  desc: string
  path: string
  health?: (cfg: TenantConfig) => ConfigHealth
}

interface SubNavGroup {
  title: string
  items: SubNavItem[]
}

const SUB_NAV_GROUPS: SubNavGroup[] = [
  {
    title: 'Business setup',
    items: [
      {
        icon: 'settings',
        label: 'Company',
        desc: 'Identity, contact, documents',
        path: '/admin/config',
        health: (cfg) => (cfg.branding_config?.display_name ? 'ok' : 'warn'),
      },
      { icon: 'building', label: 'Warehouses', desc: 'Arrival / branch locations', path: '/admin/config/warehouses' },
      { icon: 'container', label: 'Container capacities', desc: 'Capacity presets', path: '/admin/config/container-capacities' },
    ],
  },
  {
    title: 'Pricing & billing',
    items: [
      {
        icon: 'coin',
        label: 'Payments',
        desc: 'Bank transfer & Paystack',
        path: '/admin/config/payments',
        health: (cfg) => (cfg.bank_transfer_config || cfg.paystack_config?.enabled ? 'ok' : 'warn'),
      },
      { icon: 'coin', label: 'Dollar rate', desc: 'USD → NGN markup', path: '/admin/config/dollar-rate' },
      { icon: 'package', label: 'CBM rate', desc: 'Price per cubic metre', path: '/admin/config/cbm-rate' },
      { icon: 'card', label: 'Charge types', desc: 'Custom misc charges', path: '/admin/config/charge-types' },
      { icon: 'shield', label: 'Policies', desc: 'Storage fees, limits, reminders', path: '/admin/config/policies' },
    ],
  },
  {
    title: 'Messaging & integrations',
    items: [
      { icon: 'bell', label: 'Notifications', desc: 'SMS · WhatsApp · Email', path: '/admin/config/notifications' },
      {
        icon: 'log',
        label: 'Webhooks',
        desc: 'Outbound integrations',
        path: '/admin/config/webhooks',
        health: (cfg) => (cfg.webhook_config?.enabled ? 'ok' : null),
      },
    ],
  },
]

export function ConfigLayout({ children }: { children: ReactNode }): JSX.Element {
  const tenantConfig = useTenantConfig()
  const cfg = tenantConfig.data

  return (
    <div className={styles.layout}>
      <nav className={styles.navCol} aria-label="Settings">
        <Card padding="default">
          <div className={styles.navGroups}>
            {SUB_NAV_GROUPS.map((group) => (
              <div key={group.title} className={styles.navGroup}>
                <p className={styles.groupTitle}>{group.title}</p>
                {group.items.map((item) => {
                  const status = cfg && item.health ? item.health(cfg) : null
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.path === '/admin/config'}
                      className={({ isActive }) =>
                        [styles.subNavItem, isActive ? styles.subNavItemActive : ''].filter(Boolean).join(' ')
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <div className={[styles.subNavIcon, isActive ? styles.subNavIconActive : ''].filter(Boolean).join(' ')}>
                            <Icon name={item.icon} size={14} stroke={2.2} />
                          </div>
                          <div className={styles.subNavText}>
                            <div className={styles.subNavLabelRow}>
                              <span className={[styles.subNavLabel, isActive ? styles.subNavLabelActive : ''].filter(Boolean).join(' ')}>
                                {item.label}
                              </span>
                              {status && (
                                <span
                                  className={[styles.statusDot, status === 'ok' ? styles.statusDotOk : styles.statusDotWarn].join(' ')}
                                  title={status === 'ok' ? 'Configured' : 'Action needed'}
                                  aria-label={status === 'ok' ? 'Configured' : 'Action needed'}
                                />
                              )}
                            </div>
                            <div className={styles.subNavDesc}>{item.desc}</div>
                          </div>
                          {isActive && (
                            <span className={styles.chev}>
                              <Icon name="chevright" size={13} color="var(--color-primary)" />
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  )
                })}
              </div>
            ))}
          </div>
        </Card>
      </nav>
      <div className={styles.content}>{children}</div>
    </div>
  )
}
