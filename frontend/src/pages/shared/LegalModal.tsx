import type { JSX } from 'react'
import { Button, Modal } from '../../design/components'

export type LegalDocKind = 'terms' | 'privacy' | 'dpa'

const TITLES: Record<LegalDocKind, string> = {
  terms: 'Terms of Service',
  privacy: 'Privacy Policy (NDPR)',
  dpa: 'Data Processing Addendum',
}

export function LegalModal({
  kind,
  onClose,
}: {
  kind: LegalDocKind | null
  onClose: () => void
}): JSX.Element {
  return (
    <Modal
      open={kind !== null}
      onClose={onClose}
      title={kind ? TITLES[kind] : ''}
      size="sm"
      footer={
        <Button variant="primary" onClick={onClose}>
          Close
        </Button>
      }
    >
      {kind === 'terms' && (
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <p style={{ margin: 0 }}>
            Your ShipX account gives you access to shipment tracking, invoices, release notes, and claims managed
            through your shipping company&apos;s workspace.
          </p>
          <p style={{ margin: 0 }}>
            Keep your sign-in credentials and warehouse pickup codes confidential. Freight rates, customs clearance,
            storage fees, and delivery terms are set directly by your shipping company.
          </p>
          <p style={{ margin: 0 }}>
            For platform-level questions or enterprise agreements, contact{' '}
            <a href="mailto:hello@shipx.co">hello@shipx.co</a>.
          </p>
        </div>
      )}
      {kind === 'privacy' && (
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <p style={{ margin: 0 }}>
            We collect your name, email address, phone number, and optional WhatsApp number solely to manage your
            shipments, billing, release notes, and account security with your shipping company.
          </p>
          <p style={{ margin: 0 }}>
            Transactional shipment and invoice notifications are sent automatically. Optional announcements and offers
            are only sent via channels you explicitly opt into, and you may update your preferences or request data
            export/erasure (NDPR / GDPR) at any time.
          </p>
        </div>
      )}
      {kind === 'dpa' && (
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <p style={{ margin: 0 }}>
            Each shipping company on ShipX operates in an isolated tenant workspace protected by row-level database
            isolation, encryption in transit and at rest, and role-based access controls.
          </p>
          <p style={{ margin: 0 }}>
            ShipX (a product by ODUM) acts as data processor for tenant customer records under applicable NDPR and
            GDPR requirements. To request a signed DPA for your organisation, email{' '}
            <a href="mailto:hello@shipx.co">hello@shipx.co</a>.
          </p>
        </div>
      )}
    </Modal>
  )
}
