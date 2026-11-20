# Task FE-03 — Shared Component Library

## Objective

Port the reusable UI primitives from `Shipx_frontend_design/screens/shared/components.jsx` and `app-shell.jsx` into typed, production React components under `src/design/components/`. Every domain page (Task 07) is built exclusively from these — no one-off styled divs in page code.

## Depends On

Task 02 (tokens must exist before components can consume them).

## Source

`Shipx_frontend_design/screens/shared/components.jsx` (447 lines) and `app-shell.jsx` (256 lines) are the reference implementation. They're untyped inline-style React — port the **prop contracts and visual behavior**, not the literal code (replace inline `style={{...}}` objects with CSS Modules referencing the tokens from Task 02).

## Component Inventory

### Primitives (`components.jsx`)

| Component | Props (typed contract to implement) | Notes |
|---|---|---|
| `Icon` | `name: IconName; size?: number; color?: string; stroke?: number; fill?: boolean` | ~60 named line icons as inline SVG paths. Define `IconName` as a string union, not `string`, so unknown icon names fail at compile time. |
| `Button` | `variant: 'primary'\|'accent'\|'secondary'\|'ghost'\|'danger'\|'danger-outline'\|'success'; size?: 'sm'\|'md'\|'lg'; icon?: IconName; trailingIcon?: IconName; loading?: boolean; disabled?: boolean; full?: boolean; onClick` | `accent` (Kola Copper) — enforce the "one per screen" design rule with an ESLint rule or runtime dev-warning if more than one `accent` button renders in the same page tree. |
| `Badge` | `variant: 'success'\|'warning'\|'error'\|'info'\|'accent'\|'purple'\|'neutral'\|'primary'; size?: 'sm'\|'md'; dot?: boolean` | Pill-shaped. `purple` = platform role badge. |
| `Card` | `padding?: number; radius?: number; children` | Base container, 1px border + `--shadow-rest`, default padding 24px, default radius `--radius-md`. |
| `StatCard` | `label; value; suffix?; trend?: { direction: 'up'\|'down'; pct: number }; sublabel?; icon?: IconName; accentColor?` | Dashboard metric tile. |
| `Field` | `label; type?; icon?: IconName; trailing?: ReactNode; placeholder?; value; onChange; error?: string; helper?: string; multiline?: boolean; optional?: boolean; required?: boolean` | Form input wrapper. 1px border at rest (`--color-line`), 2px `--color-primary` + focus ring on focus, red border + message on `error`. Wire directly to react-hook-form's `register`/`Controller`. |
| `Table` | `columns: { title: string; type?: 'text'\|'reference'\|'number'\|'money'\|'date'\|'status'\|'action'; width?: string; align?: 'left'\|'right'\|'center'; sortable?: boolean; hideInCard?: boolean }[]; rows: { cells: ReactNode[]; onOpen?: () => void; openLabel?: string; selected?: boolean; selectable?: boolean; suspended?: boolean }[]; selectable?: boolean; dense?: boolean; loading?: boolean; emptyState?: ReactNode; sort?; onSort?; cardBreakpoint?: number` | Drives every list page in Task 07. Loading skeleton and empty-state slot built in. A column's `type` sets its alignment and font (FD-13, below). `onOpen` makes the row open its record: the first cell becomes the keyboard button and a click anywhere on the row opens it. Below `cardBreakpoint` (default **600px** since FD-13, was 860px; measured via `ResizeObserver` on its own wrapper) it renders a card list instead of scrolling the table sideways — see the 2026-09-20 addendum below. |
| `Check` | `checked?: boolean; partial?: boolean; onChange` | Checkbox primitive, supports tri-state for "select all" headers. |
| `Mono` | `children; color?` | Monospace span — **always** wrap tracking codes, container numbers, and monetary amounts in this (design rule from Task 02). |
| `Avatar` | `name?: string; src?: string; size?: number; roleColor?: keyof typeof roleColors` | Circular initials-or-image, role-tinted border/background. |
| `Banner` | `variant: 'info'\|'success'\|'warning'\|'error'; title?; icon?: IconName; action?: ReactNode; dismissible?: boolean` | Inline alert box — used heavily for read-only impersonation state (Task 08), storage-fee grace-period warnings, GDPR notices. |
| `Chip` | `label; active?: boolean; count?: number; dismissible?: boolean; onDismiss?` | Filter pill. |
| `Modal` / `ModalOverlay` | `open; onClose; title?; width?; children; footer?: ReactNode` | Full-screen on mobile (see Task 02 spacing rules), centered with `--shadow-modal` + `--scrim-modal` backdrop on desktop. **Most hand-rolled per-page modals do not use this component (they get the same focus behaviour from `<DialogGuard>`, see "Modal focus management" below)** — see the 2026-09-20 addendum's canonical CSS pattern, applied to each page's own local modal markup instead of migrating them onto this component (a separate, larger JSX refactor, deliberately out of scope for the responsive pass). |
| `ToggleSwitch` | `checked; onChange; disabled?` | Used for webhook event toggles, notification preferences (Task 08). |
| `Combobox` | `options: { value; label; meta? }[]; value; onChange; placeholder?; searchPlaceholder?; disabled?; emptyText?; id?; ariaLabel?` | Searchable single-select (2026-10-01). A button opens a filter box + keyboard-navigable listbox; filters on label **and** meta. Better UX than a native `<select>` for long lists — the create-container capacity picker and the packing-list container picker. Each option is an `<li role="option">` carrying the select handler (not an inner button), so a row click selects. |
| `ThemeToggle` | `className?` | Light/dark theme control (2026-10-01). Single button cycling System → Light → Dark via `useColorScheme()`; icon reflects the preference (`monitor`/`sun`/`moon`). Placed in `TopBar` and `CustomerTopNav` (the latter passes its own `className` to match the dark header). See [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md) §Light / Dark theme. |

### App Shell (`app-shell.jsx`)

| Component | Contract | Notes |
|---|---|---|
| `Sidebar` | `role: Role; brand?: ReactNode; items: NavGroup[]; user?: { name; role }; collapsed?: boolean; onLogout?: () => void` | Fixed 240px desktop, 64px icon-only collapsed, replaced by bottom nav on mobile. Background `--color-forest-dark`. Active item: lighter bg + left border in the role's accent color. `user` is optional — the footer's logout button renders off `onLogout` alone (Task 06: `Session` carries no display name yet), and shows the avatar/name row only when `user` is also given. Full nav tree per role is in [06_routing_rbac_and_navigation.md](06_routing_rbac_and_navigation.md). |
| `TopBar` | `role: Role; title; breadcrumb?: string[]; user; search?: boolean; actions?: ReactNode` | Fixed 64px height. Notification bell with unread-count badge wires to `GET /v1/notifications/log` (Task 07). |
| `PageShell` | `sidebar: ReactNode; topbar: ReactNode; children` | Flex layout root every authenticated page renders inside. |
| `PageHeader` | `eyebrow?; title; subtitle?; actions?: ReactNode` | Page-level title block. |
| `SectionHead` | `title; sub?; action?: ReactNode` | Card-level title block. |
| `Tabs` | `items: { key; label }[]; active: string; onChange` | Horizontal tab strip, green underline active state. |

### Brand Marks

| Component | Notes |
|---|---|
| `KolaMark` | Ported SVG, see Task 02. |
| `ShipxWordmark` | "shipx" lowercase, copper-accented "x". `showBy` prop renders the small "by Odum" co-mark for pre-auth/marketing surfaces only. |
| `TenantBrand` | Renders tenant `display_name` + optional uploaded logo in the sidebar brand slot once a tenant theme is active (Task 02). |

## Form inputs for country, state and phone (2026-11-02)

User instruction: *"Anywhere in the application where a country/state is
required, use a drop down with search instead of typing"*, and *"phone number
fields are typed manually, it should be a phone field with country code
defaulted to Nigeria."* Three components, all built on the existing `Combobox`
so searching and keyboard behaviour match the rest of the app.

| Component | Emits | Notes |
|---|---|---|
| `CountrySelect` | country **name** | Searchable by name *or* dial code ("234" finds Nigeria). Operating markets listed first. |
| `StateSelect` | subdivision name | Driven by a `country` prop. Label follows local usage — State / Province / Region. |
| `PhoneField` | **E.164** (`+2348012345678`) | Dial-code picker + national number. Defaults to Nigeria. |

**Why names, not ISO codes.** Every existing column stores a country name
(`tenant.origin_country`, `warehouse.country`), so emitting a code would mean a
migration plus a display mapping on every read. `countryByName()` resolves a
stored name case-insensitively, and an **unrecognised** stored value is kept as
its own option rather than silently dropped — a row typed by hand years ago must
not lose its country because this list spells it differently.

**Why `PhoneField` emits E.164.** It is what the database stores
(`shared/phone.py` normalises every write path), so emitting it means customer
de-duplication works and the backend never has to guess a country — a `+`-prefixed
number is passed through untouched, so a dial code the backend's `_DIAL_CODES`
table has never heard of is still stored correctly. The component is fully
controlled: the country lives in the *parsed value*, not in local state, so there
is one source of truth and no effect is needed to resync when a parent loads a
record.

**Deliberate free-text fallback.** `subdivisions.ts` carries lists only for the
markets ShipX operates in (NG, CN, GH, ZA, GB, US). For any other country
`StateSelect` renders a **text input** with an explanatory helper, because an
empty dropdown would make the field impossible to fill — strictly worse than
typing. A full ISO 3166-2 dataset would be tens of thousands of entries, almost
none of them reachable in this business.

**Accuracy of the dataset.** `countries.ts` is hand-curated (196 countries)
rather than pulled from `libphonenumber-js`, which would add ~80KB+ to format one
field. The risk of curating by hand is pinned by tests: `countries.test.ts`
asserts structural invariants (unique codes, plausible dial codes, sorted
subdivisions), and **`tests/unit/test_phone.py::TestFrontendDialCodesAgree`
parses `countries.ts` from the backend suite** and asserts it agrees with
`shared/phone.py::_DIAL_CODES` for every country the backend knows, plus that the
frontend default is still Nigeria. That seam is where a wrong value would actually
do damage, since the backend prepends a dial code to local-format numbers.

**Known limitation.** Some dial codes are genuinely shared (+1 across the US,
Canada and much of the Caribbean; +7 across Russia and Kazakhstan) and cannot be
resolved from the prefix alone without area-code tables. `parsePhone` breaks the
tie toward an operating market for determinism. The ambiguity is **cosmetic**:
both candidates share the dial code, so `toE164` reassembles the identical string
and the stored value is unaffected.

**Bug caught during the rollout.** `toE164` tested for emptiness *before*
stripping the trunk `0`, so a lone `"0"` — which exists for one keystroke while
someone types `0803…` — emitted a bare `+234`. `parsePhone` then read those dial
digits back as the national part, and the next keystroke produced `+234234…`,
doubling the dial code and growing with every character. Fixed by stripping
first, plus `parsePhone` treating a bare dial code as an empty national part.
Pinned by a character-by-character type-in test.

## Implementation Notes

- **One file per component**, not one giant `components.tsx` — this is the one place mockup-monolith structure should *not* be carried forward, since these will be imported individually across ~150 pages.
- Every component gets a colocated `.test.tsx` (render + key prop variants) — see [12_testing_strategy.md](12_testing_strategy.md).
- `Table`, `Field`, and `Banner` are the highest-leverage components (used on nearly every page) — build and review these first, before starting Task 07 pages, since any contract change later means touching dozens of call sites.
- Do not let any page reach into `--color-*` CSS variables directly for one-off styling. If a page needs something a token doesn't cover, that's a signal to either add a token (Task 02) or it's a genuine one-off (rare, keep it scoped to that page's CSS Module, never inline).

## Acceptance Criteria

- [x] All components listed above exist, each with its own file + test. Primitives and brand marks live under `src/design/components/`; the App Shell components (`Sidebar`, `TopBar`, `PageShell`, `PageHeader`, `SectionHead`, `Tabs`) live under `src/shell/` instead, per the repo structure already established in `01_project_setup.md` (that's also where `ImpersonationBanner`/`routes.tsx` land in later tasks) — keeping the shell concern in one directory rather than splitting it.
- [x] `Table` supports: sortable columns, row selection, dense mode, loading skeleton, custom empty state
- [x] `Field` integrates with react-hook-form without a wrapper-around-a-wrapper (direct `register()` spread support)
- [x] `Button` variant=`accent` has a dev-mode console warning if rendered more than once per page (enforces the one-CTA design rule)
- [x] A Storybook (or equivalent catalog route) renders every component with every variant/prop combination for design QA — `src/design/ComponentCatalog.tsx`, mounted dev-only at `/component-catalog` in `App.tsx`
- [x] No page-level code hardcodes a colour a token already covers — **done (2026-07-10)**: `frontend-ci.yml` has a "no token-duplicating hex colours in pages" guard (fails on any brand/status token hex literal in `src/pages`, excluding SVG illustration attrs + the fixed-colour print pages). One real violation fixed (`#7c3aed` → `var(--color-role-platform)` in TenantReports). One-off layout inline styles remain acceptable per this doc's guidance.

**Addendum (Task 07, 7.1):** four more small atoms — `Kvp`, `UserCell`, `ViewLink`, `KebabBtn` — were added to `src/design/components/` once 7.1 needed them. They weren't in this task's original inventory because they were never in `shared/components.jsx` either; each domain mockup (`platform-screens.jsx`, `reports-screens.jsx`, `china-screens.jsx`) had quietly redefined its own copy. Promoted to shared components (file + test each, exported from `src/design/components/index.ts`) rather than re-duplicated a fourth time, since every remaining 7.x domain needs the same row patterns.

**Addendum (2026-07-09) — Responsive foundation (prototype update of 2026-07-08):** the design prototype's `shared/components.jsx`/`app-shell.jsx` gained a container-query-based responsive layer, now mirrored in the implementation:

- `PageShell` (`src/shell/PageShell.tsx/.module.css`) is a CSS container (`container-name: sxapp`, `container-type: inline-size`) — every responsive rule in the shell keys off the app frame's width, not the viewport, matching the prototype's `.sx-appframe`. Breakpoints: **1080 / 860 / 560 px** (staff), **920 / 560 px** (auth).
- **Mobile drawer:** under 860px the docked sidebar hides and `TopBar` shows a hamburger (new `menu` icon) that opens the same `Sidebar` element in a fixed overlay drawer. Plumbed via `useShellDrawer()` context exported from `PageShell.tsx`; drawer closes on Escape, overlay click, or content click.
- **TopBar:** search shrinks to 200px ≤1080px and hides ≤860px; user-chip meta text hides ≤860px.
- ~~**Table:** wrapper scrolls horizontally; ≤860px the table gets `min-width: 720px` and a sticky first column~~ — **superseded 2026-09-20**: see the addendum below. `Table` now renders a real card-list below 860px instead of a horizontally-scrolling table with a sticky column.
- **PageHeader** stacks title over actions ≤560px. **Auth** brand panel hides <920px (corrected from 860).
- **Micro-interactions** (prototype `.sx-*` hover styles): Button hover-lift/press, sidebar-nav hover, tab hover, chip hover-lift, icon-button hover-scale. Table-row hover tint already existed.
- Prop surface widened while fixing the (previously silent) `tsc -b` debt: `Card`/`Mono` accept `style`, `Button` accepts all native button attributes + `className`, `ExportButton` is generic over its offered formats (`formats={['xlsx','csv']}` narrows the callback type).

**Addendum (2026-09-20) — App-wide responsive pass:** a full audit found responsive
coverage very uneven outside the shell/table basics above (22 nigeria-domain
page stylesheets had zero responsive CSS at all, the customer-portal shell had
no mobile nav, the documented `Table` card-list fallback was never built, and
~16 hand-rolled modals + several fixed-column stat grids overflowed or clipped
below ~480–860px). Fixed comprehensively rather than patched piecemeal, per
user direction to prioritize UX quality over speed (pre-launch, "nothing to
rush"). Breakpoint convention (860px) is now written down in
[02_design_tokens_and_theming.md](02_design_tokens_and_theming.md).

- **`Table` real mobile card-list (the previously-only-documented fallback,
  now built):** `Table.tsx` measures its own wrapper via a `ResizeObserver`
  (`useIsNarrow` hook, default `false`/table-view unless a genuinely nonzero
  width ≤860px is measured — jsdom always reports 0, so unit tests keep
  rendering the table markup unchanged) and renders one of two **structurally
  different** DOM trees, not the same markup restyled. This is a different
  mechanism than every other responsive rule in the app (which are pure CSS
  `@container` queries) — chosen deliberately because a card list needs a
  different DOM shape, not just different styling, and two simultaneously-
  rendered markups would make `getByText()` ambiguous across all 29 pages
  that assert on table row text. Convention (zero prop changes needed at any
  of the 29 existing `<Table>` call sites): column 0 → card header; a
  trailing column with `title === ''` → the card's action row; every other
  column → a label:value pair in a 2-column grid. New optional escape hatch:
  `TableColumn.hideInCard?: boolean`. Known accepted limitation: `sortable`/
  `onSort` has no card-view affordance (no column header row exists in card
  view) — data keeps whatever order the page already applies.
- **Customer-portal mobile drawer:** `useShellDrawer`/`ShellDrawerContext`
  (open/toggle/close + Escape-to-close) extracted from `PageShell.tsx` into a
  new shared `src/shell/ShellDrawer.tsx` so both `PageShell` (staff) and the
  previously-drawer-less `CustShell` (customer) can each provide their own
  instance to their own hamburger. `CustomerTopNav` gained a hamburger button
  (hidden ≥860px) and a slide-in drawer panel reusing the same nav-link data
  it already renders horizontally.
- **Canonical mobile-first modal pattern**, applied to ~18 hand-rolled modals
  across nigeria/china/tenant-admin/platform/customer (3 different local
  class-naming conventions, so this could not be one global selector — each
  file's own `.modalOverlay`/`.modalPanel` or `.overlay`/`.panel` or
  `.modalOverlay`/`.modal` pair was converted individually), reference
  implementation `warehouse/WarehouseDashboard.module.css`'s pickup sheet:
  bottom-sheet mobile default (`align-items: flex-end`, `width: 100%`,
  `border-radius` on top corners only), upgraded to a centered dialog only
  inside `@container sxapp (min-width: 861px)`; `max-height: 90vh;
  overflow-y: auto` on the panel so tall content scrolls internally; action
  buttons `min-height: 48px` (44×44px touch target rule) on mobile, `36px`
  on desktop. Several of these were genuine overflow bugs, not just
  unoptimized — `tenant-admin/PaymentGatewayConfig.module.css`,
  `WebhookConfig.module.css`, `china/PackingListList.module.css`,
  `PackingListDetail.module.css`, `ContainerDetail.module.css` all had a
  literal fixed `width: 480px` (not `max-width`) on the modal panel, wider
  than any phone viewport. Four more hand-rolled inline-styled modals with no
  CSS module at all (`design/components/LimitReachedModal.tsx`,
  `customer/MyBillingDetail.tsx`'s dispute modal, `nigeria/CarryoverLedger.tsx`,
  `tenant-admin/ChargeTypes.tsx`) got the same `maxHeight`/`overflowY` safety
  and `size="lg"` (44px) buttons applied inline instead, since they have no
  module to add a `@container` rule to.
- **`Field` inputs**: added `font-size: 16px` under `@container sxapp
  (max-width: 860px)` — below 16px, iOS Safari auto-zooms on focus. Scoped to
  mobile only so desktop density is unchanged.
- **Fixed-column stat/summary grids → reflowing grids**: standardized every
  `grid-template-columns: repeat(N, 1fr)` stat row onto the pattern already
  used correctly elsewhere in the app, `repeat(auto-fit, minmax(150px,
  1fr))`, across ~15 files. Also converted a handful of **inline**
  `style={{ gridTemplateColumns: '1fr 1fr' }}` occurrences to the same
  pattern (`customer/Account.tsx` ×3, `tenant-admin/ActivityLog.tsx`,
  `platform/CreateTenantPage.tsx` ×2) — inline styles can't be targeted by a
  CSS-module `@container` rule at all, so these stayed rigid 2-column no
  matter how narrow the shell got until moved into a class or given an
  `auto-fit` value directly.
- **Hero/toolbar rows missing `flex-wrap`**: `nigeria/BillingDetail.module.css`
  `.hero` and `nigeria/ClaimDetail.module.css` `.hero` (title + up to 4 action
  buttons side by side, no wrap), `china/PackingListList.module.css`
  `.bulkBar`/`.bulkActions` (bulk-selection toolbar: a label plus up to 3
  buttons), and `china/CreatePackingList.module.css` /
  `ImportPackingLists.module.css` `.actionsRow`/`.actionsRowFull` (multi-step
  form footers with up to 3 buttons) all got `flex-wrap: wrap` added — real
  overflow risk at 375px, live-verified via Playwright (see
  `17_testing.md`).
- Live-browser verification only (jsdom has no layout engine and never
  evaluates `@container`/`@media`) caught two overflow bugs unit tests could
  not: `BillingList`'s stats grid and `TopBar`'s action-button row both
  overflowed at 375px even after the `Table` card-view landed, traced via a
  DOM `scrollWidth` scan in `e2e/flows/responsive_smoke.spec.ts`.

## Modal focus management (audit FE-04, 2026-11-16)

`design/components/Modal.tsx`: `ModalOverlay` (which `Modal` renders, and which any custom dialog can use) now owns the dialog behaviour. **Focus in:** when it opens, focus goes to the first control the user is likely to want (a form field, then an action button), not the Close button that comes first in the markup; Close is the fallback, then the overlay itself so Tab cannot start behind it. A field with `autoFocus` keeps focus. Controls that are disabled, `hidden` or `inert` are skipped. **Trap:** Tab and Shift+Tab wrap inside the dialog; if focus has wandered behind it, Tab pulls it back in. **Restore:** closing returns focus to the control that opened it (read at first render, before an `autoFocus` field can take focus), unless that control has left the page. **Scroll lock:** the body's `overflow` is hidden while any dialog is open, with padding for the scrollbar's width so the page does not shift, and restored by the last dialog to close. **Label:** `Modal` is named by its own heading (`aria-labelledby`), not a separate `aria-label` that can drift. **Stacked dialogs** keep a stack: only the innermost traps Tab, and one Escape closes one dialog (before, a confirmation over a form closed both).

**Ground-truth gap found while doing it: the brief's premise was wrong.** It says "every confirm, payment and pickup flow uses this component". Only 5 files use `Modal`; **34 dialogs in 21 files are hand-rolled** (their own overlay and panel markup), including the staff payment, pickup, refund, release-note and claim flows. Fixing `Modal` alone would have left all of them with no focus handling, no Escape key and no accessible name. So the behaviour lives in one hook (`useDialogBehavior`) used two ways: `Modal`/`ModalOverlay`, and **`<DialogGuard onClose={...} />`**, which goes as the first child of a hand-rolled dialog's own overlay element and applies the same behaviour to its parent (it renders one hidden `<span>`). A dialog with no `aria-label`/`aria-labelledby` is named from its first heading. All 34 now carry a guard (markup otherwise unchanged). `shell/dialogs.test.ts` fails for any file that declares an `aria-modal` dialog without a `<DialogGuard>` per dialog (mutation-checked), so a new hand-rolled dialog cannot skip this; new dialogs should use `Modal`. Side effect: these dialogs gain Escape, which they never had. Not covered: popovers (the notification panels, the list Filters panels) are not modal and are left alone.

Known limit: focus is placed once, when the dialog mounts. A dialog whose first control appears after data loads (the Generate billing container picker) opens with focus on its first button (Cancel) and the field is one Tab away. Tests: `Modal.test.tsx` (32), mutation-checked; also checked in a real browser, for `Modal` (Generate billing) and a hand-rolled dialog (staff Record payment: opens on the amount field, named "Record payment", 60 Tab/Shift+Tab presses never left it, Escape returned focus to the button).

## Status registry, `StatusBadge` and `RoleBadge` (FD-08, 2026-11-19)

**Problem:** 37 status-to-colour maps in 28 files. A sealed container was blue on the dashboard and amber on the container list; `at_warehouse` read "Ready", "At warehouse", "At Warehouse" and "Ready for pickup"; `released_with_outstanding` three ways; the release note page printed `unpaid`; the Admin role badge was the error red; every warehouse card said "Normal" in amber.

**Now:**
- `src/design/status.ts` — `STATUS_REGISTRY`: 18 kinds (`container`, `invoice`, `packingList`, `claim`, `dispute`, `manifest`, `missingItem`, `seizedItem`, `refund`, `releaseNote`, `carryover`, `paymentClaim`, `notification`, `tenant`, `onboardingRequest`, `offboardingExport`, `announcement`, `staffUser`), each status → `{ label, customer?, variant }`, typed `satisfies Record<ApiUnion, StatusEntry>` so a new API status fails the type check. Helpers: `statusLabel(kind, status, audience?)`, `statusVariant`, `statusColor` (CSS value, for the pipeline's stage accents), `statusesOf` (chip and select order), `roleLabel`, `roleColor`. An unknown status shows in words ("Held at port"), never as a code.
- Colour rule: neutral = not started / done with nothing to do; info = moving, nobody needs to act; warning = waiting on someone; success = done; error = refused, failed, lost; primary = a container cleared and in Nigeria.
- `StatusBadge kind status audience?` and `RoleBadge role` (neutral badge, role colour as the dot) in `design/components`.
- Customer words where they differ: container (`Being packed`, `Packed`, `In customs`, `Cleared customs`, `Completed`), refund (`Being reviewed`, `Paid`, `Credit on your account`, `Not approved`), release note (`Ready to collect`), payment claim (`Being checked`, `Not accepted`).
- Wording changes staff will see: `Partially paid`/`Partial` → **Partly paid**; `Released (outstanding)`/`Released` → **Released, balance owed**; `In Transit`/`Arrived (NG)`/`Customs Clearance`/`At Warehouse`/`Fully Released` → sentence case, **Arrived in Nigeria**; refund `Processed` → **Paid out**; `Found & shipping` → **Found, shipping**; dispute `Resolved — adjusted` → **Resolved: adjusted**; roles **Admin / China office / Nigeria office / Warehouse / Customer**. Colour changes: dispute `escalated_china` warning (was error), manifest `resolved` success (was neutral), claim `under_inspection`/`inspection_complete` info, refund `approved` info, invoice `overpaid` info.
- Migrated: 41 files (every page map and label function deleted, plus `CONTAINER_STATUS_LABELS`, `CUSTOMER_CLAIM_STATUS_LABELS`, `releaseNoteStatusLabel`, `billingDetail/status.ts` helpers, `containerDetail/labels.ts` badge maps). The header search shows result statuses in registry words. The warehouse queue shows urgency only when Urgent or New. Print pages show registry words.
- Guard: `src/design/statusRegistry.test.ts` — every API status union (16) equals its registry kind; every label is sentence case without `_`; no page or shell file declares a status map, a `statusLabel`-style function, or picks a badge colour with `status ===`.
- Catalog: "Statuses (FD-08)" section shows every kind and every role.
- Kept on purpose: `customerRefundLabel` (a sentence for the claim page's refund line), `MyShipmentDetail`'s per-status hints (prose), `customer.ts` stage labels (public tracking stages, not a record status).

## Buttons: five variants, one exception, and no raw `<button>` (FD-07, 2026-11-19)

**Problem:** pages used `Button` ~330 times and raw `<button>` 42 times; the invoice list showed a text link, a copper accent button and an outlined button in one column, with accent on every unpaid row; the warehouse's main action used `success`, a second green; "Cancel container" was a green ghost; small buttons were 28 px; `Action` (read-only guard) wrapped only 27 mutating buttons.

**Now:**
- `ButtonVariant` = `primary | secondary | ghost | danger | danger-ghost | accent`. `success` is gone (→ primary), `danger-outline` became **`danger-ghost`** (transparent, red text, soft red hover). Accent is for paying and signing in only — auth screens, the session-timeout prompt, the customer invoice's "Pay online" and the shipment's "Pay outstanding". The dev-only "more than one accent" console warning is replaced by a test.
- Heights **32 / 40 / 48 px** (sm/md/lg); under `(pointer: coarse)` sm and md are at least 44 px. Default `type="button"`.
- **Read-only by default:** `Button` reads the session itself; with `session.readOnly` a button with `mutates` (default true for primary, accent, danger, danger-ghost) renders disabled, dashed, with a suspend icon and the title "Disabled during read-only impersonation". `mutates={false}` for a primary that only opens something; `mutates` for a secondary that changes data. `Action` is now `<Button mutates>` (kept for existing call sites); its dashed-pill `<span>` and CSS are gone. No session (login, catalog) → nothing blocked.
- New **`IconButton`** (`icon`, required `label` → aria-label and title, variants ghost/secondary/danger-ghost, square 32/40/48) and **`Pressable`** (unstyled `type="button"` with the focus ring, for tiles, option rows, pipeline stages, queue rows).
- Raw buttons in pages: 0 (was 42). Navigation became router `Link`s (auth footers, "Forgot password?", work-queue rows, carryover source, claim sub-links, audit-log link, "View full invoice"); password toggles, modal close and remove-row buttons became `IconButton`s; "Clear all filters", "Remove" and "View all" became ghost `Button`s; selectable tiles and options became `Pressable`. Found on the way: `CompanySettings`'s preview tabs had no `type` (a bare button inside a form submits it). `MyShipmentDetail`'s leftover "← My shipments" back link was removed (FD-47).
- Row pattern: invoice and claim rows carry one small **secondary** button (was accent / primary / ghost), marked `mutates={false}` because it only opens the record.
- Side by side: "Offboard" beside "Lift suspension" is now danger-ghost, not a second filled colour. Typed arrows in labels ("View all →", "Sign in →", "Review all →") became `trailingIcon="arrowright"` / a trailing icon in links.
- Guards: `src/design/buttonRules.test.ts` (no raw `<button>` in pages, accent allowlist, no typed arrow before `</Button|Link|Pressable|a>`); `Action.test.tsx` covers read-only on plain Buttons and IconButtons; `Button.test.tsx` covers `type="button"` and trailing icons; `IconButton.test.tsx` covers label and Pressable.
- Catalog: "Buttons (FD-07)" lists the rules and shows every variant, size, icon and state.
- ~~Not in this item: the table row pattern beyond these two lists is FD-13.~~ Done in FD-13 (below): rows open from their first cell; the invoice and claim rows keep their one next-step button.

## The Field family, and a name on every control (FD-11, FD-50, 2026-11-19)

**Problem:** 80 raw `<input>`/`<select>`/`<textarea>` in pages, each with its own height, border and focus; 12 native date inputs; filter bars with an "All time" preset *and* separate From/To inputs; brand colour as a plain text box; required fields with an asterisk *and* optional ones tagged at the same time; disabled pickers reading "No open containers available" with no way forward. 68 controls named only by placeholder; switches with no name because `ToggleSwitch`'s label was optional.

**Now:**
- `FieldShell` (shared): always a `<label>` (`hideLabel` keeps it for screen readers), the "Optional" tag (read as the description, not part of the name), error/helper wired with `aria-describedby`, `aria-invalid`. **No required asterisk anywhere**: forms mark optional fields only (23 asterisks removed, incl. `CountrySelect`, `StateSelect`, `PhoneField`).
- Components: `Field` (`label` now required), `Select` (options or children, `placeholder`, `empty={{ message, action: { label, to } }}`), `DateField` (Field chrome + calendar icon, the date repeated in words under it), `ColorField` (swatch picker + hex code, accepts a code once whole), `SearchField` (labelled search box with clear button, 40 px), `CellInput` / `CellSelect` / `CellCheckbox` / `CellRadio` (compact, required `label` naming the row: "Actual weight (kg), item 3"), `RadioGroup` (`list` or `cards`), `CheckboxField`, `FileInput` (visually hidden, named, behind an upload Button). `ToggleSwitch`'s `label` is required.
- `DateRangeFilter` takes `range` (the `useDateRangeFilter` state) and a `label`; presets and a custom From–To live in one popover; the button reads what applies ("Last 30 days", "Since 12 Nov 2026", "12 Nov – 19 Nov 2026"). The six list pages (containers, invoices, claims, notification log, reports, activity log) lost their separate From/To inputs; `ActivityLog` now uses the shared hook instead of its own copy.
- Migrated: every raw control in pages (0 left): 9 list search boxes → `SearchField`; 21 selects → `Select` (1 → `CellSelect`); 14 packing-list cell inputs → `CellInput`; rate inputs (CBM, dollar markup) and the template body → `Field`; refund preference, debt check, message language → `RadioGroup`; primary role → `CellRadio`; "release with outstanding" → `CheckboxField`; 3 file pickers → `FileInput` (the document dialog now shows "Choose file" and the chosen name); 5 form dates → `DateField`; brand colour → `ColorField`; the warehouse scan box → `Field` (kept large and monospaced).
- Empty pickers on the packing-list form say why and what to do: no loading container → "Create a container" link; no warehouse → "Ask your admin to add a warehouse"; no customers → ask the Nigeria office or admin.
- Guards: `src/design/formRules.test.ts` (no raw control in pages, no separate date inputs in filter bars, no asterisk); `FieldFamily.test.tsx` (13). The phone audit (`scripts/mobile-audit.mjs`) now also fails a page with any unnamed button, link, input, select, switch, checkbox, radio, combobox or tab.
- Catalog: "Field family (FD-11, FD-50)" shows every control and state. The catalog now renders inside a router.
- `Check` (the custom tri-state box) takes a required `label`; table selection boxes read "Select all rows" / "Select row N". Found by the new audit: on login, registration, the customer consent filter and the warehouse form, `Check` sat inside a `<label>` with text, which named nothing and — a span, not a form control — did not toggle when the text was clicked. Those are native `CheckboxField`s now. The platform tenant search had `label=""`; it is a `SearchField`.
- Found on the way: the reports page's "Export" button has no handler (not fixed here).

## Dialogs: named widths, quieter titles, and no lost input (FD-12, 2026-11-19)

- **Unsaved input:** `useDialogBehavior` (shared by `Modal`/`ModalOverlay` and `DialogGuard`) marks a dialog dirty on any `input` event inside it. Then Escape or a backdrop click shows "Discard your changes?" (Keep editing / Discard changes) instead of closing; the dialog's own Cancel/Close buttons still close at once. For hand-rolled dialogs, `DialogGuard` catches the backdrop click in a native listener on the overlay, before the page's React `onClick` runs, and renders the prompt into the overlay. Escape while the prompt is up means Keep editing.
- **Widths:** `Modal` takes `size` = `sm` 480 · `md` 560 (default) · `lg` 720 · `xl` 960 (was a free `width` number; 7 callers moved). Tokens `--dialog-sm|md|lg|xl` in `tokens.css`; hand-rolled dialog panels use them (440/480 → sm, 560 → md, 640 → lg).
- **Titles** 16 px semibold (`--text-lg`, 600) in `Modal` and every hand-rolled `modalTitle`/`panelTitle`/`dialogTitle` (were 20–24 px bold).
- **Footer order** Cancel, then the commit button on the right: fixed in the announcement edit/reject/delete rows and the payment-claim reject row (they had the commit first). Commit labels name the object: "Upload document", "Generate release note". The results screen's "Done" is `mutates={false}`.
- Test: `ModalDiscard.test.tsx` (6) types into a Modal and into a hand-rolled dialog, clicks the backdrop, and the input is still there; Escape asks too; Discard closes; Cancel and an untouched backdrop click close at once. Mutation-checked.
- Catalog: "Modal (FD-12)" lists the rules and demonstrates the prompt.

## Toasts: one way to say an action worked (FD-21, 2026-11-19)

**Problem:** no toast. Each page confirmed a save its own way (an inline banner, a redirect, or nothing): 14 pages kept a `saved`/`success`/`notice` flag and a "Saved." banner, and most mutations showed nothing at all.

**Now:**
- `src/design/toast.ts`: a module-level store, `toast.success|info|error(title, body?)`, so a handler calls it without a hook; 4 s auto-dismiss, at most 3 shown. `ToastRegion` (mounted once in `App` for both auth providers, and in the catalog) renders them top right on desktop and along the bottom below 600 px, in a polite `role="status"` live region, each with a Dismiss button.
- `queryClient` has a `MutationCache` whose `onSuccess` shows `mutation.meta.successToast` (string, `{title, body}` or a function of the response); `meta` is typed via `Register`. The billing, manifest, staff, container and claim mutation hooks declare it (no page uses those hooks yet; pages call the API directly).
- Converted: the transient banners and their state on payment gateway (bank details, Paystack key), dollar rate, CBM rate, webhook, company settings, notification templates, platform settings, plan override, staff profile, staff user actions, warehouses, customer account (contact details, preferences), and the release note's "New pickup code sent".
- Added at 65 call sites: every page that changes data now toasts on success, naming the record where it has one ("Payment recorded · ACM-INV-…", "Container moved to In transit · MSCU1234567", "Packing list approved · PL-…", "3 packing lists approved"). Pages that show a full result screen or panel instead are listed in the guard with their reason (auth flows, invoice-generation outcome, import results, webhook secret/test, impersonation, erasure).
- Kept as banners (lasting state): "This dispute is resolved", "Consent on file", "Pickup recorded" on the note, the invoice outcome, the packing-list validity summary.
- Tests: `ToastRegion.test.tsx` (4: shown and announced, gone after 4 s, dismiss, cap of 3); `src/design/toastRules.test.ts` (no page keeps saved/success state; every page with a write API call also calls `toast`, unless it is a listed result screen). The test setup mounts a `ToastRegion` for every test, so page tests assert the toast text a user sees; 6 page tests now assert the toast wording.

## Empty, loading and error states (FD-20, 2026-11-19)

**Problem:** 38 tables with a grey sentence and no next step, ~55 plain "Loading…" texts, and errors showing the API's own text ("Insufficient permissions for this operation. Required role: platform_admin").

**Now:**
- **Plain error words, centrally:** `ApiError.message` is now `plainErrorMessage(status, detail, errorCode)`: 403 → "You don't have permission to do this. Ask your admin if you need it.", 404 → "We couldn't find that…", 429 → wait and retry, 0/502/503/504 → "We couldn't reach the server…", other 5xx → "Something went wrong on our side…". 400/409/422 and `EXTERNAL_SERVICE_ERROR` (a payment provider's refusal) keep the server's words, which are written for users. The raw text is on `ApiError.detail`. Every existing `err.message` display became plain at once.
- `PageSkeleton kind="detail|list|form" label`, `LinesSkeleton label lines`, `Skeleton` — shaped like the page they become, `role="status"` + `aria-busy`, shapes `aria-hidden`, shimmer off under reduced motion. 35 whole-page and inline "Loading…" texts replaced, plus the auth screens, notification panels, activity feed and work queue.
- `EmptyState title body icon action onClearFilters compact` (first-use form with a next step, no-results form with "Clear filters"). Every table `emptyState` (≈40) uses it; tables that showed "Loading x…" in the empty slot now show a skeleton while loading.
- `ErrorState title error message onRetry compact`: plain message, "Try again", "Reference: <request id>". Used by the seven record pages (invoice, claim, refund, release note, manifest, packing list, container) with `refetch`, and the ten list pages' load errors (compact, with `refetch`).
- **Layout shift:** `scripts/layout-shift.mjs` measures CLS on six sampled pages with real data (fails above 0.1). The invoice list was 0.276: chip counts arrive after first paint and the wrapping row moved the search box; list filter rows now put the chips on their own line. All sampled pages measure 0.059–0.084; the remaining 0.06 on every page is the "Users limit reached" quota banner arriving after its fetch (a real alert, left as is).
- Tests: `States.test.tsx` (5), `src/design/stateRules.test.ts` (no bare "Loading…", no plain-text table empty state); 21 page tests updated to plain error words or titles without a full stop.

## Tables: column types, rows that open, one count (FD-13, 2026-11-20)

**Problem:** 13 list pages had a "View" link in a column of its own and 7 more (dashboard summaries, pipeline, invoice and claim fallbacks, notification log) a ghost "View" button; others opened with a kebab or not at all (dashboard pending packing lists and disputes). Numbers, money and IDs were aligned and set differently table to table. Some money columns had no currency. Lists counted twice ("Showing 50 packing lists" above, "Showing 50 of 68" below). The payments table led with the amount and showed `bank_transfer`. Three hand-built `<table>`s (customer payment history, both import "Skipped rows").

**Now:**
- `TableColumn.type`: `text` (default), `reference` (monospaced IDs), `number` and `money` (right-aligned, tabular figures), `date`, `status`, `action` (right-aligned; the card footer on phones). The unit goes in the title: "Total (₦)", "Volume (CBM)", "Rate (${prefix})". Set on every column in 39 pages. The codemod's wrong guesses were fixed by hand: the reports page's Billed/Collected (money, not dates), MiscCharges' "Charge" (text), storage fees' "Day" (text).
- `TableRow.onOpen` + `openLabel`: cell 0 is wrapped in a `<button>` (focus ring, `openLabel` as its name when given), and a click anywhere on the row or card opens it unless it lands on a control inside the row. `ViewLink` is deleted. Converted: every list, the dashboard's six summary tables, the pipeline, the container list (its kebab), the notification log (opens the detail drawer), invoice and claim lists (their "View" fallback is gone; "Record payment", "Release", "Start inspection", "Complete" and "Resolve" stay as the row's one next step, all `mutates={false}`).
- Card view switches at **600px** (was 860px), so tablets keep the table.
- **One count:** `ListFooter` is the list's only count. It says "of {total}" only when the total is larger than the rows shown, and takes `nounOne` for one row ("Showing 1 packing list", not "1 of 1 packing lists"); all 16 callers pass it. `PackingListList`'s count above the table is gone, and its footer says "in this status" when a status chip is on.
- Container list: ETA stays a date after clearance (it showed the word "Cleared", which the Status column already says); "Utilization (%)" became "Packed (CBM)", since packed CBM is the figure and the percentage sits on the bar.
- Payments: one `PaymentsTable` for staff and customer invoices, columns Confirmed · Reference · Method · Amount (₦); methods read "Bank transfer" via `lib/paymentMethods.ts` (`PAYMENT_METHODS`, `paymentMethodLabel`), also used by the record-payment dialog.
- Import "Skipped rows" is one `SkippedRowsTable` on `Table`.
- Guards: `src/design/tableRules.test.ts` (no "View" button or `ViewLink`; every money column names its currency; no hand-built `<table>` outside print pages and the packing-list item grid; no second count beside `ListFooter`). `Table.test.tsx` gained 6 (open button, row click opens once, a row's own action does not open it, cards open, money right-aligned, 600px switch).

## Cards: one frame, numbers in stat cards, words kept whole (FD-10, 2026-11-20)

**Problem:** every table inside a `Card padding="none"` drew its own border 1 px inside the card's (two frames); the release note and refund showed words in stat cards ("Partial release", "Unpaid", "Bank account refund"); stat labels were clamped to two lines and sublabels cut with an ellipsis; `overflow-wrap: anywhere` in Kvp, Badge, table cards and toasts split ordinary words ("OUTSTAN / DING") because it also shrinks an element's minimum width; dashboard cards side by side had different heights.

**Now:**
- `Card` renders `data-surface="card"`; `Table`'s wrapper drops its border and radius inside one. A table outside a card keeps its frame.
- `StatCard` is for one figure. Its body is a size container: the value is `clamp(lg, 16cqi, 2xl)` and wraps only between words; the label wraps between words with no clamp; the sublabel wraps; the icon hides when the card is under 180 px. Release note "Type" and "Payment status" moved to its details list (status as a badge); the refund's "Payout method" card was removed (the details list already says "Customer preference").
- `overflow-wrap: break-word` (breaks only a word wider than its whole line) replaces `anywhere` and `word-break: break-word` in Kvp, Badge, Table card values, toasts, and the notification message previews. The gateway response in the notification log keeps `break-all` (one long token).
- Badges wrap between words at every width, so a table's status column can narrow and the table fits the page (the invoice list scrolled sideways by 64 px at 1280 px because of "Released, balance owed").
- Dashboard grids (`dashCols`, `dashGrid2`, platform `dashCols`) stretch, so cards side by side share one height.
- Text that was cut off now wraps: the claim list's description, the warehouse queue's customer name.
- The invoice list's own "Showing N records" above the table was removed (FD-13's one count; the guard now also catches `Showing <strong>`).
- Guards: `src/design/cardRules.test.ts` (no `*Label(…)` as a stat value; no `anywhere`/`break-all`/`break-word` outside the allowlist; no clamp or ellipsis in StatCard; the table-in-card rule exists). `scripts/text-breaks.mjs` checks every route at 375 and 1280 px for split words, cut-off text, double frames and, at desktop width, tables that scroll sideways.

## Stepper: one progress row (FD-09, 2026-11-20)

**Problem:** seven hand-drawn steppers (container pipeline, customer tracker, staff and customer claim progress, refund approval, the packing-list form and the import wizard), each with its own dots, lines and labels. The container pipeline's upcoming steps were faint grey; the customer tracker ran off a phone's edge inside a sideways scroll strip; step names were copies that disagreed with the status badges ("Received", "Ready", "Delivered").

**Now:**
- `Stepper` (`steps: { key, label, sub?, tone? }[]`, `current`, `mode: 'progress' | 'wizard'`, `failed`, `complete`, `label`, `compactBelow` = 600): an ordered list named by `label`, `aria-current="step"` on the current step, and each step's state ("done", "current step", "stopped here", "not started") in screen-reader text. Upcoming steps keep a visible ring and second-ink label. Wizard mode numbers the dots and adds "Step n". `failed` marks the current step with a cross in the error colour (a rejected refund).
- At or below 600 px of its own width (`useIsNarrow`, now shared with `Table` in `src/design/useIsNarrow.ts`) it shows the current step, "3 of 8", its second line and a bar (`role="progressbar"` with a text value). No sideways scroll.
- `src/design/steps.ts`: `containerSteps(audience)` / `containerProgress(status)` and `claimSteps(audience)` / `claimProgress(status)` name the steps from the status registry (staff or customer wording), so a stepper and a badge always agree. Tone: the first three container steps are China-side (info blue).
- Used by `ContainerStepper` (overview and tracking tabs), `CustomerStepper` (shipment list and detail), claim detail (staff and customer), refund detail, the packing-list form and the import wizard. The container event log names events from the registry too. About 300 lines of per-page stepper CSS deleted.
- Tests: `Stepper.test.tsx` (6: named list and states, complete, failed, wizard numbers, compact form at 390 px with "2 of 4" and the progress bar, full form above 600 px); `src/design/stepperRules.test.ts` (no page CSS draws step dots or lines; the seven pages use `Stepper`). Checked in the browser: the customer tracker at 390 px fits ("Completed · 8 of 8"), the page does not scroll sideways.

## Component catalog: every component, light and dark (step 2 gate, 2026-11-20)

`/component-catalog` (dev only) now has a theme switch (`ThemeToggle`) at the top and renders every component `src/design/components/index.ts` exports: new sections for cards and stat cards (FD-10), the key-value list, tables (FD-13: column types, rows that open, the footer count, phone cards, loading, empty, selectable), the Stepper (FD-09: in progress, complete, refused, wizard, compact at phone width), empty/loading/error states (FD-20, the three page skeletons), and the remaining controls (Combobox, country/state/phone, date range, export, file input behind its button, language, kebab, Pressable, Action, quick action, user cell, icons, the plan-limit dialog, `ModalOverlay` + `DialogGuard`, cell checkbox and radio).

Rendered in both themes with no console errors. Reviewing it found and fixed:
- dark mode's active chip was deep green on the soft green fill (unreadable): it uses `--color-primary-on-soft`;
- `Pressable` showed the browser's grey button fill in dark mode: a zero-specificity `:where(.pressable)` reset (no background, border or padding), so page classes still win;
- a table in card view inside a `Card` drew a bordered card per row inside the card's frame (every list page on a phone): inside a card the rows are divided by lines, not boxed, and the wrapper takes the card's radius so its rows and header clip to the rounded corners.

- a phone card's fields sat two to a row even at 320 px, where a status ("COMPLETED") is wider than its cell; before FD-10 `anywhere` split the word, now the fields drop to one column (`repeat(auto-fit, minmax(min(100%, 136px), 1fr))`).

Guard: `src/design/catalogCoverage.test.ts` fails when an exported component is missing from the catalog or the theme switch is gone.

