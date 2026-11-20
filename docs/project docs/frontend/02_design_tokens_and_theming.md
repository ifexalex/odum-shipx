# Task FE-02 — Design Tokens & Theming

## Objective

Port the approved design system (`Shipx_frontend_design/`) into a real CSS custom-properties file plus a TypeScript mirror, and define how per-tenant branding (`tenant.branding_config`) overrides the base theme at runtime.

## Depends On

Task 01.

## Source

- `Shipx_frontend_design/uploads/DESIGN.md` — written spec
- `Shipx_frontend_design/Shipx Design System.html` — token reference (`<style>` block + token object `T` used throughout every `.jsx` mockup)
- `Shipx_frontend_design/screens/shared/components.jsx`, `app-shell.jsx` — tokens as consumed in components
- `Shipx_frontend_design/assets/odum-mark.svg` — logo asset
- `Shipx_frontend_design/uploads/Odum Brand Guideline Brief (1).pdf`, `odum-brand.pdf` — full brand rules (logo clear-space, do/don't)

**Branding note:** the product is **"ShipX"** standalone inside the app. "Odum" is the parent-brand co-mark shown only on marketing-adjacent surfaces (login screen, public tracking page, footer) as a small "by Odum" lockup — never inside the authenticated app shell.

## Token Set

Port these as CSS custom properties on `:root` in `src/design/tokens.css`, and as a parallel `theme.ts` object for any place a JS value is needed (e.g. computed chart colors).

### Color

```css
:root {
  /* Brand */
  --color-primary: #1C7922;        /* Odum Green — buttons, links, active states */
  --color-primary-deep: #14471A;   /* button active */
  --color-primary-strong: #155F1B; /* button hover */
  --color-primary-bright: #2DC438; /* focus rings, progress, "Green Flash" */
  --color-primary-soft: #D6F5DA;   /* selected row bg */
  --color-primary-tint: #F3FCF4;   /* hover row bg */

  --color-forest-dark: #0B2F0D;    /* sidebar background — never navy */

  --color-accent: #9A3412;         /* Kola Copper — ONE highest-stakes CTA per screen only */
  --color-accent-deep: #7C2D12;
  --color-accent-hover: #C2410C;
  --color-accent-soft: #FED7AA;

  /* Neutrals: one cool grey ramp (FD-03); every ink reads at 4.5:1 on every surface */
  --color-ink: #1F2329;
  --color-ink-2: #374151;
  --color-ink-3: #4B5563;
  --color-ink-4: #5F6672;
  --color-line: #D1D5DB;            /* dividers, card edges */
  --color-control-border: #868C97;  /* inputs, selects, search boxes: 3:1 on every surface */
  --color-line-soft: #E5E7EB;
  --color-surface: #FFFFFF;
  --color-surface-muted: #F9FAFB;
  --color-page: #F3F4F6;

  /* Status: the bases are text-safe (4.5:1 on every surface); -fill is the background of white button text */
  --color-success: #15803D;       --color-success-strong: #14532D; --color-success-soft: #DCFCE7;
  --color-warning: #B45309;       --color-warning-strong: #7C2D0E; --color-warning-soft: #FEF3C7;
  --color-error:   #C81E1E;       --color-error-strong:   #991B1B; --color-error-soft:   #FEE2E2;
  --color-success-fill / --color-error-fill  (= the base in light; #15803D / #B91C1C in dark)
  --color-primary-text  (brand green as text: = --color-primary in light, #5BD069 in dark)
  --color-on-dark, -muted (0.72), -subtle (0.5), -fill, -fill-strong, -line; --color-shade; --color-on-light
  --color-info:    #2563EB;       --color-info-strong:    #1E3A8A; --color-info-soft:    #DBEAFE;

  /* Role accents — used for sidebar badges, avatars, role chips */
  --color-role-platform:  #7C3AED;
  --color-role-admin:     #1C7922;
  --color-role-china:     #4F46E5;
  --color-role-nigeria:   #9A3412;
  --color-role-warehouse: #B45309;
  --color-role-customer:  #1A7F26;
  --color-role-platform-soft: #EDE9FE; /* added in FE-03: purple Badge variant background (platform role badge) */

  /* Typography */
  /* All shipped by src/design/fonts.css (self-hosted); "ShipX Naira" draws only ₦ (FD-06) */
  --font-display: "ShipX Naira", "Manrope Variable", sans-serif;
  --font-body: "ShipX Naira", "Kumbh Sans Variable", sans-serif;
  --font-mono: "ShipX Naira", "JetBrains Mono Variable", monospace;

  /* Type scale (FD-01): the only sizes on screen. Each has a paired line height (--text-*-line). */
  --text-xs: 12px;  /* 16 — table headers, badges, captions; the smallest size on screen */
  --text-sm: 13px;  /* 20 — table cells, helper text, meta lines */
  --text-md: 14px;  /* 20 — body text (set on <body>), inputs, buttons */
  --text-lg: 16px;  /* 24 — card titles, lead text */
  --text-xl: 20px;  /* 28 — section titles */
  --text-2xl: 24px; /* 32 — page titles, stat values */
  --text-3xl: 32px; /* 40 — hero figures */
  --leading-tight: 1.25; --leading-body: 1.5;          /* rules that inherit their size */
  --tracking-label: 0.04em; --tracking-tight: -0.01em; /* uppercase labels; text of 20 px and above */

  /* Spacing scale (FD-02), named by 4 px units: every gap, padding and margin is one of these */
  --space-0-5: 2px; --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
  --space-5: 20px;  --space-6: 24px; --space-8: 32px; --space-12: 48px; --space-16: 64px;

  /* Layout */
  --sidebar-width: 240px;
  --sidebar-width-collapsed: 64px;
  --content-max-width: 1280px;

  /* Radius (FD-04): four steps in order, plus full; 50% stays allowed for circles */
  --radius-sm: 4px;   /* tags, small chips */
  --radius-md: 8px;   /* controls: buttons, inputs, menus */
  --radius-lg: 12px;  /* cards */
  --radius-xl: 16px;  /* modals, hero panels */
  --radius-full: 9999px;

  /* Shadows — tinted with Forest Dark, never pure black */
  --shadow-rest:  0 1px 3px rgba(11,47,13,0.08), 0 1px 2px rgba(11,47,13,0.05);
  --shadow-hover: 0 4px 12px rgba(11,47,13,0.10), 0 2px 4px rgba(11,47,13,0.06);
  --shadow-modal: 0 10px 25px rgba(11,47,13,0.18);
  --shadow-popover: 0 8px 24px rgba(11,47,13,0.14), 0 2px 6px rgba(11,47,13,0.08);  /* menus, dropdowns */
  --shadow-focus-ring: 0 0 0 3px rgba(45,196,56,0.35);
  --shadow-selected: 0 0 0 3px color-mix(in srgb, var(--color-primary) 16%, transparent);  /* chosen option, current step */
  --shadow-glow: 0 0 8px var(--color-primary-bright);  /* live-status dot */

  /* Layers (FD-05); -1/0/1 allowed for order inside one component */
  --layer-sticky: 10; --layer-dropdown: 20; --layer-drawer: 30; --layer-modal: 40; --layer-toast: 50;

  /* Motion (FD-05): two durations, one easing; both 0ms under prefers-reduced-motion */
  --motion-fast: 120ms; --motion-base: 180ms; --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --scrim-modal: rgba(11,47,13,0.55);
}
```

### Type Scale

| Token | Size | Weight | Line height | Use |
|---|---|---|---|---|
| `display-lg` | 32px | 700 | 1.25 | One hero heading per page, max |
| `display-md` | 24px | 700 | 1.33 | Section/page titles |
| `headline-lg` | 20px | 600 | 1.4 | Card/modal titles |
| `headline-md` | 16px | 600 | 1.5 | Subsection titles |
| `body-lg` | 16px | 400 | 1.5 | Prose |
| `body-md` | 14px | 400 | 1.43 | Default — table cells, descriptions |
| `body-sm` | 12px | 400 | 1.33 | Captions, metadata |
| `label-md` | 14px | 500 | 1.43 | Button text, form labels |
| `label-sm` | 12px | 600 | 1.33 | Uppercase status badges, tags (`letter-spacing: 0.04em`) |
| `mono` | 13px | 400 | 1.54 | Tracking codes, container numbers, monetary amounts — **always** use mono for these so table columns align |

### Hard Rules (carried from the brand brief — don't relitigate these in PR review, they're settled)

- Never italicize. Use weight contrast instead.
- Kola Copper (`--color-accent`) is reserved for **one** highest-stakes action per screen (payment confirmation, release-note generation, irreversible actions). If a screen has two CTAs that both feel critical, demote one to primary green.
- Radius follows the component, not taste (FD-04): `sm` for tags and small chips, `md` for controls, `lg` for cards, `xl` for modals and hero panels, `full` for pills. A `full` badge inside an `lg` card is fine; two sizes of the same control in one view are not.
- Form inputs keep a visible 1px `--color-control-border` border at rest, never invisible until focus. It is 3:1 against every surface (FD-03); `--color-line` is for dividers only.
- No zebra-striping on tables. Use `--color-line-soft` row dividers only.
- Contrast is measured by `src/design/contrast.test.ts` in both themes (FD-03). A new text or control pair goes into that test.

## Tenant Branding Override

`tenant.branding_config` (JSONB, returned by `GET /v1/tenant/config`) carries at minimum:

```json
{ "company_name": "Acme Logistics", "display_name": "Acme Logistics", "primary_color": "#1A5276" }
```

At runtime, after the authenticated session resolves `tenant_id` and fetches config:

1. If `primary_color` is set, override `--color-primary` (and derive `--color-primary-deep` / `--color-primary-strong` / `--color-primary-soft` / `--color-primary-tint` programmatically — e.g. HSL lightness shift — rather than requiring the tenant to supply 5 shades).
2. Render `company_name` in the sidebar brand slot in place of the ShipX wordmark for tenant-scoped staff/customer views (`TenantBrand` pattern in the mockups — see `screens/shared/app-shell.jsx`).
3. Platform Admin views and the login screen always use the canonical ShipX/Odum brand — tenant overrides only apply once a tenant context is resolved.
4. **Never** let a tenant override `--color-error` / `--color-success` / `--color-warning` / `--color-info` — status colors stay consistent across tenants so staff moving between tenants (or platform admin impersonating) aren't misled by a relabeled status color.

Implementation: a `ThemeProvider` that writes CSS custom property overrides onto a scoped `<div data-tenant-theme>` wrapper (not `:root`, so the platform admin shell and any pre-auth screen keep the canonical palette even while a tenant theme is loaded elsewhere, e.g. inside an impersonation iframe-equivalent view).

## Logo Assets

- Copy `Shipx_frontend_design/assets/odum-mark.svg` into `frontend/public/` and `src/design/components/` as a React component (`<KolaMark />`, ported from `screens/shared/components.jsx`).
- Minimum render size: 16px (favicon floor).
- Clear space: one lobe-width on all sides.
- Don'ts (enforce in code review, not just docs): never recolor lobes individually, never stretch/skew/rotate, never place on busy photo backgrounds without a solid scrim.

## Responsive Breakpoint Convention

**Added 2026-09-20** (previously informal, never written down — codified during
the app-wide responsive pass).

- ~~**860px is the one mobile breakpoint** used everywhere new responsive work
  touches.~~ *Superseded 2026-11-20 (FD-35): three breakpoints, see below.* Both app shells (`PageShell.module.css` for staff/admin,
  `CustShell.module.css` for the customer portal) declare
  `container-type: inline-size; container-name: sxapp` on their shell root, so
  every descendant component queries the **shell's own measured width**, not
  the browser viewport, via `@container sxapp (max-width: 860px) { ... }`.
  This is deliberate: a docked sidebar (240px) changes the available content
  width independently of the browser window, and container queries key off
  the actual space a component has, not the outer viewport.
- Write mobile styles unqueried and wrap the **desktop** upgrade in
  `@container sxapp (min-width: 861px)` for anything that is mobile-first by
  construction (the canonical bottom-sheet modal pattern — see
  `03_component_library.md`'s Modal section). Write mobile styles inside
  `@container sxapp (max-width: 860px)` for anything that is desktop-first
  (most existing page layouts, stat grids, hero rows).
- Fall back to an equivalent `@media` query only for content rendered outside
  either shell (there is essentially none today — every authenticated route
  renders inside `PageShell` or `CustShell`).
- 44×44px minimum touch target, ≥16px input font-size (prevents iOS Safari's
  auto-zoom on focus), and `max-height: 90vh; overflow-y: auto` on any modal
  panel are the three mobile hygiene rules applied wherever a modal or form
  input was touched in the 2026-09-20 pass — see `Field.module.css` and the
  modal pattern in `03_component_library.md`.

### Three breakpoints (FD-35, 2026-11-20)

The app changes layout at **600, 860 and 1200 px** only: phone, tablet (the sidebar becomes a drawer), desktop. Styles had switched at eleven widths (420, 520, 560, 600, 720, 760, 768, 860, 920, 1080, 1240), so neighbouring parts of a page changed at different widths. Every `@media` rule and every `@container sxapp` rule uses one of the three (`min-width` takes the next pixel: 601, 861, 1201); the 1080 and 1240 rules became 1200, 720 to 920 became 860, 420 to 560 became 600, and the modal goes full-screen below 600 (it was 768). Container queries on a component's own width (a table's `cardBreakpoint`, a stat card too narrow for its icon) are that component's behaviour and are not counted. Guard: `src/design/breakpoints.test.ts` (proved with a 640 px rule).

Tokens added with it: `--app-bottom-bar` (0, or 72px while a page shows its fixed action bar on a phone; the shells pad their content by it and toasts sit above it) and `--safe-area-bottom` (the device's bottom inset).

## Acceptance Criteria

- [x] `src/design/tokens.css` defines every token above as a CSS custom property on `:root`
- [x] `src/design/theme.ts` exports the same values typed for JS consumption (charts, computed styles)
- [x] `<KolaMark />` and `<ShipxWordmark />` components ported and rendering correctly at 16px–64px
- [x] `ThemeProvider` applies tenant `primary_color` override scoped to the authenticated app shell, without affecting the login screen or Platform Admin views (scoped to `[data-tenant-theme]`, not `:root`; derivation in `deriveBrandShades.ts`)
- [x] Status colors (`success`/`warning`/`error`/`info`) are confirmed non-overridable by tenant config (write a test asserting this) — see `ThemeProvider.test.tsx`
- [x] A visual smoke test (Storybook or a `/design-preview` dev-only route) renders the full palette, type scale, and radius/shadow tokens for design QA sign-off before component work begins — `src/design/DesignPreview.tsx`, mounted dev-only in `App.tsx`

## Implementation notes / ground-truth gaps found

- **Radius (FD-04, 2026-11-19).** `--radius-xl` (12 px) was smaller than `--radius-lg` (14 px), and about half of all radius declarations were raw (2 to 28 px). The scale is now sm 4 / md 8 / lg 12 / xl 16 / full. The old token names changed meaning (old `sm` was 8 px), so existing uses were remapped by value. Old md/lg became lg (cards), or xl in a modal-like rule (`modal`, `sheet`, `dialog`, `drawer`, `panel`, `overlay`, `hero` but not `heroIcon`). Raw values went to the nearest step: up to 5 → sm, up to 9 → md, up to 13 → lg, 14 → lg (or xl in a modal), above → xl; 999 → full. 55 style sheets and 26 components changed. **`Card` radius is named**: `radius="lg" | "xl"`, default lg (12 px; it was 10). Guard: only the tokens, `0` or `50%`.
- **Layers, shadows and motion (FD-05, 2026-11-19).** There were 13 z-index values (1 to 2000), now five layers. Dropdowns, menus and the notification panel go to dropdown, with click-catchers at `dropdown - 1`. Mobile nav drawers go to drawer. Every modal and overlay (100, 130, 200, 300, 1000) goes to modal. The dev role switcher goes to toast. 0/1 inside a component stay. Shadows were already mostly tokens after FD-03; the selection halos and the live-dot glow became `--shadow-selected` / `--shadow-glow`, and keyframe steps (the announcement pulse) are left alone. Ten transition durations and three easings became `--motion-fast` (up to 150 ms before) or `--motion-base` with `--ease-standard`. A global `prefers-reduced-motion` rule makes transitions instant; it was in 3 rules before. **Buttons no longer lift on hover.** Filled buttons darken and gain `--shadow-rest`; secondary and ghost change background only. Two hover bugs were fixed along the way. In dark mode, danger and success hovered to their `-strong` tokens, which are light there, so the white label became unreadable on hover; they now darken their own fill (`color-mix(… 85%, black)`). The accent hover got lighter; it now goes to `--color-accent-deep`. Guard: z-index only as a `--layer-*` token (or −1/0/1), box-shadow only as a `--shadow-*` token, transition timing only as `--motion-*` / `--ease-standard`.
- **Inline colours (FD-03 follow-up, 2026-11-19).** The FD-03 colour guard read only style sheets, which missed 14 raw colours in inline styles: three scrims, two current-step dots that stayed white in dark mode, the Account danger zone, and the wordmark default. They are now tokens. The WhatsApp preview on Notification templates keeps WhatsApp's own chat colours, on purpose, in `NotificationTemplates.module.css`, marked `scale-exempt` with that reason. The guard now covers inline styles too.
- **Colour tokens and contrast (FD-03, 2026-11-19).** Four names were used in 15 places and defined nowhere, so they rendered as nothing (popovers had no shadow). `--shadow-lg` is now `--shadow-popover` (new, light and dark), `--color-surface-2` is `--color-surface-muted`, `--color-ink-1` is `--color-ink`, and `--color-line-strong` is `--color-control-border`. The eight aliases (`--color-text`, `--color-text-muted`, `--color-border`, `--color-*-muted`; ~140 uses) are deleted and renamed to the canonical tokens. **About 90 raw colours** in 63 files became tokens: the scrim (16), translucent white on the dark brand surfaces (new `--color-on-dark*` set), `#fff` on brand, and raw-colour `var()` fallbacks; one-off tints use `color-mix()` of a token. **Contrast**, measured by `src/design/contrast.test.ts` in both themes:
    - Light: success 3.3 → `#15803D` 5.0, warning 3.2 → `#B45309` 5.0, error 4.4 on the page → `#C81E1E`, `--color-ink-4` 4.4 on the page → `#5F6672` 5.3, `--color-ink-3` was nearly identical to ink-4 → `#4B5563`. The new control border is 3.4:1; it was 1.6:1 with `--color-line`. Role colours: warehouse 3.2 → `#B45309`, customer 2.3 → `#1A7F26`. The sidebar role badge put white text on the bright flash green; it now uses the brand green.
    - Dark: the test found what the brief missed. Brand green as text was 3.1:1 on dark cards, so there is a new `--color-primary-text` (light green in dark), used by the ~60 `color: var(--color-primary)` rules. White on the success and error buttons was 2.7 and 3.3, so there are new `--color-success-fill` / `--color-error-fill`. Platform, admin, china, warehouse and customer role colours were 2.7–3.4 as text, so the dark theme lightens them. ink-4 is `#8A958A`.
    - One colour cannot be both the background of white text and text on a dark card, so those two uses now have separate tokens.
    - `Avatar` read role colours as fixed hex values from `theme.ts`, so its initials never adapted to dark mode. `roleColors` are now CSS variables; `colors.role*` stay hex for the always-dark sidebar.
    - On the dark surfaces, white below 50% fails 4.5:1. Group labels and counts at 35–45% are now `--color-on-dark-subtle` (50%). On the brand-green customer top bar only full white passes, so its links are full white.
    - Guards: `rawValues.test.ts` fails on a raw hex or `rgb()` colour in a style sheet and on any `var(--…)` that nothing defines; `contrast.test.ts` fails when any text, badge, button, on-dark or control pair drops below AA in either theme.
- **Spacing scale (FD-02, 2026-11-19).** Spacing tokens appeared in 27 declarations; about 1,450 gaps, paddings and margins used raw px or rem, including off-scale 10, 14 and 6 px. The scale is now 2, 4, 8, 12, 16, 20, 24, 32, 48 and 64 px. The tokens are renamed by 4 px units (`--space-1` = 4 px … `--space-16` = 64 px, `--space-0-5` = 2 px) because the old xs–3xl names had no room for the new 12 and 20 px steps; the 27 old uses were renamed. A codemod moved every value to its nearest step (82 style sheets, 100 components), with ties going to the larger step (6 → 8, 10 → 12, 14 → 16). Negative margins become `calc(-1 * var(--space-*))`. `theme.ts` `spacing` mirrors the scale. **`Card` padding is now named**: `padding="none" | "default" | "large"` (20 / 24 px; `none` for a card holding a table). The prop no longer takes a number. Cards with no padding go from 24 to 20 px, as the brief says. Existing uses: 0 → none, 8–20 → default, 24–32 → large. Guard: `src/design/rawValues.test.ts` (renamed from `typeScale.test.ts`; it now covers type and spacing) fails on a px or rem gap, padding or margin in a style sheet or inline style. The codemod's first run wrote Python's `None` after every value (`padding: var(--space-4)None;`). The CSS still parsed and every check passed, but browsers dropped all about 1,450 declarations. Only the visual baseline (FD-38) showed it. The same test now fails on `None`, `undefined` or `NaN` in any declaration.
- **Type scale (FD-01, 2026-11-19).** The style sheets used about 40 font sizes (6.5 to 64 px, mixed px and rem), 11 line heights, 17 letter-spacing values and weight 800. A codemod moved them onto the seven `--text-*` steps: 72 style sheets, 56 components. A size maps to the nearest step: up to 12 → xs, below 13.5 → sm, below 15 → md, below 18 → lg, below 22 → xl, up to 28 → 2xl, above → 3xl. A line height becomes its size's paired token, or `--leading-tight`/`--leading-body` where the rule inherits its size. Positive letter spacing becomes `--tracking-label`, negative becomes `--tracking-tight`. Weights 800 become 700. `<body>` had no size, so unsized text was the browser's 16 px; it is now `--text-md`. Text that was 9–11 px is now 12 px, the smallest on screen. Stat values are `--text-2xl`, as the scale says. Exempt, each rule marked `scale-exempt` with its reason: the miniature document previews (Company settings `.doc*`, packing-list wizard `.preview*`, sized like the printed page), two emoji icons and the 404 figure. Print pages and the marketing page are exempt by folder. Guard: `src/design/rawValues.test.ts` fails on any raw `font-size`, `line-height` or `letter-spacing`, or a weight outside 400–700, in a style sheet or an inline style. Values `0` and `1` stay allowed. Reviewed with the visual baseline (FD-38): all 234 screens changed, as expected, and sampled screens were checked for clipping. The phone audit then found two pages a few pixels too wide. The claim page's status stepper now scrolls inside a `ScrollStrip` at 320 px. The claim stats row on Reports wraps.
- **Fonts are self-hosted; Manrope is the brand face (FD-06, 2026-11-19).** Owner decision: Manrope, not Averta. Averta was first in the display stack but never shipped, so a user who happened to have it installed saw a different product. Google Fonts loaded 13 weight files of three families on every visit and needed `fonts.googleapis.com`/`fonts.gstatic.com` in both CSPs. Now `src/design/fonts.css` imports the `@fontsource-variable` packages for Manrope, Kumbh Sans and JetBrains Mono, pinned exactly. Each family is one variable file per script subset, so a Latin page loads three files, about 95 KB. Both CSPs (`infrastructure/aws/modules/cloudfront/main.tf`, `infrastructure/azure/locals.tf`) now allow `font-src 'self'` only. `vite.config.ts` never inlines a font as a `data:` URL, because the AWS policy does not allow `data:` fonts.
    - **₦.** None of the three faces has U+20A6, so ₦ fell back to a system font and looked heavier than the digits beside it. `ShipX Naira` is that one glyph subset from Plus Jakarta Sans: 960 bytes, variable weight 200–800, SIL OFL licence in `src/design/fonts/`. It is listed first in every stack and, through `unicode-range: U+20A6`, draws nothing else. `size-adjust: 97.5%` matches its cap height to the others. Every ₦ in the app, through `formatNgn` or typed directly, gets it with no component change. The regeneration command is in `fonts.css`.
    - **Monospace is for codes, references and tabular numbers only.** The invoice page title (the customer's name) and the customer page's email are now proportional.
    - **To license Averta later:** add its `@font-face` to `fonts.css` and put it after `ShipX Naira` in `--font-display` and `fonts.display` (`theme.ts`). Guard: `src/design/fonts.test.ts` fails if a stack names a font that is not shipped, if ₦ is not first, or if a font loads from another origin.
- **tokens.css semantic-aliases syntax bug (found & fixed 2026-07-10; the aliases themselves were removed in FD-03, 2026-11-19)**: the semantic-alias declarations (`--color-text`, `--color-text-muted`, `--color-border`, `--color-*-muted`) were appended after `:root`'s closing brace with no selector of their own. Per CSS error-recovery, the parser consumed the orphan declarations *and* the next rule as one invalid qualified rule — and the next rule was the global `* { box-sizing: border-box }` reset. Consequences until the fix: (1) the entire app silently rendered with `content-box` sizing (e.g. `.wrap`-style containers with `max-width` + padding rendered 64px wider than the prototypes intended); (2) the alias tokens never existed, so the 11 page stylesheets referencing them fell back to inherited values; (3) every `npm run build` emitted an esbuild `css-syntax-error` warning that had been ignored. Fix: wrapped the aliases in their own `:root {}` block. Discovered while pixel-diffing the marketing landing page against `Shipx Landing Page v2.html` — the implementation was 64px wider than the prototype despite identical CSS.

## Light / Dark theme (2026-10-01)

The app ships light and dark themes, driven entirely by the CSS custom properties in `src/design/tokens.css`.

**Mechanism.** The active scheme is resolved to an explicit value in JS (`src/design/colorScheme.tsx`) and written to `document.documentElement` as `data-theme="light|dark"`. A matching pre-paint script in `index.html` applies the same attribute before React mounts, so there is no light-mode flash on first load. Because 'system' is resolved in JS (reading `prefers-color-scheme`), `tokens.css` needs only a single `:root[data-theme="dark"]` block, not a duplicated media query.

**Preference model.** `useColorScheme()` exposes `{ preference, resolved, setPreference, cycle }`. `preference` is `'light' | 'dark' | 'system'` (default `'system'`, persisted to `localStorage['shipx-color-scheme']`); `resolved` is the actual `'light' | 'dark'` in effect. In `'system'` mode the provider re-resolves when the OS flips. `useColorScheme()` has a functional standalone fallback, so a `<ThemeToggle>` still works when a component is rendered without `ColorSchemeProvider` (e.g. isolated component tests). The `<ColorSchemeProvider>` wraps the app in `main.tsx`; the `<ThemeToggle>` control lives in both `TopBar` (staff) and `CustomerTopNav` (customer) and cycles System → Light → Dark.

**What flips vs. what holds.** Only surfaces, ink, lines, shadows and the soft/tint *fill* variants flip in dark mode. Brand/status/role **hues** stay recognisable — their `-soft` backgrounds go dark and their `-strong` (badge-text) variants go light so contrast holds. Two tokens exist specifically to survive the flip:
- `--color-on-brand` (always white) — text/icons that sit on a brand/accent/dark surface (buttons, chips, sidebar, the login brand panel). Never use `--color-surface` for on-colored text, since surface becomes dark.
- `--color-primary-on-soft` (dark green in light, bright green in dark) — primary text/icon on a `--color-primary-soft` fill (stat-card icon chips, granted consent pills), so it isn't green-on-green in dark.

**Adding new UI.** Use tokens, never hardcoded `#fff`/`#000`/hex backgrounds — those don't flip. For text on a colored/dark element use `--color-on-brand`. `color-scheme` is set per theme so native controls (scrollbars, date pickers) match.

### Tenant brand shades are scheme-aware (fix, 2026-10-01)

`deriveBrandShades(hex, scheme)` takes the active scheme. A tenant's `soft` (selected-row bg) and `tint` (hover-row bg) are near-white in light mode; in dark mode they're derived as dark, lightly-saturated versions of the brand hue instead. `ThemeProvider` passes `useColorScheme().resolved` and re-derives when the scheme flips. Without this, the brand-derived *light* tint was applied inline on `[data-tenant-theme]`, overriding the dark `:root[data-theme="dark"]` token — so a hovered/selected table row rendered a blinding near-white band in dark mode (reported live). `base`/`deep`/`strong` (solid buttons, white text) are scheme-independent.

### Dark-mode contrast fixes (2026-10-01)

A WCAG contrast audit of the dark palette found a few combinations below usable thresholds. Fixed **dark-only** (each new token's light value equals what the element used before, so light mode is byte-identical):

- **`<Mono>` text was dark-on-dark (critical).** `Mono` defaulted its color to the static `colors.ink` (#1c1b1c) from `theme.ts` instead of the CSS token — so uncoloured monospace values (container numbers, totals, CBM, counts) rendered ~1.0 contrast on a dark surface, effectively invisible. Changed the default to `var(--color-ink)` (flips to light in dark; identical in light). Components that read colours from `theme.ts` (the static JS mirror) do **not** respond to dark mode — `Mono` was the only text case; the remaining `theme.ts` colour reads are brand logos on always-dark panels.
- **Accent badge + brand monogram** (copper text on copper-soft) was ~1.6 contrast. New `--color-accent-on-soft` (light `#7c2d12`, dark `#f0a67e`) used by `Badge.accent`, `TenantBrand` and the packing-list preview monogram.
- **Accent eyebrow labels** (`QuickActionCard` CTA, customer greeting) were ~2.3. New `--color-accent-text` (light `#9a3412`, dark `#eb9a70`).
- **Platform / purple badge** (impersonation audit, carryover "applied") was ~2.6. New `--color-role-platform-text` (light `#7c3aed`, dark `#b99af2`).

Left as acceptable: primary-coloured links/text (~3.1–3.4 on dark) — a single `--color-primary` can't satisfy both "link text on dark" and "white text on a primary button", and it's tenant-overridable, so splitting it is deferred; the green reads as interactive and passes large-text AA. `success`-button white text (~2.7) matches the same marginal choice already shipped in light mode.
