import type { JSX } from 'react'
import { TenantLogo } from '../../shell/TenantLogo'
import styles from './TenantBrand.module.css'

export interface TenantBrandProps {
  /** `tenant.branding_config.display_name` */
  name: string
  /** `tenant.branding_config.logo_url` uploaded logo URL, if any. */
  logoUrl?: string | null
  /** `tenant.branding_config.primary_color` for the initials fallback tile. */
  color?: string | null
  /** 'dark' for dark/brand-filled chrome (sidebar, customer topbar); 'light' for light surfaces (mobile drawer). */
  surface?: 'dark' | 'light'
  /** Hide the company name (e.g. collapsed sidebar). */
  compact?: boolean
  /** Optional subtitle below the company name (e.g. "on ShipX"). Defaults to hidden since shells show PoweredByShipx in their footer. */
  showTag?: boolean
}

/**
 * Renders the tenant's logo (or brand-colored initials fallback) and display
 * name in place of the ShipX wordmark across tenant-branded shells.
 */
export function TenantBrand({
  name,
  logoUrl,
  color,
  surface = 'dark',
  compact = false,
  showTag = false,
}: TenantBrandProps): JSX.Element {
  const hasLogo = Boolean(logoUrl)
  return (
    <div className={styles.brand} title={compact ? name : undefined}>
      <div className={[styles.mark, hasLogo ? styles.markWithLogo : ''].filter(Boolean).join(' ')}>
        <TenantLogo
          name={name}
          color={color}
          logoUrl={logoUrl}
          className={styles.logoInner}
        />
      </div>
      {!compact && (
        <div className={styles.text}>
          <div className={[styles.name, surface === 'light' ? styles.nameOnLight : ''].filter(Boolean).join(' ')}>
            {name}
          </div>
          {showTag && (
            <div className={[styles.tag, surface === 'light' ? styles.tagOnLight : ''].filter(Boolean).join(' ')}>
              on ShipX
            </div>
          )}
        </div>
      )}
    </div>
  )
}
