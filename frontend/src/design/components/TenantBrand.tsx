import type { JSX } from 'react'
import styles from './TenantBrand.module.css'

export interface TenantBrandProps {
  /** `tenant.branding_config.display_name` */
  name: string
  /** `tenant.branding_config` uploaded logo URL, if any. */
  logoUrl?: string
}

// Renders in the Sidebar brand slot in place of the ShipX wordmark once a
// tenant theme is active (see ThemeProvider, 02_design_tokens_and_theming.md).
export function TenantBrand({ name, logoUrl }: TenantBrandProps): JSX.Element {
  const initials = name.trim().slice(0, 2).toUpperCase()
  return (
    <div className={styles.brand}>
      <div className={styles.mark}>
        {logoUrl ? <img className={styles.logoImg} src={logoUrl} alt={name} /> : initials}
      </div>
      <div className={styles.text}>
        <div className={styles.name}>{name}</div>
        <div className={styles.tag}>on ShipX</div>
      </div>
    </div>
  )
}
