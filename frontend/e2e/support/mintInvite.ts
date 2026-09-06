import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.join(__dirname, '../../..')

export interface MintedInvite {
  token: string
  customerId: string
}

/**
 * Mint a real, unconsumed customer invite via scripts/mint_test_invite.py and
 * return its plaintext token.
 *
 * The real API never returns a raw token — it's stored only as a SHA-256 hash
 * (shared/invites.py) — so there is no HTTP path to get one for testing
 * InviteClaimScreen. This shells out to the backend script that talks to the
 * DB directly, the same way issue_customer_invite() does internally, minus
 * the masking. Requires the local Postgres + the repo's Python env; skip
 * (or catch and `test.skip`) if that isn't available in a given run.
 */
export function mintTestInvite(): MintedInvite {
  let output: string
  try {
    output = execFileSync('python3', ['scripts/mint_test_invite.py'], {
      cwd: REPO_ROOT,
      encoding: 'utf-8',
      // Local Postgres/DB env vars must already be exported into the shell
      // running `npx playwright test` — this does not source .env.local itself.
    })
  } catch (err) {
    const stderr = (err as { stderr?: string }).stderr ?? String(err)
    if (stderr.includes('DATABASE_HOST')) {
      throw new Error(
        'mint_test_invite.py needs DB env vars. Run: set -a; source .env.local; set +a  (from the repo root) ' +
          'in the same shell before `npx playwright test`.',
      )
    }
    throw err
  }
  const [token, customerId] = output.trim().split(' ')
  if (!token || !customerId) {
    throw new Error(`mint_test_invite.py produced unexpected output: ${output}`)
  }
  return { token, customerId }
}
