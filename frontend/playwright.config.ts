import { defineConfig, devices } from '@playwright/test'

/**
 * Two projects:
 *
 * "smoke" — runs against `npm run preview` (production build, no backend).
 *   Used for fast sanity checks on the build artifact. Single test file.
 *
 * "local-stack" — runs against the Vite dev server (port 5173) which connects
 *   to the Flask local server (make stack / make up per LOCAL_TESTING.md).
 *   Uses LocalAuthProvider's role-switcher so no real Cognito users are needed.
 *   These are the meaningful e2e flows; they require the local stack to be running.
 */
// The preview server (port 4173) backs the "smoke" project and is managed by
// Playwright. The "local-stack" project talks to the Vite dev server (5173) +
// Flask backend, which the CI job starts itself — so we skip the managed
// preview server for that run by setting PW_E2E=local-stack. Locally (no CI),
// the preview server is always defined and reused if already running.
const runningLocalStack = process.env.PW_E2E === 'local-stack'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',

  // One worker everywhere, because CI already uses one and the difference was
  // actively hiding bugs.
  //
  // Playwright defaults `workers` to 1 on CI but to half the CPU count locally,
  // so a local run and the CI run were different tests. Each exposed failures
  // the other could not: in parallel, specs that mutate shared seed data
  // skipped instead of running, and `networkidle` waits timed out because the
  // local API serves one request at a time by design (scripts/local_server.py
  // sets threaded=False — shared/db.py's connection singleton is not
  // thread-safe); serially, those same specs ran and found real defects.
  //
  // Serial is also the honest model for this suite: one API connection, and
  // specs that share tenant state. It costs wall-clock time (~10 min for the
  // local-stack project) and buys a local result that means something.
  workers: 1,

  ...(runningLocalStack
    ? {}
    : {
        webServer: {
          command: 'npm run preview',
          url: 'http://localhost:4173',
          reuseExistingServer: !process.env.CI,
        },
      }),

  projects: [
    {
      name: 'smoke',
      testMatch: 'smoke.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:4173',
      },
    },
    {
      name: 'local-stack',
      testMatch: 'flows/**/*.spec.ts',
      // 90s, not Playwright's 30s default: every case here drives a real
      // backend over a connection that handles one request at a time, so a
      // page that needs several queries can legitimately take tens of seconds
      // while other work is queued ahead of it. At 30s a different test
      // tripped the limit on each run — always a bare timeout, never a failed
      // assertion. Specs needing even more (real Cognito round-trips) raise it
      // themselves via test.describe.configure.
      timeout: 90_000,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5173',
      },
    },
  ],
})
