import type { Page } from '@playwright/test'

/**
 * Switch the local dev auth shim's active identity and wait for it to take
 * effect before interacting further.
 *
 * `#local-role-switcher`'s onChange updates LocalRoleContext asynchronously;
 * proceeding immediately can still act under the old role, so callers that
 * read `session.role` right after switching (RoleGuard included) may see a
 * stale value without this wait.
 */
export async function switchRole(page: Page, role: string): Promise<void> {
  await page.goto('/')
  await page.selectOption('#local-role-switcher', role)
  await page.waitForTimeout(200)
}

/**
 * Navigate to `path` **within the SPA** by clicking a nav link, rather than
 * `page.goto()`.
 *
 * The dev identity lives only in React state (LocalAuthProvider), with
 * nothing to persist it across a reload. `page.goto()` is a real browser
 * navigation — it reloads the page, which remounts the provider back to its
 * default identity (`platform_admin`) and silently undoes any prior
 * `switchRole()`. This bit packing-list.spec.ts: it switched to
 * china_office_staff, then called `page.goto('/packing-lists')`, which
 * reloaded the app back to platform_admin and got redirected to
 * /platform/dashboard by RoleGuard before the test's assertions ran.
 *
 * Use this for any navigation that must happen after `switchRole()`. Going
 * straight to a route with `page.goto()` is still fine as the *first*
 * navigation in a test, before any role switch.
 */
export async function goToViaNav(page: Page, linkName: string | RegExp): Promise<void> {
  // Sidebar nav items (src/shell/Sidebar.tsx) render as <button onClick=...>,
  // not <a>, so they carry the "button" accessible role rather than "link".
  await page.getByRole('button', { name: linkName }).first().click()
  await page.waitForLoadState('networkidle')
}
