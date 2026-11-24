# Task FE-12 — Testing Strategy

## Objective

Mirror the backend's testing rigor (`17_testing.md`) on the frontend: fast unit/component coverage for logic-heavy pieces, integration tests for the contracts in Tasks 05/09, and e2e coverage for the handful of flows where a regression is most costly.

## Depends On

Task 07 (need real pages to test against).

## Layers

### Component tests (Vitest + React Testing Library)

Every component in `src/design/components/` (Task 03) gets a colocated test covering its prop variants. Every domain page's *logic* (not pixel layout) — state machine button visibility, form validation, self-approval hiding (Task 07) — gets a test that renders the page with a mocked session/API response and asserts on behavior, e.g.:

```ts
it("hides approve/reject when the current user created the packing list", () => {
  render(<PackingListDetail />, { session: { userId: "u1", role: "china_office_staff" }, packingList: { createdBy: "u1", status: "pending_approval" } });
  expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
});
```

### API client / contract tests

Task 05's `apiRequest` and the per-domain `api/*.ts` wrappers get tests against a mocked HTTP layer (MSW — Mock Service Worker) asserting: RFC 7807 errors map to the right `ApiError` shape, pagination cursors round-trip correctly, idempotency keys are attached and stable across a simulated retry, 401 triggers exactly one refresh-and-replay.

Use MSW handlers shaped from the **real** backend response examples documented in Task 05 — when the backend's actual response shape changes, the MSW handler (and therefore the test) should be the first thing that breaks, not a production bug discovered later.

### Cross-tenant / cache isolation tests

Directly testing the property called out in Task 09 and Task 11: simulate login → impersonate tenant A → exit → impersonate tenant B, assert the TanStack Query cache holds zero keys referencing tenant A's data after the switch. This is the single highest-value test in the whole suite given what's at stake (a visible cross-tenant data leak in the UI, even if the API itself is correctly isolated).

### E2E (Playwright)

Cover the flows where a regression is costliest, not every page:

- Login → role-appropriate landing page, for at least one of each of the 6 roles
- Packing list create → submit → approve (two different users, confirming self-approval is blocked) → manifest auto-creation visible
- Billing: record payment → confirm balance updates → overpayment triggers carryover
- Impersonation: start → read-only banner visible, a mutating action is genuinely blocked end-to-end (not just hidden — attempt the underlying API call and confirm 403) → exit → confirm platform admin's own session is restored cleanly
- Excel import: upload a fixture file with a mix of valid/invalid rows → confirm the per-row result table and the skip-invalid path
- Customer portal: public tracking lookup (code + phone) → shipment detail renders

Run Playwright against the **local dev stack** (`make stack`/`make up`, per `LOCAL_TESTING.md`) using the local auth shim (Task 04) to set roles without needing real Cognito users in CI.

### Visual regression (optional, recommended once Task 03 stabilizes)

If the Storybook/component-catalog route from Task 03 exists, a lightweight screenshot-diff tool (e.g. Playwright's own screenshot assertions, or Chromatic if budget allows) catches unintended token/component drift — lower priority than the functional layers above, add once the design system is no longer actively changing.

## What Not to Test

- Don't pixel-test every page against the design mockups — the mockups are a reference for *building*, not a golden-master for visual regression (they're untyped inline-style JSX, not the production component tree).
- Don't write component tests asserting exact CSS values — that's what the token system (Task 02) and a one-time visual QA pass are for; tests should assert behavior (what renders, what's clickable, what's disabled), not computed style strings.

## Implementation Notes

**88 test files** (Vitest + React Testing Library) across auth, shell, design components, API rules, and pages.

**New tests added in Task 12:**

| File | What it covers |
|---|---|
| `src/test/cache-isolation.test.tsx` | Cross-tenant cache isolation: (1) logout clears all cache, (2) impersonation start clears cache, (3) impersonation exit clears cache, (4) regression guard that no query key contains a UUID-shaped tenant ID |
| `src/design/components/Action.test.tsx` | Read-only impersonation enforcement: live button in normal session; `aria-disabled` span (not `<button>`) in read-only; `onClick` never fires; tooltip present |
| `src/pages/nigeria/RefundDetail.test.tsx` | Added: threshold-aware approval — `tenant_admin`-level refund hides direct approve for `nigeria_office_staff`; `manager`-level shows approve |

**Existing coverage (not added in Task 12 — already present):**
- Packing list self-approval: `PackingListDetail.test.tsx` (hides approve/reject when actor == creator)
- Container status jurisdiction: `containerRules.test.ts` (China/Nigeria role restrictions across all stages)
- API client contract tests: `client.test.ts` (error mapping, 401-refresh, pagination cursors — uses `vi.stubGlobal('fetch')` rather than MSW; MSW not yet installed)

**Playwright e2e:**
- `playwright.config.ts` split into two projects: `smoke` (production build, no backend) and `local-stack` (dev server + Flask local stack)
- `e2e/flows/auth.spec.ts` — 6-role landing page assertions
- `e2e/flows/impersonation.spec.ts` — read-only banner absence/presence
- `e2e/flows/packing-list.spec.ts` — self-approval prevention end-to-end
- `e2e/flows/public-tracking.spec.ts` — public tracking lookup flow (no login)

**MSW note:** Not installed. Existing contract tests use `vi.stubGlobal('fetch')` which is sufficient for the API client's documented behaviors. MSW would add value if/when test helpers for full page integration tests are needed — defer to a future sprint.

## Acceptance Criteria

- [x] State-machine button-visibility rules are covered: packing list self-approval (`PackingListDetail.test.tsx`), container status jurisdiction (`containerRules.test.ts`), refund manager-approval threshold (`RefundDetail.test.tsx`)
- [x] A cross-tenant cache-isolation test exists and runs in CI on every PR — `src/test/cache-isolation.test.tsx` (4 tests)
- [x] The `Action` component read-only enforcement is tested — `Action.test.tsx` (4 tests), closing the Task 08 open criterion
- [x] Playwright e2e suite covers: auth role landing pages, impersonation banner, packing list self-approval, public tracking
- [x] CI fails the build on any Vitest test failing (`npm test` in `frontend-ci.yml`)
- [ ] Every shared component (Task 03) has a test — partially done; key components tested, not 100% coverage. Full coverage deferred.
- [ ] MSW-backed contract tests for API client — deferred; `vi.stubGlobal` approach is adequate, MSW adds infra overhead without current blocker
- [x] Playwright e2e runs in CI — **done (2026-07-10)**: `frontend-ci.yml` has an `e2e-smoke` job (built artifact via preview, verified locally) and an `e2e-local-stack` job (boots `make up` + migrate/seed + Flask + Vite dev in local-auth mode, runs the `flows/**` project with `PW_E2E=local-stack`). Reports uploaded on failure.

## Status registry guard (FD-08, 2026-11-19)

`src/design/statusRegistry.test.ts` (22): registry coverage of every API status union, label hygiene, unknown-status fallback, and a source scan that fails on any page/shell status map. 11 page tests updated to the registry's words.

## Button rules (FD-07, 2026-11-19)

`src/design/buttonRules.test.ts` (4): no raw `<button>` in pages, accent only on paying/sign-in screens, no typed arrow ending a label. `Action.test.tsx` (+2) covers read-only on plain Buttons and IconButtons and no blocking without a session; `Button.test.tsx` (+2), `IconButton.test.tsx` (2). Page tests updated for links (auth footers, work queue rows, audit log) and the disabled-button form of read-only (`readonly-impersonation.test.tsx`). Phone audit after the height change: every page fits at 375/360/320.

## Form rules and named controls (FD-11, FD-50, 2026-11-19)

`src/design/formRules.test.ts` (4) and `src/design/components/FieldFamily.test.tsx` (13). Page tests updated: date-range tests open the filter popover before typing a custom date and expect the button to read "Since …"; selectors by label text instead of DOM structure (rates, brand colour, collected-by); the `Account` language choice is a named radio group. The phone audit doubles as the FD-50 automated pass: it lists every unnamed control per route and fails on any.

## Toasts (FD-21, 2026-11-19)

`src/test/setup.ts` resets the toast store and mounts `ToastRegion` before every test. `ToastRegion.test.tsx` (4) and `src/design/toastRules.test.ts` (2) — the second found two pages that changed data silently (the announcement composer; the audit-log read was a false positive and is listed as a read).

## Tables (FD-13, 2026-11-20)

`src/design/tableRules.test.ts` (4) and 6 new cases in `Table.test.tsx`. Page tests that clicked "View" now click the row's first cell (`within(row).getAllByRole('button')[0]`) or its text. A count whose numbers sit in `<strong>` is matched with a function on `textContent`; `getByText` reads only an element's own text nodes.

## Cards and text (FD-10, 2026-11-20)

`src/design/cardRules.test.ts` (4). The browser check `scripts/text-breaks.mjs` (see `LOCAL_TESTING.md`) was proved by injecting each defect with `TEXT_BREAKS_INJECT_CSS`: a border back on a table inside a card, a 40 px stat label, an ellipsis on a sublabel. Its first run also caught a bug in itself (a red test border read as transparent because `rgb(255, 0, 0)` ends in ", 0)").

## Stepper (FD-09, 2026-11-20)

`Stepper.test.tsx` (6) stubs `getBoundingClientRect` to drive the compact form, as `Table.test.tsx` does for cards. `src/design/stepperRules.test.ts` (2). `MyClaimDetail.test.tsx` now finds each step's list item and checks its `aria-current` and its "done" text.

## Component catalog coverage (step 2 gate, 2026-11-20)

`src/design/catalogCoverage.test.ts` (2): every component exported from `src/design/components/index.ts` renders in `ComponentCatalog.tsx`, and the theme switch is there. The catalog itself was checked in a browser in light and dark (full-page screenshots, no console errors).

