import { useQuery, useQueryClient } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { useRef, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configApi, type RegistrationLinkSettings } from '../../api/tenantManagement'
import { Badge, Banner, Button, Card, Icon } from '../../design/components'
import { STALE_30S } from '../../lib/queryClient'
import styles from './CustomerSignupLink.module.css'

const REGISTRATION_LINK_KEY = ['config', 'registration-link'] as const

/**
 * The company's own customer signup link, with a QR code and an on/off switch.
 *
 * This sits beside the invite flow rather than replacing it. Invites remain the
 * way to onboard a *known* customer — the company has their details and wants
 * that specific person to have an account. The link is for the other direction:
 * put it on a receipt, a shopfront or a WhatsApp broadcast and let customers
 * bring themselves.
 *
 * It does not "create" anything. `POST /v1/register/{slug}` has been public
 * since it was written, so every tenant has had a working signup link whether
 * or not anyone told them. What was missing was any way to *see* it, share it,
 * or turn it off — which is what this is.
 */
export function CustomerSignupLink(): JSX.Element {
  const qc = useQueryClient()
  const { data: settings = null, error: loadError } = useQuery({
    queryKey: REGISTRATION_LINK_KEY,
    queryFn: () => configApi.getRegistrationLink(),
    staleTime: STALE_30S,
  })
  const [actionError, setActionError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showQr, setShowQr] = useState(false)
  const qrRef = useRef<HTMLDivElement>(null)

  const error =
    actionError ??
    (loadError ? (loadError instanceof ApiError ? loadError.message : 'Could not load the signup link.') : null)

  // Built from the browser's own origin rather than a configured base URL:
  // this is the address a customer will visit, and the app is served from it.
  // A hardcoded or env-supplied host would silently hand out a link to the
  // wrong environment the moment one of them moved.
  const signupUrl = settings?.slug ? `${window.location.origin}/register/${settings.slug}` : null

  async function copyLink(): Promise<void> {
    if (!signupUrl) return
    try {
      await navigator.clipboard.writeText(signupUrl)
      setCopied(true)
      // Reverts on its own; a permanent "Copied" would leave the button lying
      // about the clipboard's contents minutes later.
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setActionError('Could not copy — select the link and copy it manually.')
    }
  }

  async function toggle(enabled: boolean): Promise<void> {
    setSaving(true)
    setActionError(null)
    try {
      const updated = await configApi.setRegistrationLinkEnabled(enabled)
      qc.setQueryData<RegistrationLinkSettings>(REGISTRATION_LINK_KEY, updated)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not update the signup link.')
    } finally {
      setSaving(false)
    }
  }

  /** Download the QR as an SVG, which prints at any size without blurring. */
  function downloadQr(): void {
    const svg = qrRef.current?.querySelector('svg')
    if (!svg || !settings?.slug) return
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${settings.slug}-signup-qr.svg`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!settings) {
    return (
      <Card>
        <div className={styles.loading}>{error ?? 'Loading signup link…'}</div>
      </Card>
    )
  }

  return (
    <Card>
      <div className={styles.head}>
        <div>
          <h3 className={styles.title}>
            Customer signup link{' '}
            <Badge variant={settings.enabled ? 'success' : 'neutral'} size="sm">
              {settings.enabled ? 'Active' : 'Off'}
            </Badge>
          </h3>
          <p className={styles.sub}>
            Share this and customers can create their own account with your company — no invite
            needed. Inviting individual customers still works exactly as before.
          </p>
        </div>
        <Button
          variant={settings.enabled ? 'ghost' : 'primary'}
          loading={saving}
          onClick={() => void toggle(!settings.enabled)}
        >
          {settings.enabled ? 'Turn off' : 'Turn on'}
        </Button>
      </div>

      {error && (
        <div className={styles.spacer}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {signupUrl ? (
        <>
          <div className={styles.linkRow}>
            <code className={styles.link} data-testid="signup-url">
              {signupUrl}
            </code>
            {/* No icon until it has copied: the design system has no copy
                glyph, and borrowing a near-miss would say the wrong thing. */}
            <Button variant="secondary" icon={copied ? 'check' : undefined} onClick={() => void copyLink()}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button variant="ghost" icon="qr" onClick={() => setShowQr((v) => !v)}>
              {showQr ? 'Hide QR' : 'Show QR'}
            </Button>
          </div>

          {showQr && (
            <div className={styles.qrBlock} ref={qrRef}>
              {/* Rendered as SVG so it stays sharp printed on a poster at any
                  size. High error correction, because a QR on a shopfront or a
                  receipt gets scuffed, folded and photographed at an angle. */}
              <QRCodeSVG value={signupUrl} size={168} level="H" includeMargin />
              <div className={styles.qrSide}>
                <p className={styles.qrHint}>
                  Customers scan this to open your signup page. Print it, put it on a receipt, or
                  send the image.
                </p>
                <Button variant="secondary" icon="download" onClick={downloadQr}>
                  Download SVG
                </Button>
              </div>
            </div>
          )}

          {!settings.enabled && (
            <div className={styles.spacer}>
              <Banner variant="warning">
                The link is switched off — anyone opening it is told the company is not accepting
                new registrations. Existing customers and invites are unaffected.
              </Banner>
            </div>
          )}
        </>
      ) : (
        <Banner variant="warning">
          This company has no URL slug yet, so a signup link cannot be built. Contact support.
        </Banner>
      )}

      <p className={styles.foot}>
        <Icon name="info" size={12} /> Anyone with the link can sign up as your customer. Turn it off
        if you would rather invite customers individually.
      </p>
    </Card>
  )
}
