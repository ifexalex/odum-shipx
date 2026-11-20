/// <reference types="node" />
/**
 * FD-21: a page confirms a change with a toast, not with its own "saved" state and a success banner, and every page
 * that changes data confirms it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')

function sources(dir: string): Array<[string, string]> {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    if (!/\.tsx?$/.test(name) || name.includes('.test.')) return []
    return [[relative(SRC, path), readFileSync(path, 'utf8')] as [string, string]]
  })
}

const files = [...sources(join(SRC, 'pages')), ...sources(join(SRC, 'shell'))].filter(
  ([p]) => !p.startsWith('pages/marketing/') && !p.startsWith('pages/print/'),
)

// API methods that read or fetch a file; anything else on an `xxxApi` changes data.
const READS =
  /^(get|list\w*|\w+List|stats|search|export\w*|download\w*|lookup|presign\w*|getUrl|getEvidenceUploadUrl|report|activity|history|events|for\w*|me|summary|preview|pdf|verifyPayment|initializePayment|\w*Stats|\w+ByContainer|byId|query\w*|fetch\w*|count\w*|check\w*|validate\w*|auditLog)$/

/** Pages that change data but show the outcome as a whole screen or result panel instead of a toast. */
const RESULT_SCREENS: Record<string, string> = {
  'pages/auth/ActivateScreen.tsx': 'account activated screen',
  'pages/auth/InviteClaimScreen.tsx': 'account created screen',
  'pages/auth/RegisterScreen.tsx': 'registration done screen',
  'pages/auth/RequestOnboardingScreen.tsx': 'request received screen',
  'pages/auth/ResetPasswordScreen.tsx': 'password changed screen',
  'pages/auth/ForgotPasswordScreen.tsx': 'code sent screen',
  'pages/nigeria/GenerateBillingModal.tsx': 'invoice outcome panel',
  'pages/china/InvoiceOutcomeBanner.tsx': 'invoice outcome panel',
  'pages/china/ImportPackingLists.tsx': 'import results panel',
  'pages/platform/PlatformTenantDetail.tsx': 'impersonation opens the tenant',
  'pages/tenant-admin/WebhookConfig.tsx': 'new secret and test result panels',
  'pages/customer/Account.tsx': 'erasure signs the customer out',
}

describe('toast rules (FD-21)', () => {
  it('no page keeps its own "saved" or "success" state', () => {
    const offenders = files.flatMap(([path, text]) =>
      [
        ...text.matchAll(
          /const \[(saved|success|saveSuccess|actionMsg|notice|successMsg|savedAt), set\w+\] = useState/g,
        ),
      ].map((m) => `${path}: ${m[1]}`),
    )
    expect(offenders).toEqual([])
  })

  it('every page that changes data confirms it with a toast', () => {
    const offenders = files
      .filter(([path, text]) => {
        const writes = [...text.matchAll(/\b\w+Api\.(\w+)\(/g)].filter((m) => !READS.test(m[1]!))
        return (
          writes.length > 0 &&
          !/\btoast\.(success|info|error)\(/.test(text) &&
          !(path in RESULT_SCREENS)
        )
      })
      .map(([path]) => path)
    expect(offenders).toEqual([])
  })
})
