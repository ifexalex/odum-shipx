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
| `Table` | `columns: { title: string; width?: string; align?: 'left'\|'right'\|'center'; sortable?: boolean; hideInCard?: boolean }[]; rows: { cells: ReactNode[]; selected?: boolean }[]; selectable?: boolean; dense?: boolean; loading?: boolean; emptyState?: ReactNode; onSort?; cardBreakpoint?: number` | Drives every list page in Task 07. Build the loading skeleton (5 gray rows matching column widths) and the empty-state slot into this component once, not per page. Below `cardBreakpoint` (default 860px, measured via `ResizeObserver` on its own wrapper), renders a card-list instead of scrolling the table horizontally — see the 2026-09-20 addendum below. Pass a smaller `cardBreakpoint` (e.g. 600) for a compact, few-column table embedded in a narrow desktop column (the dashboard's summary tables sit in a ~776px column; the 860px default would card-ify them on a 1440px screen, inconsistent with every full-width list). |
| `Check` | `checked?: boolean; partial?: boolean; onChange` | Checkbox primitive, supports tri-state for "select all" headers. |
| `Mono` | `children; color?` | Monospace span — **always** wrap tracking codes, container numbers, and monetary amounts in this (design rule from Task 02). |
| `Avatar` | `name?: string; src?: string; size?: number; roleColor?: keyof typeof roleColors` | Circular initials-or-image, role-tinted border/background. |
| `Banner` | `variant: 'info'\|'success'\|'warning'\|'error'; title?; icon?: IconName; action?: ReactNode; dismissible?: boolean` | Inline alert box — used heavily for read-only impersonation state (Task 08), storage-fee grace-period warnings, GDPR notices. |
| `Chip` | `label; active?: boolean; count?: number; dismissible?: boolean; onDismiss?` | Filter pill. |
| `Modal` / `ModalOverlay` | `open; onClose; title?; width?; children; footer?: ReactNode` | Full-screen on mobile (see Task 02 spacing rules), centered with `--shadow-modal` + `--scrim-modal` backdrop on desktop. **Most hand-rolled per-page modals do not use this component** — see the 2026-09-20 addendum's canonical CSS pattern, applied to each page's own local modal markup instead of migrating them onto this component (a separate, larger JSX refactor, deliberately out of scope for the responsive pass). |
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
