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
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:5173',
      },
    },
  ],
})
