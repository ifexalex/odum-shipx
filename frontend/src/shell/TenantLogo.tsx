/**
 * The tenant's logo mark (FD-29): the uploaded image when there is one, else its initials on its brand colour. One
 * component for the settings page, its live preview and the printed documents, so they always agree.
 *
 * The image comes through a short-lived link (`branding_config.logo_url`). If it has expired by the time it loads (a
 * page left open for hours), the config is read again once for a fresh link, and the initials show meanwhile.
 */
import { QueryClientContext } from '@tanstack/react-query'
import { useContext, useRef, useState, type JSX } from 'react'
import { configKeys } from '../api/keys'
import { isValidHexColor } from '../design/deriveBrandShades'
import { initialsFor } from '../lib/initials'

export interface TenantLogoProps {
  /** The company name, for the initials and the image's alt text. */
  name: string
  /** The brand colour behind the initials; the theme's primary when unset or invalid. */
  color?: string | null
  logoUrl?: string | null
  /** Sizes the mark; the caller's class, so each place keeps its own size. */
  className?: string
  /** Fallback colour when `color` is not a valid hex (the print pages use a fixed green, not a CSS variable). */
  fallbackColor?: string
}

export function TenantLogo({
  name,
  color,
  logoUrl,
  className,
  fallbackColor = 'var(--color-primary)',
}: TenantLogoProps): JSX.Element {
  // Optional: a printed document rendered on its own (tests) has no query client, and then nothing is re-read.
  const qc = useContext(QueryClientContext)
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const refreshed = useRef(false)

  if (logoUrl && failedUrl !== logoUrl) {
    return (
      <img
        src={logoUrl}
        alt={`${name} logo`}
        className={className}
        style={{ objectFit: 'contain', background: 'transparent' }}
        onError={() => {
          setFailedUrl(logoUrl)
          if (!refreshed.current) {
            refreshed.current = true
            void qc?.invalidateQueries({ queryKey: configKeys.tenantConfig() })
          }
        }}
      />
    )
  }
  return (
    <div className={className} style={{ background: color && isValidHexColor(color) ? color : fallbackColor }} aria-hidden="true">
      {initialsFor(name)}
    </div>
  )
}
