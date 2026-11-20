/// <reference types="node" />
/**
 * FD-08: one status registry. Every status value the API types declare has an entry, and no page keeps its own
 * status-to-colour or status-to-words map (that is how a sealed container came to be blue on one page and amber on
 * another, and `at_warehouse` to read four different ways).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { NEUTRAL_SERIES_COLOR, STATUS_REGISTRY, statusColor, statusLabel, statusSeriesColors, statusVariant, statusesOf, type StatusKind } from './status'

const SRC = resolve(process.cwd(), 'src')

/** Each API status union, and the registry kind that must cover it. */
const UNIONS: Array<[file: string, type: string, kind: StatusKind]> = [
  ['api/tracking.ts', 'ContainerStatus', 'container'],
  ['api/billing.ts', 'PaymentStatus', 'invoice'],
  ['api/billing.ts', 'CBMDisputeStatus', 'dispute'],
  ['api/billing.ts', 'CarryoverStatus', 'carryover'],
  ['api/billing.ts', 'PaymentClaimStatus', 'paymentClaim'],
  ['api/packingList.ts', 'PackingListStatus', 'packingList'],
  ['api/claims.ts', 'DamageClaimStatus', 'claim'],
  ['api/claims.ts', 'MissingItemStatus', 'missingItem'],
  ['api/claims.ts', 'SeizedItemStatus', 'seizedItem'],
  ['api/manifest.ts', 'VerificationStatus', 'manifest'],
  ['api/refunds.ts', 'RefundStatus', 'refund'],
  ['api/releaseNotes.ts', 'ReleaseNoteStatus', 'releaseNote'],
  ['api/notifications.ts', 'NotifStatus', 'notification'],
  ['api/tenantManagement.ts', 'TenantStatus', 'tenant'],
  ['api/tenantManagement.ts', 'OnboardingRequestStatus', 'onboardingRequest'],
  ['api/tenantManagement.ts', 'OffboardingExportStatus', 'offboardingExport'],
]

function unionValues(file: string, type: string): string[] {
  const source = readFileSync(join(SRC, file), 'utf8')
  const match = source.match(new RegExp(`export type ${type} =((?:\\s*\\|?\\s*'[^']+')+)`))
  if (!match) throw new Error(`no union ${type} in ${file}`)
  return [...match[1]!.matchAll(/'([^']+)'/g)].map((m) => m[1]!)
}

function sources(dir: string): Array<[string, string]> {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    if (!/\.tsx?$/.test(name) || name.includes('.test.')) return []
    return [[relative(SRC, path), readFileSync(path, 'utf8')] as [string, string]]
  })
}

describe('status registry (FD-08)', () => {
  it.each(UNIONS)('%s %s is fully covered', (file, type, kind) => {
    const values = unionValues(file, type)
    expect(values.length).toBeGreaterThan(1)
    expect(statusesOf(kind).sort()).toEqual([...values].sort())
  })

  it('gives every entry words in sentence case and no raw codes', () => {
    for (const [kind, entries] of Object.entries(STATUS_REGISTRY)) {
      for (const [status, entry] of Object.entries(entries)) {
        for (const words of [entry.label, (entry as { customer?: string }).customer].filter(Boolean) as string[]) {
          expect(words, `${kind}.${status}`).not.toMatch(/_/)
          expect(words[0], `${kind}.${status}`).toBe(words[0]!.toUpperCase())
        }
      }
    }
  })

  it('reads the same status the same way everywhere', () => {
    expect(statusLabel('container', 'at_warehouse')).toBe('At warehouse')
    expect(statusLabel('container', 'at_warehouse', 'customer')).toBe('At warehouse')
    expect(statusLabel('invoice', 'released_with_outstanding')).toBe('Released, balance owed')
    expect(statusVariant('container', 'sealed')).toBe('info')
  })

  it('shows an unknown status in words, never as a code', () => {
    expect(statusLabel('container', 'held_at_port')).toBe('Held at port')
    expect(statusVariant('container', 'held_at_port')).toBe('neutral')
    expect(statusColor('container', 'cleared')).toBe('var(--color-primary)')
  })
})

describe('no page keeps its own status map (FD-08)', () => {
  const files = [...sources(join(SRC, 'pages')), ...sources(join(SRC, 'shell'))].filter(
    ([path]) => !path.startsWith('pages/marketing/'),
  )

  it('finds the pages it is meant to police', () => {
    expect(files.length).toBeGreaterThan(80)
  })

  it('declares no status-to-colour or status-to-words map', () => {
    const offenders = files.flatMap(([path, text]) =>
      [
        ...text.matchAll(/^(?:export )?const (\w+)\s*:\s*Record<[^>]*Status[^>]*,\s*(?:BadgeVariant|string|\{)/gm),
        ...text.matchAll(/^(?:export )?const (\w*(?:STATUS|VARIANT|BADGE)\w*)\s*:\s*Record<string,\s*BadgeVariant>/gm),
        ...text.matchAll(/^(?:export )?function (statusLabel|\w+StatusLabel|statusBadgeVariant|\w*[Ss]tatusVariant)\(/gm),
      ].map((m) => `${path}: ${m[1]}`),
    )
    expect(offenders).toEqual([])
  })

  it('picks no badge colour from a status by hand', () => {
    const offenders = files.flatMap(([path, text]) =>
      [...text.matchAll(/<Badge[^>]*variant=\{[^}]*\.(?:status|payment_status|verification_status)\s*===/g)].map(() => path),
    )
    expect(offenders).toEqual([])
  })
})

describe('chart colours (FD-52)', () => {
  it('colour each status series as its badge, and keep two of one colour apart', () => {
    const colors = statusSeriesColors('invoice', ['paid', 'partially_paid', 'unpaid', 'released_with_outstanding', 'waived'])
    expect(colors[0]).toBe(statusColor('invoice', 'paid'))
    expect(colors[2]).toBe(statusColor('invoice', 'unpaid'))
    // "Released, balance owed" is amber like its badge, never purple; it shares amber with "Partly paid", so darker.
    expect(colors[1]).toBe('var(--color-warning)')
    expect(colors[3]).toBe('var(--color-warning-strong)')
    expect(new Set(colors).size).toBe(colors.length)
  })

  it('a series that is not a status is one neutral colour', () => {
    expect(NEUTRAL_SERIES_COLOR).toBe('var(--color-ink-3)')
  })
})
