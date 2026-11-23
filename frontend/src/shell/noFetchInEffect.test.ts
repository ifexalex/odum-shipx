/**
 * Drift guard for FE-05: pages do not load server data in a `useEffect`.
 *
 * A page that fetches by hand in an effect misses the shared cache, the retry policy and the central invalidation
 * (api/cacheInvalidation.ts), so its data goes stale after someone else's write and each one handles loading and
 * errors differently. Reads go through a React Query hook in `src/hooks/`.
 *
 * What this catches: an effect whose body calls an API module (`fooApi.bar(...)`, or the same object imported under
 * another name, e.g. `import { platformApi as platformExtras }`), directly or through a function defined in the same
 * file. Effects that do not fetch (focus, timers, subscriptions, copying query data into a form once) are fine.
 *
 * The alias case was missed until 2026-11-17: three tabs of PlatformTenantDetail fetched in effects through
 * `platformExtras` and the guard passed.
 */
import { describe, expect, it } from 'vitest'

const SOURCES = import.meta.glob(['../pages/**/*.tsx', '../shell/**/*.tsx', '../design/**/*.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/**
 * The one effect allowed to call an API module, and why. It is not a read: landing on the page after a Paystack
 * redirect POSTs the reference once so the server can verify and record the payment. A query would retry and refetch
 * a write.
 */
const ALLOWED = new Set(['../pages/customer/PaymentSuccess.tsx: billingApi.verifyPayment'])

/** Local names bound to an API object by an aliased import from an `api/` module (`import { xApi as y }`). */
function aliasedApiObjects(text: string): string[] {
  const names: string[] = []
  for (const imported of text.matchAll(/import\s*\{([^}]*)\}\s*from\s*'[^']*\/api\/[^']*'/g)) {
    for (const spec of imported[1]!.split(',')) {
      const alias = /^\s*(\w+Api)\s+as\s+(\w+)\s*$/.exec(spec)
      if (alias) names.push(alias[2]!)
    }
  }
  return names
}

/** Matches a call on an API object in this file: any `*Api.method(`, plus the file's aliases. */
function apiCallPattern(text: string): RegExp {
  const names = ['\\w+Api', ...aliasedApiObjects(text)]
  return new RegExp(`\\b((?:${names.join('|')})\\.\\w+)\\(`, 'g')
}

/** The text of the `{ ... }` block that opens at `open`. */
function block(text: string, open: number): string {
  let depth = 1
  let i = open + 1
  while (depth > 0 && i < text.length) {
    if (text[i] === '{') depth++
    else if (text[i] === '}') depth--
    i++
  }
  return text.slice(open, i)
}

/** Functions declared in the file whose body calls an API module. */
function fetchingFunctions(text: string, API_CALL: RegExp): Map<string, string> {
  const found = new Map<string, string>()
  const declarations = [
    /(?:async\s+)?function\s+(\w+)\s*\([^)]*\)[^{]*\{/g,
    /const\s+(\w+)\s*=\s*(?:useCallback\()?\s*(?:async\s*)?\([^)]*\)\s*(?::[^=]+)?=>\s*\{/g,
  ]
  for (const pattern of declarations) {
    for (const match of text.matchAll(pattern)) {
      const call = API_CALL.exec(block(text, match.index + match[0].length - 1))
      API_CALL.lastIndex = 0
      if (call) found.set(match[1]!, call[1]!)
    }
  }
  return found
}

function fetchesInEffects(path: string, text: string): string[] {
  const API_CALL = apiCallPattern(text)
  const fetchers = fetchingFunctions(text, API_CALL)
  const offences: string[] = []
  for (const match of text.matchAll(/useEffect\(\s*(?:async\s*)?(?:\(\)\s*=>|function\s*\w*\s*\(\))\s*\{/g)) {
    const body = block(text, match.index + match[0].length - 1)
    for (const call of body.matchAll(API_CALL)) offences.push(`${path}: ${call[1]}`)
    for (const [name, api] of fetchers) {
      if (new RegExp(`\\b${name}\\(`).test(body)) offences.push(`${path}: ${api}`)
    }
  }
  return offences
}

describe('no page loads server data in a useEffect (FE-05)', () => {
  const offences = Object.entries(SOURCES)
    .filter(([path]) => !path.includes('.test.'))
    .flatMap(([path, text]) => fetchesInEffects(path, text))

  it('finds the sources it is meant to scan', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100)
  })

  it('has no effect that calls an API module, except the documented one', () => {
    expect(offences.filter((offence) => !ALLOWED.has(offence))).toEqual([])
  })

  it('still needs its one exception (remove it from ALLOWED when the code no longer does this)', () => {
    expect(offences.filter((offence) => ALLOWED.has(offence))).toEqual([...ALLOWED])
  })

  it('recognises a fetch in an effect, directly and through a local function', () => {
    const direct = 'function P() { useEffect(() => { void fooApi.list().then(setRows) }, []) }'
    const indirect = 'function P() { async function load() { setRows(await fooApi.list()) }\n useEffect(() => { void load() }, []) }'
    const harmless = 'function P() { const q = useFoo()\n useEffect(() => { ref.current?.focus() }, []) }'
    expect(fetchesInEffects('x.tsx', direct)).toEqual(['x.tsx: fooApi.list'])
    expect(fetchesInEffects('x.tsx', indirect)).toEqual(['x.tsx: fooApi.list'])
    expect(fetchesInEffects('x.tsx', harmless)).toEqual([])
  })

  it('recognises an API object imported under another name', () => {
    const aliased =
      "import { platformApi as platformExtras, type Tenant } from '../../api/tenantManagement'\n" +
      'function P() { useEffect(() => { void (async () => { setUsers(await platformExtras.tenantUsers(id)) })() }, [id]) }'
    expect(fetchesInEffects('x.tsx', aliased)).toEqual(['x.tsx: platformExtras.tenantUsers'])
  })
})
