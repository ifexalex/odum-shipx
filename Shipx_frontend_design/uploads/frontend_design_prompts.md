# ShipX — Frontend Design Prompts

> **How to use this file**
> Pass each numbered section to your AI design tool (Claude, Stitch, Figma AI, etc.) **in order**,
> starting with Section 0. Each section builds on the design tokens and components established in the
> previous one. Include the "Carry-forward context" block at the top of every prompt after Section 0.
>
> **Platform summary (include in every prompt):**
> ShipX is a multi-tenant SaaS logistics platform for China → Nigeria cargo shipping companies, built
> under the **Odum** brand. Multiple independent shipping companies (tenants) each have their own
> isolated portal with their own branding, users, and data. The platform has six user roles:
> Platform Admin, Tenant Admin, China Office Staff, Nigeria Office Staff, Warehouse Attendant,
> and Customer.

---

## Section 0 — Design System Foundation

> Pass this section first. All subsequent sections reference these tokens and components.

### Prompt

Design a complete **design system / UI kit** for **ShipX**, a logistics SaaS platform built under the
**Odum** brand. The system must visually inherit Odum's identity while remaining functional, dense,
and trust-building for a B2B logistics audience.

#### Brand Identity

- **Product name:** ShipX (a product by Odum)
- **Parent brand:** Odum — a Nigerian-rooted brand whose identity centers on being "the lion of the business world." Bold, decisive, and confident, with cultural depth drawn from Igbo heritage (the three-lobed kola nut, *Oji Ikenga / Oji Dike*, symbolizing body, mind, and spirit — strength, bravery, and unity).
- **Tagline:** "Cargo logistics, fearlessly tracked." (alt: "Lead every shipment. Guangzhou to Lagos.")
- **Brand voice:** Bold, confident, decisive. We *lead* shipments, *protect* cargo, and *roar* through borders. Prefer active, ownership-driven language ("you lead every shipment") over passive ("cargo gets shipped"). Professional and trust-building — bold but never flashy or consumer-playful.
- **Platform logo:**
  - **Wordmark:** "ShipX" set in **Averta Bold**, with characterful open counters mirroring the Odum wordmark style (Odum uses open counters in *d, u, m* — flow, openness, innovation). For the "X", use **beveled, rounded terminals** rather than sharp angular cuts — geometric strength softened by approachability, echoing Odum's beveled three-lobed kola-nut logomark.
  - **Symbol / icon:** A geometric, three-faceted cargo cube (echoing Odum's three-lobed kola-nut logomark — body, mind, spirit / origin, transit, delivery) with **beveled rounded corners**. The three facets visually represent the three legs of a shipment: origin (China), transit (sea), delivery (Nigeria).
  - **Lockup:** Symbol left, wordmark right. Co-brand with a small "by Odum" mark in marketing surfaces (auth screens, public tracker, footer). Inside the app, "ShipX" stands alone.
  - **Color:** Logo renders in `neutral-900` (Odum near-black) on light surfaces and `white` on dark surfaces. Avoid color-trend-dependent renderings.
- **Market:** B2B SaaS — Nigerian shipping companies handling China→Nigeria cargo. Professional, trust-building, dense data UI. Not consumer-playful.

#### Color Palette

The palette is **green-anchored** (Odum's primary green family) with a **warm copper accent** inspired by the kola nut's reddish-brown hue. This pairing is culturally rooted (green + earth tones echo classic West African design) and provides necessary CTA contrast against green brand surfaces.

**Brand & Primary (Odum Greens):**

| Token | Hex | Usage |
|---|---|---|
| `primary-900` | `#0B2F0D` | Sidebar background, heaviest headings (Odum Dark Green) |
| `primary-800` | `#14471A` | Sidebar hover states, deep nav contrast |
| `primary-700` | `#155F1B` | Primary navigation accents, hover states on primary buttons |
| `primary-500` | `#1C7922` | **Primary brand color** — primary buttons, links, active states (Odum Green) |
| `primary-300` | `#2DC438` | Bright accent green — focus rings, hover highlights, progress bars (Odum Faded Green) |
| `primary-100` | `#D6F5DA` | Highlighted rows, selected-row tint, soft backgrounds |
| `primary-50` | `#F3FCF4` | Page background tints, hero panel washes (Odum Ice White) |

**Accent (Kola Copper — for CTAs and key actions):**

| Token | Hex | Usage |
|---|---|---|
| `accent-600` | `#7C2D12` | Pressed/active state of accent buttons |
| `accent-500` | `#9A3412` | **CTAs** (confirm payment, generate release note, key actions) — kola-nut copper |
| `accent-400` | `#C2410C` | Hover state of accent buttons |
| `accent-100` | `#FED7AA` | Accent backgrounds, soft highlights |

**Status (functional):**

| Token | Hex | Usage |
|---|---|---|
| `success-500` | `#16A34A` | Approved, paid, cleared, picked-up, verified, active, resolved (lime-leaning, distinct from primary brand green) |
| `success-100` | `#DCFCE7` | Success backgrounds |
| `warning-500` | `#D97706` | Pending, in-progress, awaiting, draft, under-inspection (amber) |
| `warning-100` | `#FEF3C7` | Warning backgrounds |
| `danger-500` | `#DC2626` | Rejected, overdue, seized, suspended, cancelled, offboarded |
| `danger-100` | `#FEE2E2` | Error backgrounds |
| `info-500` | `#2563EB` | Informational badges, in-transit, processing, acknowledged (kept distinct from brand green) |
| `info-100` | `#DBEAFE` | Info backgrounds |

**Neutrals (Odum-warm gray family):**

| Token | Hex | Usage |
|---|---|---|
| `neutral-900` | `#1C1B1C` | Primary text (Odum Black — slightly warm, never pure #000) |
| `neutral-700` | `#374151` | Secondary text, strong labels |
| `neutral-600` | `#666666` | Tertiary text (Odum Dark Grey) |
| `neutral-500` | `#6B7280` | Placeholder text, captions, helper text |
| `neutral-300` | `#CCCCCC` | Borders, dividers (Odum Grey) |
| `neutral-200` | `#E5E7EB` | Subtle dividers, table row separators |
| `neutral-100` | `#F3F4F6` | Page background |
| `neutral-50` | `#F9FAFB` | Card backgrounds, sub-surfaces |
| `white` | `#FFFFFF` | Card surfaces, modals, primary canvas |

> **Pantone reference (for print/co-brand surfaces):** PANTONE 15-0146 TCX *Green Flash* approximates `primary-300`. Use when producing print collateral or coordinating with offline brand assets.

#### Typography

ShipX inherits the Odum type pairing: **Averta** (primary, by Kostas Bartsokas) for display and headings — its geometric forms with consistent stroke weight and characterful open counters carry the Odum identity. **Kumbh Sans** (secondary, by Saurabh Sharma — available on Google Fonts) handles body and UI text where range of weights and on-screen legibility matter most.

- **Primary family:** `Averta`. Fallback stack: `Averta, "Averta Std", Inter, system-ui, -apple-system, sans-serif`.
  - *Note:* Averta is a licensed font (commercial license required from Kostas Bartsokas / Type Department). If Averta is unavailable in any environment, fall back to **Inter** (Google Fonts) with the same scale and weights — Inter's geometric character is the closest free alternative.
- **Secondary family:** `Kumbh Sans` (Google Fonts). Fallback: `"Kumbh Sans", Inter, system-ui, sans-serif`.
- **Monospace:** `JetBrains Mono` (Google Fonts). Fallback: `"JetBrains Mono", "IBM Plex Mono", ui-monospace, "SF Mono", monospace`. Used for tracking codes, IDs, container numbers, monetary amounts in tables.

**Scale:**

| Token | Size | Weight | Family | Line-height | Usage |
|---|---|---|---|---|---|
| `display-lg` | 32px | 700 (Averta Bold) | Averta | 40px | Page H1s (dashboard hero) |
| `display-md` | 24px | 700 (Averta Bold) | Averta | 32px | Section headers, modal titles |
| `heading-lg` | 20px | 600 (Averta Semibold) | Averta | 28px | Card titles, dialog headers |
| `heading-md` | 16px | 600 (Averta Semibold) | Averta | 24px | Table headings, panel titles |
| `body-lg` | 16px | 400 (Kumbh Regular) | Kumbh Sans | 24px | Primary body text |
| `body-md` | 14px | 400 (Kumbh Regular) | Kumbh Sans | 20px | Secondary body, table cells |
| `body-sm` | 12px | 400 (Kumbh Regular) | Kumbh Sans | 16px | Captions, metadata, timestamps |
| `label-md` | 14px | 500 (Kumbh Medium) | Kumbh Sans | 20px | Form labels, nav items |
| `label-sm` | 12px | 600 (Kumbh Bold) | Kumbh Sans | 16px | Status badges, tags (uppercase + 0.04em letter-spacing) |
| `mono` | 13px | 400 | JetBrains Mono | 20px | Tracking codes, IDs, container numbers, amounts |

> **Voice in typography:** Headings (Averta) carry weight and confidence — use them sparingly but boldly. Body (Kumbh Sans) is functional and legible. Avoid italicizing — Odum's bold voice prefers weight contrast over slant.

#### Spacing & Layout

- **Base unit:** 4px. All spacing in multiples: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
- **Page layout:** Fixed sidebar (240px wide on desktop) + scrollable main content area.
- **Content max-width:** 1280px centered.
- **Card padding:** 24px.
- **Section gutter:** 24px between major sections.
- **Border-radius (Odum-flavored — slightly more rounded than typical SaaS to echo Odum's beveled forms):**
  - Buttons: **8px**
  - Cards: **10px** (beveled but not pillowy)
  - Modals: **14px**
  - Badges / pills: **9999px** (full pill — Odum's open-counter language favors flowing curves)
  - Inputs: **8px**
  - Stat tiles / hero metric containers: **12px** (to feel monumental)
- **Shadow:** Shadows are tinted with the brand dark green (not pure black) so they feel cohesive on green surfaces.
  - Cards: `0 1px 3px rgba(11,47,13,0.08), 0 1px 2px rgba(11,47,13,0.05)`
  - Cards (hover): `0 4px 12px rgba(11,47,13,0.10), 0 2px 4px rgba(11,47,13,0.06)`
  - Modals: `0 10px 25px rgba(11,47,13,0.18)`
  - Focus ring: `0 0 0 3px rgba(45,196,56,0.35)` (Odum bright green at 35% alpha)

#### Core Components

Design each of the following components in all relevant states:

**1. Button**
- Variants: `primary` (filled `primary-500` Odum Green, white text), `accent` (filled `accent-500` Kola Copper, white text), `secondary` (outlined `neutral-300`, `neutral-900` text on white), `ghost` (text only, `primary-500`), `danger` (filled `danger-500`, white text)
- Sizes: `sm` (28px height), `md` (36px), `lg` (44px)
- States: default, hover (primary darkens to `primary-700`; accent darkens to `accent-400`), active/pressed (one tone deeper still — `accent-600` for accent), disabled (50% opacity, no pointer), loading (spinner replaces label, button stays full-width)
- Icon support: leading icon, trailing icon, icon-only
- Border-radius: 8px. Font: `label-md` Kumbh Medium.

**2. Badge / Status Chip**
- Pill shape (radius 9999px), small **filled dot indicator** on the left, `label-sm` text (uppercase + 0.04em letter-spacing).
- Variants mapped to statuses (badges use `*-100` background + `*-500` text + `*-500` dot — except gray which uses neutrals):
  - **Green (success-500):** `paid`, `approved`, `cleared`, `picked_up`, `verified`, `active`, `resolved`
  - **Blue (info-500):** `in_transit`, `processing`, `acknowledged`, `pending_approval`
  - **Amber (warning-500):** `unpaid`, `partially_paid`, `pending_review`, `pending`, `draft`, `under_inspection`
  - **Copper (accent-500):** `discrepancies_found`, `investigating`, `accounts_reviewed` (uses kola-copper to feel "in active human review")
  - **Red (danger-500):** `rejected`, `cancelled`, `suspended`, `seized`, `overdue`, `offboarded`
  - **Purple (`#7C3AED` text on `#EDE9FE` bg):** `waived`, `released_with_outstanding`, `applied_as_credit`
  - **Gray (neutral-600 text on neutral-200 bg):** `inactive`, `expired`, `no_action`, `closed`

**3. Data Table**
- Columns: fixed left (checkbox), variable middle cells, fixed right (actions column).
- Header row: `neutral-50` background, `heading-md` Averta Semibold, `neutral-700` text.
- Body rows: `body-md` Kumbh Regular. Row separators use `neutral-200` 1px lines (no heavy zebra striping — Odum prefers clean geometry).
- Row states: default (white), hover (`primary-50` Ice White wash), selected (`primary-100` light green tint + checkbox ticked + 2px `primary-500` left border), loading (skeleton rows pulsing `neutral-100` ↔ `neutral-200`).
- Pagination bar: "Showing 1–20 of 143 results" in `body-sm` `neutral-500`, Previous/Next as ghost buttons with chevron icons, rows-per-page selector (dropdown).
- Empty state: centered illustration (cargo container line-art in `neutral-300`) + heading + optional CTA button.
- Sortable column headers: up/down chevron indicator in `neutral-500` (becomes `primary-500` when active).

**4. Input Fields**
- Types: text, textarea, number, date, select/dropdown, multi-select, search (with leading magnifier icon), file upload.
- Border: 1px `neutral-300`, radius 8px, height 40px (single-line), padding 12px 14px.
- States: default, focused (2px `primary-500` border + 3px `rgba(45,196,56,0.35)` focus ring), filled (no visual change beyond content), error (1px `danger-500` border + `danger-500` error message below), disabled (`neutral-100` bg, `neutral-500` text, no pointer).
- Label above (`label-md` Kumbh Medium, `neutral-700`), helper text below (`body-sm` `neutral-500`), error text replaces helper (`body-sm` `danger-500`).

**5. Card**
- Variants: `stat` (metric card — large `display-md` number in `neutral-900` Averta Bold + `label-md` label in `neutral-600` Kumbh + small trend indicator with arrow icon in `success-500` or `danger-500`), `content` (header + body + optional footer with right-aligned action buttons), `list-item` (compact row card, 12px radius, used in dense lists).
- Default: `white` bg, `neutral-200` 1px border, 10px radius, default shadow.
- Hover (when interactive): subtle shadow lift (use hover shadow token), no border color change.

**6. Sidebar Navigation**
- Background: `primary-900` (Odum Dark Green — a deep, near-forest green that feels grounded, not corporate-navy).
- Top: ShipX logo lockup (white wordmark + symbol). 24px padding around.
- Below logo: tenant name/logo area (white text on dark, `heading-md` Averta Semibold). Tenant logo if uploaded — 32px tall, left-aligned.
- Nav sections: section labels in `neutral-300` (light gray for legibility on dark green), uppercase `label-sm` with 0.06em letter-spacing.
- Nav items: 40px tall, icon (20px) + label (`label-md` Kumbh Medium). Default: `neutral-300` text. Hover: `white` text + `primary-800` row background. Active: `white` text + `primary-800` background + 3px `primary-300` (bright green) left border.
- Collapsible subsections: chevron rotates on expand.
- Bottom: User avatar (32px circle) + name (`label-md` white) + role (`body-sm` `neutral-300`) + logout icon button.

**7. Top Bar / Header**
- Background: `white`, 1px `neutral-200` border-bottom, 64px tall.
- Left: Page title (current section name) in `heading-lg` Averta Semibold `neutral-900`. Optional breadcrumb above.
- Right side, in order: search input (240px wide, `neutral-100` bg, magnifier icon), notification bell icon (with red `danger-500` count badge if unread), user avatar dropdown (32px circle + dropdown chevron).

**8. Modal / Dialog**
- Centered overlay (backdrop `rgba(11,47,13,0.55)` — green-tinted scrim), modal `white` bg, 14px radius, modal shadow.
- Sizes: `sm` 480px (alert/confirm), `md` 560px (forms), `lg` 720px (forms with multi-section), `xl` 960px (detail views). Fullscreen on mobile.
- Header: title (`display-md` Averta Bold) on left + close (X) icon button on right. 24px padding.
- Body: scrollable if content overflows. Max-height 70vh.
- Footer: right-aligned action buttons (cancel `ghost` + confirm `primary` or `accent` or `danger` depending on action). 16px button gap.

**9. Toast Notifications**
- Position: top-right, stacking with 8px gap. Width 360px on desktop.
- Variants: success (`success-500` 4px left border + check icon), error (`danger-500` + alert icon), warning (`warning-500` + warning icon), info (`info-500` + info icon).
- Body: `body-md` Kumbh Regular `neutral-900`. Optional `body-sm` description in `neutral-600`.
- Auto-dismiss at 4 seconds (success/info) or 7 seconds (warning/error). Manual close X button always visible.

**10. Timeline / Activity Feed**
- Vertical line in `neutral-200` with **filled circle dots** (10px) at each event. Dots use status colors: `success-500` for completed events, `primary-500` for current, `neutral-300` for upcoming/pending.
- Event row: dot + timestamp (`body-sm` `neutral-500`, right-aligned) + event label (`label-md` Kumbh Medium `neutral-900`) + optional description (`body-sm` `neutral-600`).
- 16px gap between events. Used for: shipment tracking, audit log, claim history, dispute timeline.

**11. Filter Bar**
- Horizontal strip below page header. `neutral-50` bg, 16px vertical padding.
- Dropdowns for filterable fields (status, date range, customer, container) — secondary buttons with chevron.
- Active filter chips (dismissible — small pill with X icon, `primary-100` bg, `primary-700` text).
- "Clear all" link (`primary-500`, `body-sm`).
- Right-aligned: count of results (`body-sm` `neutral-500`) + export button (`secondary` button with download icon).

**12. Tabs**
- Underline style (not pill).
- Default tab: `label-md` Kumbh Medium `neutral-600`, no underline. Hover: `neutral-900` + 2px `neutral-300` underline.
- Active tab: `label-md` Kumbh **Bold** `primary-500`, 2px `primary-500` underline.
- Variants: page-level tabs (44px tall, 24px gap), panel-level tabs (32px tall, 16px gap, used inside cards).

**13. Empty State**
- Centered in content area, max-width 360px.
- SVG illustration (cargo-themed: container, document, map pin icons in `neutral-300` line-art style — geometric and beveled, matching the Odum logomark vocabulary).
- Heading: `heading-lg` Averta Semibold.
- Subtext: `body-md` Kumbh Regular `neutral-500`.
- Optional CTA button (`primary` or `accent`).

**14. Skeleton Loaders**
- Animated pulse blocks transitioning `neutral-100` ↔ `neutral-200`, matching the shape of real content (rows, cards, stat blocks, avatars). Radius matches the target component.

**15. Breadcrumb**
- Separator: `/` in `neutral-300`.
- Current page (last item): `neutral-900` non-link, `body-sm` Kumbh Medium.
- Parent pages: `primary-500` text links, `body-sm` Kumbh Regular, hover underline.

#### Responsive Behavior

- **Desktop (≥1280px):** Fixed 240px sidebar + full content area.
- **Tablet (768–1279px):** Collapsible sidebar (icon-only 64px when collapsed; tooltip on hover shows label). Content adapts to narrower width.
- **Mobile (<768px):** Bottom navigation bar (max 5 icons, 64px tall, `white` bg, `primary-900` icons, active tab uses `primary-500`). Sidebar appears as a slide-in drawer when hamburger is tapped. Tables scroll horizontally with sticky first column. Cards stack vertically.

#### Role-Based Theme Accents

Each portal retains the same base design system but has a subtle accent in the sidebar role label and top-bar role badge to help users orient at a glance. The sidebar background remains `primary-900` Odum Dark Green for all roles — only the role-label color and badge change.

| Role Portal | Role-label color | Top-bar badge | Notes |
|---|---|---|---|
| Platform Admin | `#7C3AED` (deep purple) | "Platform" | Authoritative, distinct from tenant brand |
| Tenant Admin | `primary-500` Odum Green | "Admin" | The Odum brand color — the "owner's portal" |
| China Office Staff | `#6366F1` (indigo) | "China Office" | Cool tone, geographically distinct |
| Nigeria Office Staff | `accent-500` Kola Copper | "Nigeria Office" | Earth-toned, culturally rooted to home market |
| Warehouse Attendant | `warning-500` amber | "Warehouse" | Operational, hi-vis feel |
| Customer | `primary-300` bright green | (no badge) | Welcoming, lighter brand green |

---

## Section 1 — Authentication Screens

> **Carry-forward context:** Use the design system from Section 0. ShipX is a multi-tenant SaaS logistics platform for China→Nigeria cargo. Six user roles share the same auth flow but land on different portals after login.

### Prompt

Design the **authentication screens** for ShipX. These are the only screens without the sidebar layout — they use a split-panel layout.

#### Layout: Split Panel

- **Left panel (40%):** Dark panel using `primary-900` (Odum Dark Green) background.
  - ShipX logo lockup (symbol + wordmark, white) centered vertically — three-faceted beveled cargo cube symbol next to "ShipX" wordmark in Averta Bold.
  - Tagline below logo: **"Cargo logistics, fearlessly tracked."** (`heading-lg` Averta Semibold, white)
  - Sub-tagline: "Guangzhou to Lagos. End-to-end. Unstoppable." (`body-md` Kumbh Regular, `primary-300` bright green for accent)
  - Below: A subtle illustration of a cargo container / ship silhouette rendered with **beveled rounded corners** in `primary-700` (echoing the Odum kola-nut logomark vocabulary — geometric strength softened by approachability).
  - Bottom: small "by **Odum**" co-brand mark (`label-sm` `primary-300`) followed by "Powered by ShipX Platform" (`body-sm` `neutral-300`).
- **Right panel (60%):** White background, form centered vertically with max-width 420px.

#### Screen 1.1 — Login

**URL:** `/login`

**Right panel content:**
- Heading: "Sign in to ShipX" (`display-md`)
- Subtext: "Enter your credentials to access your portal." (`body-md`, `neutral-500`)
- Form fields:
  - Email address (text input, placeholder: "you@company.com", leading envelope icon)
  - Password (text input, type=password, trailing eye/hide icon, placeholder: "••••••••")
- Checkbox: "Remember me for 30 days"
- "Forgot password?" link (right-aligned, below password field)
- Primary button: "Sign In" (full width, `lg` size, `accent-500` kola copper)
- Divider: "or"
- Secondary text: "New customer? Register here →" (links to `/register`)

**States to design:**
- Default (empty form)
- Filled (email + password entered, button active)
- Loading (button shows spinner, fields disabled)
- Error: "Invalid email or password" — red inline alert box above the form fields
- Error: "Your account has been suspended. Contact your administrator." — different error message
- Error: "Your company account is suspended. Contact ShipX support." — tenant-suspended state

#### Screen 1.2 — Customer Self-Registration

**URL:** `/register`

**Right panel content:**
- Heading: "Create your account" (`display-md`)
- Subtext: "Register to track your shipments and manage billing." (`body-md`)
- Form fields (stacked):
  - Full name (text input)
  - Email address (text input)
  - Phone number (text input, placeholder: "+234...")
  - WhatsApp number (text input, optional, placeholder: "+234... (if different)")
  - Notification preferences (multi-checkbox): "Notify me via: ☐ SMS ☐ WhatsApp ☐ Email"
  - Password (with strength indicator below: weak/medium/strong colored bar)
  - Confirm password
- Consent checkbox: "I agree to the Terms of Service and Privacy Policy" (required)
- Primary button: "Create Account" (full width, `lg`, accent-500)
- "Already have an account? Sign in →"

**States:**
- Default
- Validation errors (inline per field)
- Success state: replace form with a green checkmark illustration + "Account created! Check your email to verify." message

#### Screen 1.3 — Forgot Password

**URL:** `/forgot-password`

**Right panel content:**
- Back link: "← Back to login" (top left)
- Heading: "Reset your password"
- Subtext: "Enter your email and we'll send a reset link."
- Form: Email input + "Send Reset Link" button (full width)

**Step 2 (after submission):** Replace form with:
- Email icon (large)
- "Check your email"
- "We sent a password reset link to **user@example.com**"
- "Didn't receive it? Resend email" link
- "Back to login" link

#### Screen 1.4 — Set New Password

**URL:** `/reset-password?token=...`

- Heading: "Set a new password"
- Form: New password (with strength bar) + Confirm new password
- Button: "Update Password"
- Success state: "Password updated! Redirecting to login..." with spinning loader

#### Mobile Layout (Auth)

On mobile: left panel collapses — show only the ShipX logo at top of a full-width white screen. Form below.

---

## Section 2 — Platform Admin: Dashboard & Tenant Management

> **Carry-forward context:** Use the design system from Section 0. Platform Admin has the highest privilege — they manage all tenants. Sidebar label reads "Platform" in `#7C3AED` deep purple (per the Role-Based Theme Accents table in Section 0). This portal lives at `/platform/...`.

### Prompt

Design the **Platform Admin portal** screens: the dashboard overview, tenant list, and tenant detail/management.

#### Sidebar Navigation (Platform Admin)

Left sidebar (`primary-900` background, 240px):
- Logo: ShipX wordmark (white)
- Role badge: "PLATFORM ADMIN" pill in `accent-500`
- Nav sections:
  - **Overview:** Dashboard
  - **Tenants:** All Tenants, Create Tenant
  - **Platform:** Settings, Audit Log
- Bottom: Avatar + "Platform Admin" + Logout

#### Screen 2.1 — Platform Dashboard

**URL:** `/platform/dashboard`

**Page header:** "Platform Overview" + date range selector (Last 30 days / This month / Custom)

**Top stat row (4 cards):**
1. **Active Tenants** — large number (e.g. 12), subtext "2 suspended", trend: "+2 this month"
2. **Total API Calls (30d)** — number with "M" suffix, trend percentage vs last period
3. **Containers Processed (30d)** — number across all tenants
4. **Platform MRR** — "₦X,XXX,XXX" (or USD), trend

**Tenant Health Table** (below stats):
- Title: "Tenant Health" with "View all" link
- Columns: Tenant Name | Status badge | Plan | Active Users | Containers (30d) | API Calls (30d) | Storage | Actions
- Status badges: `active`, `suspended`, `offboarded`
- Actions column: "View" button per row
- Max 10 rows, paginated
- Empty state for no tenants

**Recent Platform Activity** (right sidebar panel, 30% width):
- Title: "Recent Activity"
- Timeline of last 20 platform-level audit events: tenant created, tenant suspended, settings changed
- Each event: icon + description + "by Platform Admin" + timestamp relative (e.g. "2h ago")

**Quick Actions** (below the main table):
- Row of 3 cards: "Onboard New Tenant" (CTA card with + icon), "View Audit Log", "Platform Settings"

#### Screen 2.2 — Tenant List

**URL:** `/platform/tenants`

**Page header:** "Tenants" + "Onboard New Tenant" button (accent-500, right aligned)

**Filter bar:**
- Status filter: All | Active | Suspended | Offboarded
- Search input: "Search by name, email, ID..."
- Sort: Name | Created Date | Last Active

**Tenant Table:**
- Columns: ☐ | Tenant Name + Logo (avatar) | ID (monospace, truncated) | Status | Plan | Primary Contact | Users | Created | Actions
- Actions: Three-dot menu → View Details, Suspend, Activate, Reactivate, Offboard
- Suspended rows: subtle red-tinted background
- Row click → navigate to tenant detail

**Empty state:** "No tenants yet. Start by onboarding your first tenant."

#### Screen 2.3 — Create Tenant (Modal or full page)

**URL:** `/platform/tenants/new`

Design as a full-page form with two-column layout:

**Left column — Company Details:**
- Company name (required)
- Primary contact email (required) — this becomes the first Tenant Admin user
- Primary contact name
- Origin country (dropdown, default: China)
- Destination country (dropdown, default: Nigeria)
- Company logo upload (drag-and-drop + file picker, preview thumbnail)

**Right column — Subscription & Configuration:**
- Subscription plan (radio group: Starter | Professional | Enterprise — show feature list per plan)
- Initial dollar rate (number input, placeholder: "1550.00", label: "USD → NGN rate at onboarding")
- Initial CBM rate (number input, label: "Rate per CBM in USD")
- Max users (number, auto-filled by plan)
- Max containers/month (number, auto-filled by plan)

**Footer:** Cancel (ghost) + "Onboard Tenant" (primary, large) buttons

**Success state:** Full-page success card — "Tenant '{name}' onboarded! Admin invite sent to {email}." with a "View Tenant" and "Onboard Another" button.

#### Screen 2.4 — Tenant Detail

**URL:** `/platform/tenants/:id`

**Page header:**
- Breadcrumb: Platform > Tenants > Acme Logistics
- Tenant logo (48px avatar) + Tenant name (`display-md`) + Status badge
- Right side: Action buttons depending on status:
  - Active → "Suspend" (danger outlined) | "View as Tenant Admin" (ghost)
  - Suspended → "Activate" (success) | "Reactivate" (if previously active) | "Offboard" (danger)

**Page tabs:** Overview | Users | Usage & Billing | Configuration | Audit Log

**Tab: Overview**
- Two-column layout:
  - Left: Company info card (name, contact, origin/destination, plan, onboarded date, last active)
  - Right: Key metrics card (active users, containers this month, API calls this month, storage used/quota)
- Below: Recent containers table (last 5 containers processed by this tenant) — columns: Container # | Status | Customers | Created Date
- Recent users table (last 5 users created) — columns: Name | Role | Email | Last Login

**Tab: Users**
- Table of all users for this tenant
- Columns: Name | Email | Role | Status | Last Login | Actions
- Actions: Resend Invite, Reset Password, Deactivate

**Tab: Usage & Billing**
- Period selector (month/year)
- Usage stat cards: API Calls | Containers Processed | Storage Used | Active Users
- Bar chart: API calls by day for the period
- Usage vs limit progress bars for each metered dimension

**Tab: Configuration**
- Read-only view of tenant config: Current dollar rate, CBM rate, branding info, notification settings
- "Edit config" links that open the tenant's own config pages (admin view)

**Tab: Audit Log**
- Table of all audit events for this tenant: Action | Entity | Actor | Timestamp | Before/After (expandable)

#### Screen 2.5 — Platform Settings

**URL:** `/platform/settings`

- Two-panel layout:
  - Left: Settings nav (vertical list): General | Notification Providers | Maintenance | Plans & Limits
  
**General:**
- Platform name, support email, default currency display
- "Save Changes" button

**Notification Providers:**
- SMS gateway configuration (provider name, API key masked, from number)
- WhatsApp Business API config (phone number ID, access token masked)
- Test send button for each

**Maintenance:**
- Maintenance window toggle (with datetime range picker)
- Banner message text input

**Plans & Limits:**
- Table: Plan name | Max Users | Max Containers/Month | Max Storage | Price/Month | Edit
- "+ Add Plan" button

---

## Section 3 — Tenant Admin: Dashboard & User Management

> **Carry-forward context:** Design system from Section 0. Tenant Admin manages a single shipping company's portal. The sidebar shows the tenant's logo and company name at the top. Portal lives at `/admin/...`.

### Prompt

Design the **Tenant Admin portal** screens: dashboard, staff user management, and customer management.

#### Sidebar Navigation (Tenant Admin)

- Logo area: Tenant's own company logo (uploaded at onboarding) + company name in white
- Role badge: "ADMIN" in `primary-500`
- Nav sections:
  - **Overview:** Dashboard, Reports
  - **Operations:** Customers, Users (Staff)
  - **Configuration:** Company Settings, Dollar Rate, CBM Rate, Charge Types, Notification Templates
- Bottom: Avatar + user name + "Tenant Admin" + Logout

#### Screen 3.1 — Tenant Admin Dashboard

**URL:** `/admin/dashboard`

**Page header:** "Dashboard" + company name subtitle + "Good morning, {name}" greeting

**Stat row (4 cards):**
1. **Active Customers** — count, link to customers list
2. **Containers This Month** — count + "X in transit"
3. **Outstanding Billing** — NGN amount (sum of unpaid/partially-paid billing)
4. **Pending Claims** — count of open damage/missing item claims

**Two-column content area:**

**Left (65%):**
- Recent Containers table — columns: Container # | Status | Customers | Packing Lists | Billing Status | Actions
- Status badge for each container tracking stage

**Right (35%):**
- Notifications / Activity Feed — recent 10 events: customer registered, container arrived, billing generated, payment confirmed, claim filed
- "View full audit log" link at bottom

**Bottom row:**
- Staff Users card: list of 5 most recent logins + "Manage Users" link
- Quick actions: "Add Customer", "Create Container", "Generate Billing"

#### Screen 3.2 — Staff User List

**URL:** `/admin/users`

**Page header:** "Staff Users" + "Invite Staff Member" button (primary)

**Filter bar:** Search by name/email | Filter by Role (All | Tenant Admin | China Office Staff | Nigeria Office Staff | Warehouse Attendant) | Filter by Status (Active | Suspended)

**Users Table:**
- Columns: ☐ | Avatar+Name | Email | Role badge | Status badge | Last Login | Created | Actions
- Actions (three-dot menu): View Profile, Reset Password, Resend Invite, Edit Role, Deactivate
- Inactive/suspended rows: muted text + red badge

#### Screen 3.3 — Invite Staff Member (Modal)

Triggered by "Invite Staff Member" button. Design as a `md` modal:

- Heading: "Invite a Staff Member"
- Fields:
  - Full name (required)
  - Email address (required) — "An invite email will be sent to this address"
  - Role (dropdown): China Office Staff | Nigeria Office Staff | Warehouse Attendant | Tenant Admin
  - Helper text: description of selected role shown below dropdown
- Footer: Cancel + "Send Invite" (primary)

**Success state:** Modal replaces with: "Invite sent to {email}! They'll receive an email to set their password."

#### Screen 3.4 — Staff User Profile

**URL:** `/admin/users/:id`

**Breadcrumb:** Admin > Users > Amara Okafor

**Two-column layout:**

**Left — Profile Card:**
- Avatar (large, 80px) + name + role badge + status
- Email (non-editable, with info tooltip: "Email cannot be changed after account creation")
- Last login timestamp
- Account created date

**Right — Edit Panel:**
- Editable: Full name, Role dropdown
- "Save Changes" button (primary)
- Danger zone section (red border card):
  - "Deactivate this user" with warning text + Deactivate button (danger)
  - "Reset Password" — sends a password reset email

**Below — Activity tab:**
- Recent audit log entries for this user: actions performed, timestamps

#### Screen 3.5 — Customer List

**URL:** `/admin/customers`

**Page header:** "Customers" + "Add Customer" button

**Filter bar:** Search by name/email/phone | Status (Active | Anonymised)

**Customers Table:**
- Columns: ☐ | Name | Email | Phone | Registered | Last Shipment | Actions
- Anonymised customers: show "[ANONYMISED]" in name/email/phone cells with italic style
- Actions: View Profile, Edit, Export Data (GDPR), Anonymise (GDPR, danger)

**GDPR Banner (if any anonymised customers exist):**
- Blue info banner below filter bar: "X customers have been anonymised per GDPR requests. Their billing and shipment records are retained."

#### Screen 3.6 — Customer Profile

**URL:** `/admin/customers/:id`

**Breadcrumb:** Admin > Customers > Ngozi Okonkwo

**Page tabs:** Profile | Shipments | Billing | Claims | Data Export (GDPR)

**Tab: Profile**
- Two-column layout:
  - Left: Contact card (name, email, phone, whatsapp, address, contract details)
  - Right: Consent & GDPR card (consent given at, notification consent channels shown as chips, anonymised_at if applicable)
- Edit button (opens inline edit form for phone, address only; email non-editable)

**Tab: Shipments**
- Table of this customer's containers/tracking history
- Columns: Tracking Code | Container # | Status | Cartons | Total CBM | Last Updated

**Tab: Billing**
- Table of billing records for this customer
- Columns: Billing ID | Container | Total NGN | Status | Paid NGN | Outstanding | Billed At | Actions

**Tab: Claims**
- Table of damage claims, missing item reports, seized items
- Columns: Type badge (Damage/Missing/Seized) | Reference | Status | Filed At | Resolution

**Tab: Data Export (GDPR)**
- Info box: "Download all data held for this customer per GDPR Article 20 (Right to Data Portability)."
- "Generate Export" button — triggers download of a JSON bundle
- Danger zone: "Anonymise Customer Record" (irreversible — confirm dialog required)

---

## Section 4 — Tenant Admin: Configuration & Settings

> **Carry-forward context:** Design system from Section 0. Tenant Admin configuration screens let the company configure rates, branding, notification templates, and custom charge types. Lives at `/admin/config/...`.

### Prompt

Design the **Tenant Admin configuration screens**: company settings/branding, dollar rate management, CBM rate, charge types, and notification templates.

#### Screen 4.1 — Company Settings

**URL:** `/admin/config`

**Page header:** "Company Settings"

**Layout:** Two-column (left nav + right content). Left nav:
- General
- Dollar Rate
- CBM Rate
- Charge Types
- Notification Templates

**General (default active):**

Left column form:
- Company name (text input)
- Company logo (image upload with preview, accepts PNG/JPG/SVG, max 2MB)
- Warehouse address (textarea — shown on release notes)
- Support email (text input)

Right column — Preview card:
- "Live Preview" heading
- Shows how the logo + company name appears on a packing list header
- Shows how it appears on a release note

"Save Changes" button (primary, full-width, below form)

#### Screen 4.2 — Dollar Rate

**URL:** `/admin/config/dollar-rate`

**Page header:** "Dollar Exchange Rate" + subtitle "Configure the USD → NGN rate used for billing calculations."

**Current Rate Card:**
- Large display: "₦1,650 per $1 USD"
- Set by: "Amara Okafor on 15 Apr 2026 at 14:32"
- Badge: CURRENT

**Update Rate Form (inline card):**
- Label: "Set new rate"
- Input: number field with "₦" prefix, placeholder "1650.00"
- Currency pair: read-only "USD_NGN"
- Warning text: "Changing this rate will affect billing calculations for any new billing records created after this point. Existing records are not affected."
- Button: "Update Rate" (primary)

**Rate History Table** (below):
- Title: "Rate History"
- Columns: Rate (₦/USD) | Changed By | Date & Time | Reason (if stored)
- Last 20 entries, paginated
- Current rate highlighted with "CURRENT" badge in first row

**Filter:** rate_type dropdown (dollar_rate | cbm_rate — same page for both in some implementations, keep as separate pages here)

#### Screen 4.3 — CBM Rate

**URL:** `/admin/config/cbm-rate`

Same layout as Dollar Rate screen but for CBM pricing:

- Current Rate Card: "**$48.00** per CBM" (USD)
- Update form: number input with "$" prefix
- Note: "This rate determines the base shipping cost per cubic meter. It is multiplied by the dollar rate to arrive at the NGN amount per CBM for billing."
- Rate history table

#### Screen 4.4 — Charge Types

**URL:** `/admin/config/charge-types`

**Page header:** "Custom Charge Types" + "Add Charge Type" button

**Explanation banner (info):** "Define your company's miscellaneous charge categories (e.g., Customs Examination, Port Handling). These appear as options when adding charges to a billing record."

**Charge Types Table:**
- Columns: Name | Default Amount (NGN) | Description | Status | Actions
- Status: Active (green) / Inactive (gray)
- Actions: Edit (opens modal), Deactivate

**Add/Edit Charge Type Modal:**
- Fields: Name (required), Description (optional, textarea), Default Amount NGN (number)
- Footer: Cancel + "Save Charge Type"

#### Screen 4.5 — Notification Templates

**URL:** `/admin/config/notifications`

**Page header:** "Notification Templates & Preferences"

**Two-section layout:**

**Section A — Channel Preferences:**
- Card title: "Enabled Channels"
- Toggle switches: SMS | WhatsApp | Email (with explanatory text per channel)
- Current status shown (enabled/disabled)

**Section B — Event Templates:**
- List of notification events, each as a card:
  - **Payment Notification** — "Sent when billing is generated"
  - **Shipment Status Update** — "Sent on each tracking stage change"
  - **Release Note Issued** — "Sent when goods are ready for pickup"
  - **Claim Filed** — "Sent when a damage claim is logged"
- Each event card shows:
  - Toggle (enable/disable this event's notifications)
  - Per-channel template (tabs: SMS | WhatsApp | Email)
  - Template text editor with variable chips: `{customer_name}`, `{container_number}`, `{amount_ngn}`, `{tracking_code}`, `{warehouse_address}`
  - Character count (important for SMS 160-char limit)
  - "Save Template" button per event

**Preview panel (right side, 30%):**
- Shows rendered preview of the active template with sample data filled in

---

## Section 5 — China Office Staff: Packing Lists & Containers

> **Carry-forward context:** Design system from Section 0. China Office Staff create packing lists for customer cargo loaded into containers. They also manage container creation. Sidebar role badge shows "China Office" in indigo. Portal is role-filtered — they see the same app as Nigeria Office but with different permissions.

### Prompt

Design the **China Office Staff** screens: container management, packing list creation, packing list detail, and bulk actions.

#### Sidebar Navigation (China Office Staff)

- Company logo + name
- Role badge: "CHINA OFFICE" in indigo
- Nav:
  - **Containers:** All Containers, Create Container
  - **Packing Lists:** All Packing Lists, Create Packing List
  - **Manifests:** View Manifests
  - **Disputes:** CBM Disputes (badge with count)
- Bottom: Avatar + name + logout

#### Screen 5.1 — Container List

**URL:** `/containers`

**Page header:** "Containers" + "Create Container" button (primary)

**Filter bar:**
- Status filter chips: All | Draft/Active | In Transit | Arrived | Cleared | Picked Up
- Search: "Container number, vessel..."
- Date range picker

**Containers Table:**
- Columns: Container # | Vessel Name | Origin Port | Destination Port | Status | Packing Lists | Expected Arrival | Actions
- Status: color-coded badge (each stage of: `active`, `in_transit`, `arrived_nigeria`, `customs_clearance`, `cleared`, `ready_for_pickup`, `completed`)
- Row click → Container detail
- Actions: View, Update Status (if Nigeria Office), Export Manifest

**Empty state:** "No containers yet. Create your first container to get started."

#### Screen 5.2 — Create Container

**URL:** `/containers/new`

**Page header:** "Create New Container" — Breadcrumb: Containers > New

**Form layout (single column, 600px max-width, centered card):**

- Container number (text input, required, monospace font)
- Vessel name (text input)
- Origin port (dropdown: Guangzhou | Shanghai | Shenzhen | Ningbo | Other)
- Destination port (dropdown: Apapa, Lagos | Tin Can Island | Other)
- Expected arrival date (date picker)

Footer: Cancel + "Create Container" (primary)

**Success state:** Navigate to the new container detail page with a green toast: "Container MSCU1234567 created."

#### Screen 5.3 — Container Detail

**URL:** `/containers/:id`

**Breadcrumb:** Containers > MSCU1234567

**Page header:**
- Container number in `display-md` monospace
- Status badge (current tracking stage)
- Vessel name + origin→destination ports in subtext

**Action buttons (top right):**
- "Add Packing List" (primary)
- "View Manifest" (secondary)
- "Export" (ghost, dropdown: Excel | PDF)
- Status update dropdown (Nigeria Office only): "Update Status" → stage selector

**Page tabs:** Overview | Packing Lists | Manifest | Documents | Tracking Events

**Tab: Overview**

Two-column layout:
- Left: Container info card (container #, vessel, ports, expected arrival, created by, created at)
- Right: Cargo summary card (total customers, total cartons, total CBM, total weight)

Tracking timeline (full-width below):
- Horizontal stepper or vertical timeline showing all stages
- Completed stages: filled `success-500` green dot + stage name + completion date/time
- Current stage: pulsing `primary-500` Odum Green dot
- Future stages: gray outline dot (`neutral-300`)

**Tab: Packing Lists**
- Table: Packing List ID | Customer Name | Cartons | Total CBM | Status | Submitted At | Actions
- Status: draft | pending_approval | approved | rejected
- Actions: View, Approve (if has permission), Reject
- Bulk action bar (when rows selected): "Bulk Approve" | "Bulk Reject" buttons

**Tab: Manifest**
- Manifest overview card: verification status badge + created date
- Customer summary table: Customer | Cartons | Total CBM | Total Weight | Packing List Status | Actions
- "Verify Manifest" button (shows discrepancy form if needed)

**Tab: Documents**
- List of uploaded documents (PDFs, photos)
- "Upload Document" button → file picker modal with type dropdown (Bill of Lading, Customs Form, Other)
- Each document: icon + filename + uploaded by + date + download button

**Tab: Tracking Events**
- Reverse-chronological timeline of all status change events
- Each event: event type icon + description + "Updated by {user}" + timestamp

#### Screen 5.4 — Create Packing List

**URL:** `/packing-lists/new`

**Breadcrumb:** Packing Lists > New

**Page header:** "Create Packing List"

**Step indicator (3 steps):** ① Details → ② Items → ③ Review & Submit

**Step 1 — Details:**
- Customer (searchable dropdown — search customers by name/phone)
- Container (searchable dropdown — search containers by number, shows only active containers)
- "Next →" button

**Step 2 — Items:**

Heading: "Add Carton Items" + item count badge

**Items table (editable, each row is a carton):**
- Columns: Carton Tag (auto-generated, e.g. SHX-00001, editable) | Description | Weight Dispatch (kg) | Weight Actual (kg) | L × W × H (cm) | CBM (auto-calculated, shown in blue) | Received Date | Declared Value (USD)
- Each row is fully editable inline
- "+ Add Item" button at bottom adds a new row
- Trash icon to remove a row
- Running total bar at bottom: "Total Cartons: 4 | Total CBM: 0.56 | Total Weight: 45.2 kg"

**Step 3 — Review & Submit:**
- Summary card: Customer name, Container, item count, total CBM
- Preview of the packing list (styled like a printable document)
- Two buttons: "Save as Draft" (secondary) + "Submit for Approval" (primary, accent-500)

#### Screen 5.5 — Packing List Detail

**URL:** `/packing-lists/:id`

**Breadcrumb:** Packing Lists > PL-20260415-001

**Page header:**
- Packing List reference in `display-md`
- Status badge
- Customer name + Container number in subtext

**Action buttons (context-dependent by status and role):**
- Draft: "Edit" (primary), "Submit for Approval" (accent)
- Pending Approval (if Tenant Admin/Reviewer): "Approve" (success), "Reject" (danger)
- Approved: "Export PDF" (ghost), "Export Excel" (ghost)
- Rejected: "Edit & Resubmit" (primary, with rejection comment shown)

**Items Table:**
- All carton items with columns: Tag | Description | Dispatch Weight | Actual Weight | CBM | Received Date | Declared Value
- Footer row: totals in bold

**Rejection Comments panel** (if status = rejected):
- Red-bordered card: "Rejection Reason: [comment from reviewer]" + item-level rejection notes if any
- Per-item: red badge on rejected items with reason tooltip

**Print view:** Dedicated "Print" button — renders a clean black-and-white printable layout with company logo at top.

#### Screen 5.6 — Packing List List

**URL:** `/packing-lists`

**Page header:** "Packing Lists" + "Create Packing List" button

**Filter bar:** Status (All | Draft | Pending Approval | Approved | Rejected) | Container filter | Customer filter | Date range

**Table:**
- Columns: Ref # | Customer | Container | Cartons | Total CBM | Status | Submitted | Actions
- Row click → Packing List detail
- Bulk selection → "Bulk Approve" / "Bulk Reject" contextual action bar appears at top when 2+ selected

**Bulk Reject Modal:**
- Heading: "Reject Selected Packing Lists"
- "You are rejecting X packing lists."
- Textarea: "Rejection comments" (required, applies to all selected)
- Footer: Cancel + "Confirm Rejection" (danger)

---

## Section 6 — Nigeria Office Staff: Operations Dashboard & Manifests

> **Carry-forward context:** Design system from Section 0. Nigeria Office Staff handle the Nigeria-side operations: receiving containers, verifying manifests, managing customs clearance, tracking updates, distributing packing lists to customers. Sidebar role badge: "Nigeria Office" in `accent-500` kola copper (the earth-toned, culturally-rooted accent — see Role-Based Theme Accents in Section 0).

### Prompt

Design the **Nigeria Office Staff** operations screens: operations dashboard, manifest management, and tracking status updates.

#### Sidebar Navigation (Nigeria Office Staff)

- Company logo + name
- Role badge: "NIGERIA OFFICE" in `success-500`
- Nav:
  - **Dashboard**
  - **Containers:** All Containers, Tracking Updates
  - **Manifests:** All Manifests
  - **Packing Lists:** Packing List Distribution
  - **Billing:** Billing Management, Carryovers, CBM Disputes
  - **Claims:** Damage Claims, Missing Items, Seized Items
  - **Release:** Release Notes
  - **Refunds:** Refund Requests
- Bottom: Avatar + name + logout

#### Screen 6.1 — Nigeria Office Dashboard

**URL:** `/dashboard`

**Page header:** "Operations Dashboard" + "Today, {date}"

**Urgent Actions panel (top, amber background):**
- Only shown when there are items needing attention
- "3 containers arrived — manifests need verification" → "Go to Manifests"
- "5 packing lists pending approval" → "Go to Packing Lists"
- "2 CBM disputes need response" → "Go to Disputes"

**Stat row (4 cards):**
1. **Containers at Customs** — count with breakdown badge (e.g. "2 delayed")
2. **Awaiting Payment** — NGN total outstanding across all customers
3. **Open Claims** — count with type breakdown (damage | missing | seized)
4. **Ready for Pickup** — count of release notes issued, not yet picked up

**Container Status Pipeline (horizontal flow):**
- Kanban-style horizontal pipeline with columns for each tracking stage
- Each column shows count of containers at that stage
- Mini-card per container: container number, arrival date, # customers
- Click → Container detail

**Two-column below:**
- Left: Recent Payments table (customer | amount | container | confirmed at)
- Right: Incoming Containers (next 5 expected arrivals with expected date countdown)

#### Screen 6.2 — Manifest List

**URL:** `/manifests`

**Page header:** "Manifests"

**Filter bar:** Status (All | Pending | Verified | Discrepancies Found | Resolved) | Container filter | Date range

**Manifest Table:**
- Columns: Manifest ID | Container # | Customers | Total Cartons | Total CBM | Verification Status | Created | Actions
- Actions: View, Verify Manifest (if pending), Resolve Discrepancy (if discrepancies_found)

#### Screen 6.3 — Manifest Detail

**URL:** `/manifests/:id`

**Breadcrumb:** Manifests > MF-20260415-001

**Page header:**
- Manifest reference
- Container number link
- Verification status badge
- "Verify Manifest" button (primary, shown if status = pending)
- "Resolve Discrepancy" button (warning, shown if status = discrepancies_found)

**Manifest Summary Card:**
- Total customers | Total cartons | Total CBM | Total weight | Container | Created date

**Customer Summary Table:**
- Columns: Customer Name | Cartons | Total CBM | Total Weight | Carton Tags (pill list, max 5 shown + "+N more") | Packing List Status | Actions
- Actions: View Packing List, Print Customer Packing List

**Verify Manifest Modal:**
- Triggered by "Verify Manifest" button
- Heading: "Verify Manifest MF-20260415-001"
- Verification status radio: "✓ Verified — All items present" | "⚠ Discrepancies Found"
- If discrepancies: show a dynamic form to add discrepancy records:
  - Customer (dropdown)
  - Carton tags affected (multi-input with tag chips)
  - Type (Missing | Damaged)
  - Notes (textarea)
  - "+ Add another discrepancy" link
- Footer: Cancel + "Submit Verification" (primary)

**Discrepancy Log section** (shown after verification with discrepancies):
- List of logged discrepancies with resolution status

**Resolve Discrepancy Modal:**
- "Resolution notes" textarea (required)
- Optional "Final counts" — table of customer → carton count adjustments
- "Mark as Resolved" (primary)

#### Screen 6.4 — Update Container Status

**URL:** `/containers/:id` (Tracking tab, or dedicated status update modal)

**Status Update Modal** (triggered from container detail or dashboard pipeline card):
- Heading: "Update Container Status"
- Current status display (read-only badge)
- New status dropdown: sequential stages only — can't skip
- Notes field (optional)
- Footer: Cancel + "Update Status" (primary)

**Confirmation dialog for critical stages** (e.g. marking "Cleared" or "Ready for Pickup"):
- "This will trigger payment notification SMS/WhatsApp to all customers in this container. Proceed?"
- Cancel + "Yes, Update & Notify" (accent)

---

## Section 7 — Nigeria Office Staff: Billing Management

> **Carry-forward context:** Design system from Section 0. Billing is CBM-based (total CBM × CBM rate × dollar rate = NGN amount). Nigeria Office Staff generate and manage billing records. Statuses: unpaid, partially_paid, paid, overpaid, waived, released_with_outstanding.

### Prompt

Design the **Billing Management** screens for Nigeria Office Staff: billing list, billing detail, charge management, CBM disputes, and carryovers.

#### Screen 7.1 — Billing List

**URL:** `/billing`

**Page header:** "Billing" + "Generate Billing" button (primary, for selected container)

**Filter bar:** Status (All | Unpaid | Partially Paid | Paid | Overpaid | Waived | Released w/ Outstanding) | Customer filter | Container filter | Date range

**Summary strip (below filter bar):**
- "Total Outstanding: ₦X,XXX,XXX" | "Total Paid (this month): ₦X,XXX,XXX" | "Total Overdue (>30d): ₦X,XXX"

**Billing Table:**
- Columns: Customer Name | Container # | Total CBM | CBM Rate ($/CBM) | Subtotal USD | Dollar Rate | Subtotal NGN | Misc Fees | Total NGN | Paid | Outstanding | Status | Billed At | Actions
- Status badge with color
- Outstanding column: red text if > 0, green if = 0
- Actions: View Detail, Record Payment, Generate Release Note (if paid/partial), Cancel

#### Screen 7.2 — Billing Detail

**URL:** `/billing/:id`

**Breadcrumb:** Billing > BL-20260415-001

**Page header:**
- Customer name link
- Container number link
- Status badge
- Action buttons (context by status):
  - Unpaid/Partially Paid: "Record Payment" (accent) | "Add Charge" (secondary) | "Cancel" (danger ghost)
  - Paid: "Generate Release Note" (accent) | "Export Invoice" (ghost)
  - Waived: read-only

**Billing Breakdown Card:**
- Line items table:
  | Line Item | Amount |
  |---|---|
  | CBM Calculation: X.XX CBM × $XX/CBM × ₦X,XXX | ₦XXX,XXX |
  | Misc Fee: Customs Examination | ₦XX,XXX |
  | Misc Fee: Port Handling | ₦XX,XXX |
  | Carryover from Previous | ₦X,XXX |
  | Adjustment | -₦X,XXX |
  | **Total Due** | **₦XXX,XXX** |
  | Total Paid | ₦XX,XXX |
  | **Outstanding** | **₦XX,XXX** |
- CBM detail expandable: shows original CBM, corrected CBM (if dispute resolved), rate breakdown

**Payment History section:**
- Table: Payment ID | Amount (NGN) | Method | Reference | Confirmed By | Confirmed At
- "Record Payment" button opens modal

**Record Payment Modal:**
- Amount NGN (number input, pre-filled with outstanding amount)
- Payment method (dropdown: Bank Transfer | Cash | Gateway)
- Payment reference (text input)
- Footer: Cancel + "Confirm Payment" (accent)

**Misc Charges section:**
- Table of added charges: Description | Amount NGN | Added By | Added At | Delete
- "+ Add Charge" button → opens modal:
  - Charge type (dropdown from tenant's configured charge types)
  - Custom description (optional override)
  - Amount NGN (number, pre-filled with default_amount_ngn)

**CBM Dispute section:**
- If no dispute: "No disputes filed" + "File CBM Dispute" button (customer-facing)
- If dispute exists: dispute status badge + original CBM + customer-measured CBM + dispute reason + resolution flow

**Carryover section:**
- Shows active carryovers applied to this billing
- "Exempt Carryover" button if carryover applies (with notes input)

#### Screen 7.3 — CBM Disputes

**URL:** `/billing/disputes`

**Page header:** "CBM Disputes"

**Filter bar:** Status (All | Submitted | Acknowledged | Investigating | Escalated to China | Resolved — Adjusted | Resolved — No Change | Closed)

**Disputes Table:**
- Columns: Dispute ID | Customer | Container | Original CBM | Customer's CBM | Status | Filed At | Actions
- Actions: View, Acknowledge, Escalate to China, Resolve, Reject

**Dispute Detail (opens as side panel or modal):**
- Original CBM vs customer-claimed CBM side by side
- Dispute reason text
- Status timeline (submitted → acknowledged → investigating → resolved)
- Action buttons per stage:
  - Submitted: "Acknowledge" (moves to acknowledged)
  - Acknowledged: "Begin Investigation" | "Escalate to China Office"
  - Investigating: "Resolve — Adjusted" | "Resolve — No Change" | "Reject"
- Resolve Modal: status dropdown (resolved_adjusted | resolved_no_change) + corrected CBM (if adjusted) + resolution notes

#### Screen 7.4 — Carryovers

**URL:** `/billing/carryovers`

**Page header:** "Carryover Ledger"

**Info banner:** "Carryovers are outstanding balances from previous billing cycles automatically applied to the customer's next billing record."

**Carryovers Table:**
- Columns: Customer | Original Billing | Carryover Amount | Applied To | Status (Active / Exempted) | Created | Notes | Actions
- Actions: Exempt (if active) — opens modal with optional notes field

---

## Section 8 — Nigeria Office Staff: Claims & Refunds

> **Carry-forward context:** Design system from Section 0. Claims covers three types: Damage Claims (filed by customers, investigated by Nigeria Office), Missing Items (cargo not in container), and Seized Items (customs-seized cartons). Refunds flow: Create → Accounts Review → Approve/Reject.

### Prompt

Design the **Claims and Refunds** screens for Nigeria Office Staff.

#### Screen 8.1 — Damage Claims List

**URL:** `/claims`

**Page header:** "Damage Claims" + "Log Claim" button

**Filter bar:** Status (All | Filed | Under Inspection | Inspection Complete | Pending Resolution | Resolved | Closed) | Customer filter | Date range

**Claims Table:**
- Columns: Claim ID | Customer | Container | Cartons Affected | Status | Inspection Method badge | Filed At | Actions
- Inspection Method badge: "Delegate Visit" (blue) | "Customer Evidence" (gray)
- Actions: View Detail, Start Inspection (if filed), Resolve (if inspection complete)

#### Screen 8.2 — Damage Claim Detail

**URL:** `/claims/:id`

**Breadcrumb:** Claims > DC-20260415-001

**Page header:**
- Claim reference
- Customer name link
- Status badge
- Action buttons by status:
  - Filed: "Start Inspection" (primary)
  - Under Inspection: "Complete Inspection" → goes to resolution
  - Inspection Complete: "Resolve Claim" (accent)

**Claim Info Card:**
- Container | Cartons affected (list of carton tags) | Description | Filed At | Filed By

**Evidence panel:**
- Photo gallery (grid of uploaded photos, click to expand lightbox)
- "Upload Evidence" button (if under inspection)

**Inspection section:**
- Inspection method badge
- Start inspection button opens modal: Method selection (Delegate Visit | Customer Evidence)

**Resolution section:**
- "Resolve Claim" button opens modal:
  - Resolution type (radio): Refund | Discount | No Action | Compensation
  - Amount USD (shown if Refund or Compensation)
  - Settlement amount USD (alternate label for Compensation)
  - Amount NGN (shown if Refund)
  - Discount percentage (shown if Discount, 0–100%)
  - Reason (textarea, required)
  - Notes (textarea, optional)
  - Footer: Cancel + "Confirm Resolution" (primary)
- After resolution: Resolution summary card (resolution type badge + amount + reason)

**Activity Timeline:** All status changes with actor + timestamp

#### Screen 8.3 — Missing Items

**URL:** `/claims/missing-items`

**Page header:** "Missing Items" + "Log Missing Item" button

**Filter bar:** Status | Container filter | Customer filter

**Table:**
- Columns: Item ID | Customer | Container | Manifest | Carton Tags | Status | Reported At | Actions
- Status badges: reported | investigating | found_and_shipping | confirmed_lost | resolved
- Actions: View, Update Status

**Log Missing Item Modal:**
- Manifest (dropdown, required)
- Customer (dropdown filtered by manifest)
- Carton tags (multi-input with tag chips)
- Description (textarea, required)
- Footer: Cancel + "Log Missing Item" (primary)

**Update Status Modal** (for existing items):
- Current status displayed
- New status dropdown
- Notes textarea
- Refund amount NGN (optional, if confirmed_lost and triggering refund)

#### Screen 8.4 — Seized Items

**URL:** `/claims/seized-items`

**Page header:** "Seized Items (Customs)" + "Log Seizure" button

**Filter bar:** Status | Container filter | Customer filter

**Table:**
- Columns: Item ID | Customer | Container | Carton Tags | Seizure Reason | Recovery Status | Reported At | Actions
- Recovery Status badges: seized | recovery_in_progress | recovered | permanently_lost
- Actions: View, Update Recovery Status

**Log Seizure Modal:**
- Container (dropdown)
- Customer (dropdown)
- Carton tags (multi-input)
- Reason (textarea, required)

**Update Recovery Status Modal:**
- Current status
- New recovery status dropdown
- Notes
- Refund amount NGN (optional)

#### Screen 8.5 — Refund Requests List

**URL:** `/refunds`

**Page header:** "Refund Requests"

**Filter bar:** Status (All | Pending Review | Accounts Reviewed | Pending Approval | Approved | Rejected | Processed | Applied as Credit) | Customer filter | Type filter (Overpayment | CBM Correction | Damage or Loss) | Date range

**Summary strip:** "Total Pending: ₦X,XXX,XXX | Total Approved (this month): ₦X,XXX,XXX"

**Refunds Table:**
- Columns: Ref ID | Customer | Type badge | Requested NGN | Approved NGN | Customer Choice | Status | Filed At | Actions
- Type badges: Overpayment (blue) | CBM Correction (indigo) | Damage/Loss (red)
- Customer Choice: "Immediate Refund" | "Apply as Credit"
- Actions: View, Accounts Review (if pending_review), Approve/Reject (if accounts_reviewed)

#### Screen 8.6 — Refund Detail

**URL:** `/refunds/:id`

**Breadcrumb:** Refunds > RF-20260415-001

**Refund Info Card:**
- Customer | Type | Amount Requested | Billing Reference | Damage Claim Reference | Notes | Filed At

**Status workflow panel:**
- Visual stepper: Pending Review → Accounts Review → Pending Approval → Approved/Rejected
- Current step highlighted

**Accounts Review section** (shown when status = pending_review):
- "Perform Accounts Review" button → opens form:
  - Debt Check Passed (toggle: Yes / No)
  - Debt Check Notes (textarea, required)
  - "Submit Review" button

**Approval section** (shown when status = accounts_reviewed or pending_approval):
- "Approve Refund" button (success) → modal:
  - Amount Approved NGN (number, pre-filled with requested amount)
  - Approval Level (text, e.g. "manager", "head_of_finance")
  - "Confirm Approval" button
- "Reject Refund" button (danger) → modal:
  - Reason (textarea, required)
  - "Confirm Rejection" button

**Resolution section** (shown when resolved):
- Approved amount | Approval level | Resolved by | Resolved at
- Customer choice: "Immediate Refund — ₦XX,XXX to account ending ***1234" or "Applied as credit to next billing"

---

## Section 9 — Payment & Release Notes

> **Carry-forward context:** Design system from Section 0. After billing is confirmed paid (fully or partially), a Release Note is generated — this is the authorization document for warehouse pickup. Warehouse Attendants use release notes to verify and record pickup. Release notes can be split for partial collection.

### Prompt

Design the **Payment & Release Notes** screens for Nigeria Office Staff and Warehouse Attendants.

#### Screen 9.1 — Release Notes List

**URL:** `/release-notes`

**Page header:** "Release Notes"

**Filter bar:** Status (All | Active | Picked Up | Expired | Cancelled) | Customer filter | Container filter | Date range

**Release Notes Table:**
- Columns: Reference # | Customer | Container | Cartons | Payment Status badge | Release Status badge | Is Partial | Authorized At | Actions
- Reference # in monospace font
- Actions: View, Record Pickup (if active, for warehouse attendant), Split (if active + partial allowed)

#### Screen 9.2 — Release Note Detail

**URL:** `/release-notes/:id`

**Breadcrumb:** Release Notes > RN-ABC123

**Page header:**
- Reference number in `display-md` monospace
- Status badge
- Print button (ghost) — generates clean printable release note

**Release Note Card (printable layout preview):**
- Company header (logo + company name)
- --- 
- RELEASE NOTE
- Reference: RN-ABC123
- Date of Authorization: 15 Apr 2026
- ---
- Customer Name: Ngozi Okonkwo
- Container: MSCU1234567
- Total Cartons: 4
- Carton Tags: SHX-00001, SHX-00002, SHX-00003, SHX-00004
- Warehouse Address: {tenant warehouse address}
- Payment Status: PAID
- ---
- Authorized by: Amara Okafor (Nigeria Office Staff)

**Actions (below card):**
- Active: "Record Pickup" (accent, large) | "Split Release Note" (secondary)
- Picked Up: disabled/read-only badge

**Split Release Note Modal:**
- Heading: "Split Release Note"
- Info: "Select which carton tags the customer is collecting now. The remaining cartons will be on a new release note."
- Carton tag selector: checkbox list of all carton tags on this note
- Notes (optional textarea)
- Footer: Cancel + "Split & Generate New Note" (primary)

**Record Pickup (Record Pickup Modal):**
- Heading: "Record Pickup"
- Cartons Released (number input, default = total cartons on note)
- Is Delegate? toggle (Yes/No)
- If Yes: delegate fields appear:
  - Delegate Name
  - Delegate Phone
  - ID Type (dropdown: National ID | Driver's License | Passport)
  - ID Number (text input)
- Notes (optional)
- Footer: Cancel + "Confirm Pickup" (accent)

**After pickup — Pickup Record section:**
- Pickup date | Time | Attendant | Cartons released | Delegate info (if applicable)
- Remaining cartons counter (if partial pickup)

#### Screen 9.3 — Warehouse Attendant View

**URL:** `/release-notes` (same URL, different view based on role)

**Warehouse Attendant sees a simplified view:**

**Page header:** "Pickup Queue" — "Scan or enter release note reference"

**Search bar (prominent, full-width):** Large input + "Look Up" button (accent, large)
- "Enter release note reference number (e.g. RN-ABC123)"

**Queue Table:**
- Shows only active (not-yet-picked-up) release notes assigned for pickup today
- Columns: Reference # | Customer Name | Container | Cartons | Authorized At | Action
- Action: "Record Pickup" button (green) per row

---

## Section 10 — Customer Portal

> **Carry-forward context:** Design system from Section 0. Customers are the end-users of the shipping company — they see a simplified portal showing only their own shipments, billing, and claims. No sidebar operational features. Mobile-first design is critical for this role.

### Prompt

Design the **Customer Portal** screens: shipment tracking, billing/payments, claims, and account.

#### Customer Portal Layout

**No sidebar** — use a **top navigation bar** instead:

Top nav:
- Left: ShipX logo + tenant company name (customer is aware they're using "Acme Logistics powered by ShipX")
- Center: Nav links: My Shipments | Billing | Claims | Account
- Right: Notification bell + Avatar dropdown (My Account | Logout)

**Mobile:** Bottom tab bar: Shipments (home) | Billing | Claims | Account

**Hero color:** `primary-700` top nav for customer portal (differentiated from staff portals).

#### Screen 10.1 — My Shipments (Customer Homepage)

**URL:** `/my-shipments`

**Page header:** "My Shipments" — "Hello, Ngozi 👋"

**Active Shipment Card(s) (top, featured):**
- Large card per in-progress shipment
- Container number
- Tracking stage: visual horizontal stepper (Received → Packed → In Transit → Arrived → Customs → Cleared → Ready → Picked Up)
- Current stage highlighted in accent color with pulsing dot
- Cartons: X | CBM: X.XX | Total Cost: ₦XXX,XXX
- "View Details" button

**Past Shipments table (below):**
- Columns: Container | Tracking Code | Status | Cartons | Billed At | Amount | Actions
- "Picked Up" status in green
- Pagination

**Empty state (no shipments):** "No shipments yet. Your packages will appear here once they're registered by your shipping company."

#### Screen 10.2 — Shipment Detail (Customer)

**URL:** `/my-shipments/:tracking_code`

**Back link:** "← My Shipments"

**Tracking Card:**
- Tracking code in `mono` font
- Container number
- Horizontal stepper (or vertical on mobile) — all 8 stages, current stage shown with green pulsing dot
- Last updated: "5 hours ago"

**My Cartons section:**
- Table: Carton Tag | Description | Weight (kg) | CBM | Received Date

**Billing summary (if billing generated):**
- Cost breakdown card (CBM cost + misc fees + total)
- Payment status badge
- "View Full Billing" link

**Damage claims section:**
- Shows any damage claims for this shipment
- "File a Claim" button (shown if shipment is arrived or later stage)

**Documents section:**
- Download Packing List (PDF)
- Download Release Note (PDF, if generated)

#### Screen 10.3 — Billing (Customer)

**URL:** `/my-billing`

**Page header:** "My Billing"

**Outstanding Alert (if any unpaid):**
- Amber banner: "You have ₦XXX,XXX outstanding across X containers. Pay now to receive your goods."

**Billing Cards (not table — card layout for mobile-friendliness):**
Each billing record shown as a card:
- Container # | Billed date
- Total: ₦XXX,XXX
- Paid: ₦XX,XXX | Outstanding: ₦XX,XXX
- Status badge
- "View Details" link

**Paid records (collapsed section, expandable):** "X completed billing records" accordion

#### Screen 10.4 — Billing Detail (Customer)

**URL:** `/my-billing/:id`

**Back link:** "← Billing"

**Billing Breakdown Card:**
- Same line-item table as staff view but simplified labels
- No CBM rate internals if business rules dictate hiding

**Payment Status Card:**
- Status badge + "How to pay" instruction section (tenant-configured)
- "I've made a payment" button → opens "Payment Confirmation Request" form (if manual payment):
  - Amount NGN paid
  - Bank/transfer reference
  - Optional notes
  - Submit → "Thank you! Our team will confirm your payment shortly."

**CBM Dispute section:**
- "I believe my CBM measurement is incorrect" → "File a CBM Dispute" link/button
- Opens dispute modal: reason (textarea) + their measured CBM (number input)
- After filing: dispute status tracking shown in a card

#### Screen 10.5 — Claims (Customer)

**URL:** `/my-claims`

**Page header:** "My Claims"

**"File a Claim" button (accent, top right)**

**Claims list:**
- Card layout (not table, mobile-friendly)
- Each card: Claim type badge (Damage) | Container | Status | Filed date | "View" button

#### Screen 10.6 — File a Damage Claim (Customer)

**URL:** `/my-claims/new`

**Back link:** "← My Claims"

**Step 1 — Claim Details:**
- Shipment (dropdown — customer's containers that are in Nigeria)
- Affected carton tags (multi-select from their cartons, or free-text)
- Description of damage (textarea, required, min 20 characters)

**Step 2 — Evidence Upload:**
- Heading: "Upload Photos of Damage"
- Drag-and-drop upload zone + file picker
- Accepted: JPG, PNG (max 10MB each, up to 10 photos)
- Thumbnail preview grid with remove button on each

**Step 3 — Review & Submit:**
- Summary card
- "Submit Claim" button

#### Screen 10.7 — Account (Customer)

**URL:** `/account`

**Page tabs:** Profile | Notifications | Privacy

**Tab: Profile**
- View-only: Name, Email (non-editable), Phone, WhatsApp
- Editable: Address, WhatsApp number (optional field)
- "Update" button

**Tab: Notifications**
- "How would you like to receive updates?"
- Toggle per channel: SMS | WhatsApp | Email
- "Save Preferences"

**Tab: Privacy**
- Consent given on: {date}
- "Request my data" (GDPR export) — "We'll email you a copy of all data we hold for you."
- "Delete my account" (GDPR right to erasure) — danger button, confirmation dialog: "This will anonymise your personal data. Your billing and shipment records will be retained for legal purposes. This cannot be undone."

---

## Section 11 — Public Shipment Tracker

> **Carry-forward context:** Design system from Section 0. The public tracker requires no login — customers can look up their shipment by tracking code. This is a marketing/trust page that could be embedded on the shipping company's website.

### Prompt

Design the **Public Shipment Tracker** — a single page with no authentication required.

#### Screen 11.1 — Public Tracker

**URL:** `/track` or `/track/:code`

**Layout:** Full-width, no sidebar. Minimal top nav: ShipX logo lockup with small "by Odum" co-brand mark (left) + company name + "Sign in" link (right).

**Hero section:**
- Gradient background (`primary-900` Odum Dark Green → `primary-700` deep green)
- Subtle background pattern: scattered geometric beveled-corner cargo cubes at low opacity (echoes the Odum logomark vocabulary — three-faceted forms tied to the kola-nut symbolism). Renders in `primary-800` over the gradient.
- Heading: **"Track Your Shipment"** (`display-lg` Averta Bold, white)
- Subheading: "Enter your tracking code to see the latest status of your cargo." (`body-lg` Kumbh Regular, `primary-100` for soft contrast)
- Large search input (white, full-width up to 500px, 56px tall) + "Track" button (`accent-500` kola copper, `lg` size)
- Example: "e.g. SHX-2026-NGOZI-001" (placeholder text in `neutral-500` mono)

**Results section (appears below hero after search):**

**If found:**
- White card with shadow:
  - Tracking code + customer name (first name only)
  - Container number
  - Horizontal stage stepper (all 8 stages, current highlighted in green with checkmark)
  - "Last updated: X hours ago" + "By: Nigeria Office"
  - Estimated pickup window (if tracking stage is "Cleared" or later)
- Prompt: "Know more details? Sign in to your account →"

**If not found:**
- "No shipment found for '{code}'." + "Check your tracking code and try again." + "Contact your shipping company" link

**Mobile:** Full-screen white card below hero, stage stepper becomes vertical.

---

## Section 12 — Shared Patterns, Modals & Edge Cases

> **Carry-forward context:** Design system from Section 0. This section covers patterns used across all portals that haven't been explicitly shown yet.

### Prompt

Design the following **shared UI patterns** used across all portals:

#### Pattern 12.1 — Confirmation Dialogs (Destructive Actions)

Design the confirmation modal for irreversible actions:

**Suspend Tenant:**
- Red icon (warning triangle)
- Heading: "Suspend Acme Logistics?"
- Body: "This will immediately revoke access for all 12 users at Acme Logistics. Their data will be preserved. You can reactivate them at any time."
- Footer: "Cancel" (ghost) + "Yes, Suspend Tenant" (danger, filled)

**Anonymise Customer (GDPR):**
- Red icon
- Heading: "Anonymise Ngozi Okonkwo?"
- Body: "This will permanently remove all personal details (name, email, phone, address). Billing and shipment records will be retained. **This cannot be undone.**"
- Input: Type "ANONYMISE" to confirm (text field must match exactly)
- "Confirm Anonymisation" (danger) — disabled until input matches

**Cancel Billing:**
- Heading: "Cancel this billing record?"
- Body: "Reason (required)" — textarea
- "Confirm Cancellation" (danger)

#### Pattern 12.2 — Bulk Action Bar

When rows are selected in any table, show a **sticky action bar** at the bottom of the viewport:

- Dark bar (`neutral-900` background, 60px height)
- Left: checkbox count "3 items selected" + "Clear selection" link
- Right: context-appropriate action buttons (white text, outlined)
- Example for packing lists: "Bulk Approve (3)" (green) + "Bulk Reject (3)" (red)
- Slides up from bottom when selection > 0, slides down when cleared

#### Pattern 12.3 — Notification Bell Panel

Click the bell icon in the top bar → slide-in panel from right (320px wide):

- Header: "Notifications" + "Mark all read" link
- List of notifications (reverse chronological):
  - Each notification: icon (type-dependent) + title + body text + timestamp
  - Unread: blue left border + slightly darker background
  - Read: normal background
- Notification types and icons:
  - Container arrived → cargo icon
  - Payment confirmed → check-circle icon
  - Claim filed → alert icon
  - CBM dispute → scale icon
  - Release note issued → document icon
- "View all notifications" link at bottom → `/notifications` page

#### Pattern 12.4 — Data Export Flow

Design the export experience triggered from any list page:

1. User clicks "Export" button (ghost, with download icon)
2. Dropdown appears: "Export as Excel" | "Export as PDF"
3. If data is large: modal shows "Preparing your export..." with progress indicator
4. On completion: browser download triggers + green toast "Export ready — downloading."
5. Error case: red toast "Export failed. Try again." with retry link

#### Pattern 12.5 — Empty States

Design empty states for each major entity:

- **No Containers:** Cargo container SVG illustration + "No containers yet." + "Create your first container" CTA
- **No Packing Lists:** Document/clipboard illustration + "No packing lists." + "Create a packing list" CTA
- **No Billing Records:** Invoice illustration + "No billing records for this filter." (no CTA — billing is generated automatically)
- **No Claims:** Checkmark illustration + "No claims. Everything looks good!" (positive empty state)
- **No Customers:** Person/team illustration + "No customers yet." + "Add first customer" CTA
- **No Notifications:** Bell illustration + "You're all caught up!" (positive)
- **Table with active filter but no results:** "No results for your current filters." + "Clear filters" link

#### Pattern 12.6 — Loading States

Design loading states for each major content type:

- **Table loading:** 5 skeleton rows (gray animated bars matching column widths)
- **Card loading:** Skeleton card with gray bars for title, 3 body lines, 1 button shape
- **Stat card loading:** Skeleton for large number + small label bar
- **Timeline loading:** 4 skeleton timeline entries

#### Pattern 12.7 — Error States

Design error states for network/system failures:

- **500 / Unknown error:** Red icon + "Something went wrong." + "Try again" button + "Contact support" link
- **404 Not Found:** Broken box illustration + "This page doesn't exist or you don't have access."
- **Offline / No Connection:** Cloud-with-X icon + "You appear to be offline." + "Retry" button
- **Session Expired:** Lock icon + "Your session has expired." + "Sign in again" button (redirects to login)
- **403 Forbidden:** Lock icon + "You don't have permission to view this." + "Go back" link

#### Pattern 12.8 — Responsive Table (Mobile)

On mobile (<768px), all data tables transform into:
- **Card list layout:** Each row becomes a card with a 2-column grid of label: value pairs
- Key columns promoted to card header (e.g. Name/Reference #)
- Status badge visible on card
- Actions: Single prominent button ("View") + three-dot menu for secondary actions

#### Pattern 12.9 — Status Transition Guardrails (Visual)

For status dropdowns (container tracking, claim status, refund status), design the "allowed transitions" visual:

- Dropdown items that are NOT valid next states are shown as disabled (grayed, not selectable) with a tooltip: "Cannot move from X to Y."
- Valid next states shown in full color
- Current state shown at top with "Current Status" label (not selectable)

#### Pattern 12.10 — Audit Log Viewer

A shared component used in: Tenant Detail > Audit Log, Billing Detail history, Claim Activity:

- Reverse-chronological table
- Columns: Action | Entity Type | Entity ID (monospace) | Actor (avatar + name) | Role badge | Timestamp | Changes
- "Changes" column: expandable `{before_state → after_state}` JSON diff viewer (key: old value strikethrough → new value highlighted green)
- Filter: Entity type | Actor | Date range

---

## Section 13 — Final Pass: Mobile Layouts & Responsive Variants

> **Carry-forward context:** Design system from Section 0. All screens already exist in desktop form. This section finalizes the mobile experience for the most frequently used screens by Customers and Warehouse Attendants (both primarily use mobile).

### Prompt

Design the **mobile variants** (375px iPhone-width viewport) for the following high-priority screens:

#### Mobile Priority Screens

**1. Customer: My Shipments (Homepage)**
- Full-width active shipment card with large status stepper (vertical)
- Past shipments as stacked cards (not a table)
- Bottom tab bar: Shipments (home icon) | Billing | Claims | Account

**2. Customer: Shipment Detail**
- Vertical stepper (8 stages, current stage with green pulsing dot and label)
- Carton list as accordion (tap to expand)
- Floating action button: "View Billing" (if billing exists)

**3. Customer: Billing Detail**
- Line items in a readable card (not a table)
- Large prominent total amount
- "I've Paid" CTA button (accent, full width, sticky at bottom)

**4. Warehouse Attendant: Pickup Queue**
- Large search bar at top (full-width)
- Active releases as stacked cards — each card has reference #, customer name, carton count, large "Record Pickup" button
- "Record Pickup" flow: full-screen modal (not a floating panel) optimized for one-thumb use
  - Step 1: Cartons count confirmation
  - Step 2: Is Delegate toggle (reveals fields if yes)
  - Step 3: Confirm button (full-width, green, 56px height)

**5. Login Page (Mobile)**
- Full-width white screen (no split panel)
- ShipX logo centered at top
- Form below with larger inputs (44px height min for touch targets)
- "Sign In" button: full-width, 52px height (accent)

**6. Packing List (Customer view)**
- Horizontal scroll for the carton items table OR accordion per item
- "Download PDF" sticky button at bottom

**General Mobile Rules for all screens:**
- Minimum touch target: 44×44px
- Input font size: min 16px (prevents iOS zoom)
- Modals: full-screen on mobile (not centered floating)
- Tables: Card list format
- Sidebar: Drawer (slide-in from left, 280px, with backdrop overlay)
- Tab bars: Bottom navigation (iOS style) for customer portal; hamburger → drawer for staff portals

---

## Section 14 — Gaps: Billing Flows, Import, Usage Analytics, Print Layouts & More

> **Carry-forward context:** Design system from Section 0. This section fills every feature left uncovered by Sections 1–13. Pass each sub-section individually or together. All screens must use the same design tokens, sidebar navigation, and component library established in Section 0.

---

### Screen 14.1 — Generate Billing (Manual Trigger)

> **Context:** Billing is normally auto-generated when a container status changes to `cleared`. However, Nigeria Office Staff and Tenant Admins can trigger billing manually for a specific container+customer pair — for example when auto-billing failed or a customer needs a corrected bill. Route: `POST /v1/billing`.

**Trigger:** "Generate Billing" button in the Billing List page header (`/billing`).

**Design as a `md` modal (560px wide):**

**Heading:** "Generate Billing Record"

**Step 1 — Select Container & Customer:**

- Container (searchable dropdown)
  - Search by container number
  - Shows: container # + vessel name + status badge
  - Only shows containers that are `cleared` or later (billing-eligible)
- Customer (searchable dropdown, filtered to customers with goods in the selected container)
  - Search by name or phone
  - Shows: customer name + carton count from their approved packing lists

**Live Preview panel (appears after both are selected):**

Pale blue card below the dropdowns:

```
Billing Preview
───────────────────────────────────────
Customer:       Ngozi Okonkwo
Container:      MSCU1234567
Total CBM:      0.56 CBM
CBM Rate:       $48.00 / CBM
Subtotal USD:   $26.88
Dollar Rate:    ₦1,650 / $1
Subtotal NGN:   ₦44,352.00
Carryover:      ₦5,000.00 (from BL-20260201)
Credits:        ₦0.00
─────────────────────────────
Total Due:      ₦49,352.00
```

- If CBM or rates are missing: amber warning card "CBM rate or dollar rate is not configured. Set them in Configuration before generating billing."

**Footer:** Cancel (ghost) + "Generate Billing Record" (primary)

**States:**
- Loading (after clicking Generate): spinner + "Generating billing..." — fields disabled
- Success: modal closes, green toast "Billing record generated for Ngozi Okonkwo — ₦49,352.00", billing list refreshes
- Error (already exists): red inline alert "A billing record already exists for this customer and container."

---

### Screen 14.2 — Record Payment Modal (Full Design)

> **Context:** Nigeria Office Staff confirm payments manually (bank transfer, cash) or via payment gateway. Route: `POST /v1/payments/:billing_id/confirm`. This supplements the thin mention in Section 7.2 — this is the full modal design.

**Trigger:** "Record Payment" button in Billing Detail page.

**Design as a `md` modal (560px):**

**Heading:** "Record Payment"

**Top info strip (read-only, gray background):**
- Customer: Ngozi Okonkwo | Outstanding: **₦49,352.00**

**Form fields:**

- Amount Paid (NGN) — number input with ₦ prefix
  - Default pre-filled: outstanding amount
  - Helper: "Enter the amount actually received, even if partial."
- Payment Method — segmented control or radio group:
  - 🏦 Bank Transfer
  - 💵 Cash
  - 🔗 Payment Gateway
- Payment Reference — text input (required for Bank Transfer / Gateway, optional for Cash)
  - Placeholder: "Bank transfer ref / gateway transaction ID"
- Notes — textarea (optional)

**Overpayment alert (shown live when amount > outstanding):**
- Amber banner: "⚠ Amount entered (₦55,000) exceeds the outstanding balance (₦49,352). An overpayment of ₦5,648 will be recorded and may generate a carryover credit."

**Footer:** Cancel (ghost) + "Confirm Payment" (`accent-500` kola copper)

**Post-confirmation states to design:**

- **Fully paid:** Modal closes, billing status badge updates to `paid` with green animation, toast "Payment of ₦49,352 confirmed. Billing is now fully paid." + "Generate Release Note?" prompt button appears inline in billing detail.
- **Partially paid:** Status updates to `partially_paid`, toast "Payment of ₦25,000 confirmed. Outstanding: ₦24,352."
- **Overpaid:** Status updates to `overpaid` in purple badge, toast "Payment of ₦55,000 confirmed. Overpayment of ₦5,648 recorded."

---

### Screen 14.3 — Packing List Excel Import (China Office)

> **Context:** China Office Staff can bulk-create packing lists by uploading an Excel file instead of entering items manually. The file is first uploaded to S3 (presigned URL), then the import endpoint is called with the S3 key. Route: `POST /v1/packing-lists/import`. Only available to China Office Staff.

**Trigger:** "Import from Excel" button on the Packing Lists list page (`/packing-lists`), beside the "Create Packing List" button.

**Design as a multi-step full-page flow (not a modal — too complex for a modal):**

**URL:** `/packing-lists/import`

**Breadcrumb:** Packing Lists > Import from Excel

**Step indicator (3 steps):** ① Upload File → ② Review & Validate → ③ Confirm Import

---

**Step 1 — Upload File:**

- **Container selector** (dropdown, required): "Which container are these packing lists for?"
  - Shows: container # + vessel + status
  - Only cleared/active containers shown

- **Download template** link: "Don't have the template? Download the ShipX Excel template →"
  - Ghost button with Excel icon, downloads `shipx_packing_list_template.xlsx`

- **Upload zone** (large, dashed border, 200px tall):
  - Icon: Excel file icon
  - Primary text: "Drag & drop your .xlsx file here"
  - Secondary: "or click to browse"
  - Accepted: `.xlsx` only | Max size: 10MB
  - On hover: border turns `primary-500` (Odum Green)
  - On drag-over: `primary-100` background fill + "Drop to upload" in `primary-700`

- **File selected state:** Shows filename + size + green checkmark + "Remove" link

- **"Upload & Parse" button** (primary, full-width below upload zone)

**Loading state (parsing):**
- Progress bar + "Parsing file... validating 47 rows"

---

**Step 2 — Review & Validate:**

**Summary bar (green or amber depending on errors):**
- "✓ 47 rows parsed | 3 customers | 0 errors" (green) OR
- "⚠ 47 rows parsed | 3 customers | 4 errors — fix errors before importing"

**Preview table (editable):**

| Carton Tag | Customer | Description | Weight Dispatch (kg) | Weight Actual (kg) | L×W×H (cm) | CBM | Received Date | Status |
|---|---|---|---|---|---|---|---|---|
| SHX-00001 | Ngozi Okonkwo | Electronics (mixed) | 12.5 | 12.8 | 40×30×25 | 0.030 | 15 Apr 2026 | ✓ |
| SHX-00002 | Ngozi Okonkwo | Clothing (assorted) | 8.2 | — | 35×30×20 | — | 15 Apr 2026 | ⚠ Missing weight |
| — | Emeka Eze | Phone accessories | — | — | — | — | — | ✗ Missing customer |

- ✓ Valid rows: normal text
- ⚠ Warning rows: amber background, warning icon in Status cell with tooltip
- ✗ Error rows: red background, error icon, row is non-importable

**Error panel (below table, shown if errors exist):**
- Collapsible "4 errors found" panel
- List: "Row 3: Customer not found in system — 'Emeka Ezeh' (check spelling)" | "Row 7: Received date is in the future" | etc.
- "Fix in file and re-upload" link

**Options:**
- Checkbox: "Skip rows with errors and import valid rows only (X of Y rows)"

**Navigation:** "← Back to Upload" (ghost) + "Continue →" (primary, disabled if unfixable errors and skip not checked)

---

**Step 3 — Confirm Import:**

**Summary card:**
- Container: MSCU1234567
- Customers: 3 (Ngozi Okonkwo, Adaeze Nwosu, Chukwuemeka Nwogu)
- Packing Lists to create: 3 (one per customer)
- Total cartons: 44 | Total CBM: 2.35

**Per-customer summary table:**
| Customer | Cartons | Total CBM | Status |
|---|---|---|---|
| Ngozi Okonkwo | 18 | 0.89 | Will create new packing list |
| Adaeze Nwosu | 14 | 0.72 | Will create new packing list |
| Chukwuemeka Nwogu | 12 | 0.74 | Will create new packing list |

**Footer:** "← Back" (ghost) + "Confirm & Import" (accent, large)

**Loading state:** "Importing packing lists... (3 of 3 created)"

**Success state:** Replace page with success card:
- Green checkmark illustration
- "3 packing lists imported successfully!"
- "They are now in Draft status and need to be submitted for approval."
- "View Packing Lists" (primary) + "Import Another File" (ghost)

---

### Screen 14.4 — Container Documents Upload Modal

> **Context:** Nigeria Office and China Office Staff can attach documents to a container (Bill of Lading, customs forms, inspection reports). The flow uses a presigned S3 URL. Route: `POST /v1/containers/:id/documents/presigned-url`. Triggered from Container Detail > Documents tab.

**Trigger:** "Upload Document" button in Container Detail > Documents tab.

**Design as a `md` modal (560px):**

**Heading:** "Upload Document"

**Form fields:**

- Document Type (dropdown, required):
  - Bill of Lading
  - Customs Declaration
  - Inspection Report
  - Weight Certificate
  - Container Seal Certificate
  - Other (free-text description appears below)

- Description (text input, optional unless type = "Other")
  - Placeholder: "Brief description of the document"

- File upload zone (compact, 120px tall):
  - "Drag & drop or click to browse"
  - Accepted: PDF, JPG, PNG | Max: 25MB

**Upload progress state (inside modal after file selected and "Upload" clicked):**
- Progress bar: "Uploading... 67%"
- File name + size shown
- Cancel link

**Footer:** Cancel (ghost) + "Upload" (primary)

**Success state:** Modal closes, toast "Document uploaded." + Documents tab refreshes showing new entry.

**Documents tab list design (in Container Detail):**

| Icon | Document Type | Description | Uploaded By | Date | Actions |
|---|---|---|---|---|---|
| 📄 | Bill of Lading | BL-MSCU1234567-2026 | Amara Okafor | 15 Apr 2026 | Download | Delete |
| 📄 | Customs Declaration | NCS Form C-47 | Amara Okafor | 17 Apr 2026 | Download | Delete |

- Empty state: "No documents uploaded yet." + "Upload Document" CTA

---

### Screen 14.5 — Apply Carryover to Billing

> **Context:** Staff can manually apply an outstanding carryover from a previous billing cycle to a current billing record. Route: `PATCH /v1/billing/:id/apply-carryover`. The carryover ID must be passed in the request body. Triggered from Billing Detail page.

**Trigger:** "Apply Carryover" button in Billing Detail page (shown when the customer has outstanding carryovers not yet applied).

**Carryover Alert in Billing Detail (shown when un-applied carryovers exist):**

Amber banner inside Billing Detail, above the total row:
- "⚠ This customer has ₦8,500 in outstanding carryovers from previous billing cycles."
- "Apply Carryover" button (amber outlined, small)

**Apply Carryover Modal (`sm`, 480px):**

**Heading:** "Apply Outstanding Carryover"

**Carryover detail card:**
| Field | Value |
|---|---|
| Carryover Amount | ₦8,500.00 |
| Source Billing | BL-20260201-003 |
| Created | 1 Feb 2026 |
| Status | Outstanding |

**Effect preview:**
```
Current Total Due:      ₦49,352.00
Carryover Applied:    + ₦8,500.00
─────────────────────────────────
New Total Due:          ₦57,852.00
```

**Warning text:** "Applying this carryover will increase the customer's total due. This action cannot be undone."

**Footer:** Cancel + "Apply Carryover" (danger-outlined — it increases the customer's debt)

**Success state:** Modal closes, toast "Carryover of ₦8,500 applied to billing." + billing breakdown card updates to show the carryover line.

---

### Screen 14.6 — Release with Outstanding Balance

> **Context:** In exceptional circumstances, a Tenant Admin can authorize release of goods even though the customer still has an outstanding balance (`release_with_outstanding: true` in `GenerateReleaseNoteRequest`). This requires a distinct warning confirmation flow to prevent accidental use.

**Trigger:** In the "Generate Release Note" modal (Section 9 / Billing Detail), a toggle appears when billing status is `partially_paid` or `unpaid`:

**Inside Generate Release Note Modal — Unpaid/Partial state:**

Normal flow: button "Generate Release Note" is disabled with tooltip "Billing must be fully paid to release goods."

Below the disabled button — alternate option:
- Collapsed section: "Release with outstanding balance?" (link/expander)
- When expanded: amber bordered card appears:

  > **⚠ Release with Outstanding Balance**
  >
  > You are about to release goods to a customer who has not fully paid.
  >
  > Outstanding amount: **₦24,352.00**
  >
  > Approval notes (required):
  > `[textarea — reason for exception]`
  >
  > This action is logged and audited.

- Toggle: ☐ "I confirm this release is authorized by Tenant Admin" (required)
- Button (appears only when toggle checked + notes filled): "Release Anyway" (danger, large)

**Confirmation dialog (second layer — double confirm):**
- Heading: "Are you absolutely sure?"
- Body: "A release note will be generated for **Ngozi Okonkwo** despite ₦24,352.00 remaining unpaid. The billing record will be marked `released_with_outstanding`."
- Footer: "Cancel" (ghost) + "Yes, Release" (danger, filled)

**Post-release state:** Release note generated, billing status badge changes to `released_with_outstanding` (purple), audit log entry created.

---

### Screen 14.7 — Billing: Storage Fees

> **Context:** Storage fees accrue when a customer's goods remain in the warehouse beyond the free-storage period. They are tracked separately from CBM billing and visible on the billing detail. Route: `GET /v1/billing/:id/storage-fees`.

**Placement:** A "Storage Fees" section in Billing Detail page, below Misc Charges and above Payment History.

**Storage Fees Section design:**

**Section header:** "Storage Fees" + info icon (tooltip: "Storage fees accrue after the free-storage period expires. They are added to your total outstanding balance.")

**If no storage fees:** Gray italic text "No storage fees accrued."

**If storage fees exist:**

Summary banner (amber if any accruing, green if all settled):
- "₦12,000 in storage fees have accrued (₦2,000/day × 6 days)"

**Storage Fees Table:**

| Period | Days | Rate/Day (NGN) | Amount (NGN) | Status | Notes |
|---|---|---|---|---|---|
| 20 Apr – 25 Apr 2026 | 5 | ₦2,000 | ₦10,000 | Unpaid | Free period expired 19 Apr |
| 26 Apr 2026 | 1 | ₦2,000 | ₦2,000 | Accruing | Today |

- Accruing rows: amber background, "Accruing" badge
- Settled rows: green "Settled" badge

**Total row:** Bold "Total Storage Fees: ₦12,000"

**Note:** Storage fees are informational in this view — they are settled by the customer as part of the total billing payment.

---

### Screen 14.8 — China Office: Escalated CBM Dispute View

> **Context:** When Nigeria Office Staff escalates a CBM dispute (`status = escalated_china`), it becomes visible to China Office Staff for investigation. China Office can then resolve (corrected CBM) or reject (original measurement stands). China Office sees disputes under `/billing/disputes` filtered to their role.

**Trigger:** China Office Staff navigates to `/billing/disputes`.

**Differences from Nigeria Office view (Section 7.3):**

**Filter bar — China Office default view shows only escalated disputes:**
- Default active filter: "Escalated to China" (highlighted chip, pre-selected)
- Other filters: All | Submitted | Investigating | Resolved | Rejected

**Disputes Table — China Office columns:**
| Dispute ID | Customer | Container | Original CBM | Customer's Claimed CBM | Escalated At | Staff Notes | Actions |
|---|---|---|---|---|---|---|---|
| CBM-001 | Ngozi Okonkwo | MSCU1234567 | 0.56 | 0.28 | 2 days ago | "Customer has photos" | Investigate |

- Actions: "Investigate" (primary) | "Resolve" | "Reject"

**Dispute Detail Side Panel (opens on row click):**

- Original CBM measurement (from China warehouse records)
- Customer's claimed CBM
- Reason stated by customer
- Nigeria staff notes (from escalation)
- Evidence photos (if uploaded by customer) — click to expand lightbox

**China Office Actions:**

"I've Re-measured" button → opens **Resolution Form:**
- Re-measured CBM (number input)
- Resolution type (radio):
  - `resolved_adjusted` — "Measurement error confirmed. New CBM: X.XX"
  - `resolved_no_change` — "Original measurement verified. Customer's claim rejected."
- Resolution notes (textarea, required, min 10 chars)
  - Helper: "This note will be visible to the Nigeria office and the customer."
- "Submit Resolution" button (primary)

**Reject Dispute button** → confirmation modal:
- "Reject this dispute? The customer's CBM claim will be dismissed. Original billing stands."
- Reason textarea
- "Confirm Rejection" (danger)

**Empty state (no escalated disputes):** "✓ No disputes escalated to China office." (green, positive)

---

### Screen 14.9 — Platform Admin: Full Audit Log Page

> **Context:** The Platform Admin has a cross-tenant audit log accessible at `/platform/audit-log`. Unlike the per-tenant audit log tab (covered in Section 2.4), this is a standalone full-page view across all tenants. Route: `GET /v1/platform/audit-log`.

**URL:** `/platform/audit-log`

**Breadcrumb:** Platform > Audit Log

**Page header:** "Platform Audit Log" + "Export" button (ghost, Excel/CSV dropdown)

**Filter bar:**
- Tenant filter (dropdown: All Tenants | [list of tenant names])
- Entity type filter (dropdown: All | tenant | tenant_user | customer | billing | container | packing_list | claim | refund | release_note)
- Action filter (dropdown: All | CREATE | UPDATE | STATUS_CHANGE | DELETE | ANONYMISE | SUSPEND | ACTIVATE)
- Actor filter (text search: "Search by user name or ID")
- Date range picker (from / to)
- "Apply Filters" button + "Clear" link

**Results summary:** "Showing 1–50 of 2,341 audit events matching filters"

**Audit Log Table:**

| Timestamp | Tenant | Entity Type | Entity ID | Action | Actor | Role | Before → After |
|---|---|---|---|---|---|---|---|
| 15 Apr 2026 14:32:01 | Acme Logistics | billing | BL-001 | STATUS_CHANGE | Amara Okafor | nigeria_office_staff | unpaid → paid |
| 15 Apr 2026 14:29:14 | StarShip Ltd | tenant | acme-uuid | SUSPEND | Platform Admin | platform_admin | active → suspended |

- Entity ID: monospace, truncated (hover to see full UUID)
- Tenant column: tenant name + subtle avatar
- Actor: user name + role badge
- Before → After: abbreviated summary; click row to expand

**Expanded row view (accordion below the row):**

```json
Before: { "status": "unpaid", "total_paid_ngn": 0 }
After:  { "status": "paid",   "total_paid_ngn": 49352 }
```

- JSON diff viewer: removed keys in red strikethrough, added/changed values in green

**Pagination:** 50 per page, cursor-based ("Load more" or Previous/Next)

**Empty state (no results for filter):** "No audit events match your filters. Try adjusting the date range or entity type."

---

### Screen 14.10 — Tenant Admin: Reports Page

> **Context:** The Tenant Admin has a `/admin/reports` page showing business-level analytics for their shipping company. This is distinct from Platform Admin's usage metrics — it focuses on operational KPIs, not API calls. Route: `GET /v1/tenant/reports`.

**URL:** `/admin/reports`

**Page header:** "Reports & Analytics" + Period selector (This Month | Last Month | Last 3 Months | Last 6 Months | Custom range)

**Layout:** Full-width, cards + chart sections

---

**Section A — Operational Overview (stat cards row):**

| Card | Metric | Trend |
|---|---|---|
| Containers Processed | 14 this period | +3 vs last period |
| Total Revenue (NGN) | ₦4,231,000 | +12% |
| Active Customers | 89 | +7 new this period |
| Average Days to Pickup | 4.2 days | -0.8 vs last period |

---

**Section B — Container Pipeline Chart:**

- **Stacked bar chart** — X axis: weeks in selected period; Y axis: container count
- Each bar stacked by status (In Transit, At Customs, Cleared, Picked Up)
- Tooltip on hover: "Week of Apr 14: 3 containers — 1 in transit, 1 cleared, 1 picked up"

---

**Section C — Revenue Breakdown (two columns):**

Left — **Revenue by Payment Status (donut chart):**
- Segments: Paid (green), Partially Paid (amber), Unpaid (red), Waived (gray), Released w/ Outstanding (purple)
- Center: "Total: ₦4,231,000"
- Legend below

Right — **Top Customers by Revenue (horizontal bar chart):**
- Top 10 customers ranked by total billed amount
- Customer name + NGN amount bar
- "View full customer list" link

---

**Section D — CBM & Billing Table:**

Tabular breakdown per container processed in the period:

| Container # | Customers | Total CBM | CBM Rate ($/CBM) | Dollar Rate | Total Billed (NGN) | Total Collected (NGN) | Outstanding (NGN) |
|---|---|---|---|---|---|---|---|
| MSCU1234567 | 12 | 8.42 | $48.00 | ₦1,650 | ₦665,000 | ₦620,000 | ₦45,000 |

**Footer:** "Export this report" → dropdown: Excel | PDF

---

**Section E — Claims Summary:**

Three mini-cards in a row:
- Damage Claims: X filed | Y resolved | Z open
- Missing Items: X logged | Y found | Z confirmed lost
- Refunds Issued: X approved | Total: ₦XXX,XXX

"View full claims" link → navigates to `/claims`

---

### Screen 14.11 — Notification Delivery Log

> **Context:** Tenant Admins and Nigeria Office Staff need visibility into which notifications were sent to customers (SMS, WhatsApp, email), and whether they delivered. This is a log viewer — not a notification composition screen. Accessed via the notification bell or a dedicated section.

**URL:** `/admin/notifications/log`

**Breadcrumb:** Admin > Notifications > Delivery Log

**Page header:** "Notification Delivery Log"

**Filter bar:**
- Channel filter (All | SMS | WhatsApp | Email)
- Event type filter (All | Payment Due | Status Update | Release Note Issued | Claim Filed | Custom)
- Status filter (All | Sent | Delivered | Failed | Pending)
- Customer filter (search)
- Date range

**Delivery Log Table:**

| Sent At | Customer | Channel | Event Type | Message Preview | Status | Actions |
|---|---|---|---|---|---|---|
| 15 Apr 14:32 | Ngozi Okonkwo | 📱 WhatsApp | Payment Due | "Your cargo is ready... ₦49,352" | ✅ Delivered | View |
| 15 Apr 14:31 | Adaeze Nwosu | 💬 SMS | Payment Due | "Dear Adaeze, your shipment..." | ⚠ Failed | Retry |
| 15 Apr 09:00 | Emeka Eze | 📧 Email | Status Update | "Your container has cleared..." | ✅ Delivered | View |

- Status badges: Delivered (green) | Failed (red) | Pending (amber) | Sent (blue — sent but delivery unconfirmed)
- "Retry" action: re-sends the same notification to the same customer via the same channel

**Notification Detail Modal (triggered by "View"):**

- Full message body rendered (SMS text or HTML email preview)
- Delivery timestamp
- Recipient phone/email (partially masked for privacy: `+234***4567`)
- Gateway response (technical, collapsed by default): "WhatsApp API response: 200 OK | Message ID: wamid.abc123"
- Error details (if failed): "Error: Invalid phone number format" or "Error: WhatsApp API timeout"

**Summary stats bar (above table):**
- "Last 30 days: 247 sent | 234 delivered (94.7%) | 13 failed | 0 pending"

---

### Screen 14.12 — Print / PDF Layouts

> **Context:** Two core documents need print-ready designs: the Packing List (customer-facing, showing their cargo items) and the Release Note (warehouse pickup authorization). These are generated on demand and rendered as clean black-and-white documents. Design both as A4 portrait print layouts.

---

#### 14.12.1 — Packing List Print Layout

**Trigger:** "Export PDF" or "Print" button on Packing List Detail page.

**A4 Portrait layout (210mm × 297mm), 20mm margins all sides:**

**Header block (top ~60mm):**
```
[COMPANY LOGO — left, max 120×40px]      [COMPANY NAME — right, 18pt bold]
                                          [company tagline if set — 9pt gray]
──────────────────────────────────────────────────────────────────────────────
PACKING LIST                                         Ref: PL-20260415-001
Container: MSCU1234567    Vessel: MSC Altair    Origin Port: Guangzhou
─────────────────────────────────
Customer:      Ngozi Okonkwo
Phone:         +234 801 234 5678
Date:          15 April 2026
Tracking Code: SHX-2026-NGOZI-001
──────────────────────────────────────────────────────────────────────────────
```

**Items Table (full width, 8pt font, tight row padding):**

| Carton Tag | Description | Weight (Dispatch) | Weight (Actual) | L×W×H (cm) | CBM | Received |
|---|---|---|---|---|---|---|
| SHX-00001 | Electronics (mixed) | 12.5 kg | 12.8 kg | 40×30×25 | 0.030 | 15 Apr |
| SHX-00002 | Clothing (assorted) | 8.2 kg | 8.5 kg | 35×30×20 | 0.021 | 15 Apr |

- Alternating row shading (white / very light gray)
- Borders: 0.5pt lines

**Footer block:**

```
──────────────────────────────────────────────────────────────────────────────
SUMMARY
Total Cartons: 4    Total Weight (Actual): 45.2 kg    Total CBM: 0.560

Prepared by: Kwame Asante (China Office)         Date: 15 April 2026

Status: APPROVED ✓

──────────────────────────────────────────────────────────────────────────────
This packing list is an official document issued by [Company Name].
For queries, contact: support@acmelogistics.com

Page 1 of 1
```

**Design notes:**
- No color — pure black on white (print-safe)
- Company logo top-left (grayscale rendering)
- "APPROVED" stamp-style overlay (light green circle with checkmark, 10% opacity) if status is approved
- If rejected: "REJECTED" in red at top-right (small, rotated 15°)

---

#### 14.12.2 — Release Note Print Layout

**Trigger:** "Print" button on Release Note Detail page.

**A4 Portrait layout:**

**Header block:**
```
[COMPANY LOGO — left]                    [COMPANY NAME — right, 18pt bold]

══════════════════════════════════════════════════════════════════════════
                           GOODS RELEASE NOTE
══════════════════════════════════════════════════════════════════════════

Reference Number:   RN-20260415-ABC123          [QR CODE — top right, 35×35mm]
Date of Issue:      15 April 2026
Valid Until:        22 April 2026 (7 days)
```

**Customer & Cargo section:**
```
┌─────────────────────────────────┬───────────────────────────────────┐
│ CUSTOMER DETAILS                │ CARGO DETAILS                     │
│                                 │                                   │
│ Name:     Ngozi Okonkwo         │ Container:  MSCU1234567            │
│ Phone:    +234 801 234 5678     │ Vessel:     MSC Altair            │
│                                 │ Total Cartons:  4                 │
│                                 │ Carton Tags:    SHX-00001         │
│                                 │                 SHX-00002         │
│                                 │                 SHX-00003         │
│                                 │                 SHX-00004         │
└─────────────────────────────────┴───────────────────────────────────┘
```

**Payment section:**
```
┌────────────────────────────────────────────────────────────────────┐
│ PAYMENT STATUS: PAID IN FULL ✓                                     │
│ Amount Paid: ₦49,352.00     Payment Ref: TRF-20260415-001         │
└────────────────────────────────────────────────────────────────────┘
```

**Warehouse instructions:**
```
COLLECTION INSTRUCTIONS
──────────────────────────────────────────────────────────────────────
Please present this release note (printed or digital) at:

   [WAREHOUSE ADDRESS — from tenant config, 11pt bold]

Operating Hours: Monday – Saturday, 8:00 AM – 5:00 PM

The customer or authorized delegate must present valid photo ID.
```

**Authorization footer:**
```
══════════════════════════════════════════════════════════════════════

Authorized by:  Amara Okafor                    Date: 15 April 2026
                Nigeria Office Staff
                [Company Name]

Signature: ______________________________

══════════════════════════════════════════════════════════════════════
This document is valid for one-time use only. ShipX Platform.
```

**Design notes:**
- Black on white (print-safe)
- QR code in top right corner (encodes the reference number for warehouse scanner)
- "RELEASE WITH OUTSTANDING BALANCE" watermark text diagonally across the page (red, 20% opacity) if `released_with_outstanding = true`
- "PARTIAL RELEASE" badge at top-right if `is_partial_release = true`

---

## Section 15 — Final Gaps: Release Note Generation, Payment Gateway, Warehouse Home, Quotas & Config

> **Carry-forward context:** Design system from Section 0. This section closes every remaining gap identified after the full audit of all 11 handler files and the PRD. Pass each sub-section individually.

---

### Screen 15.1 — Generate Release Note Modal (from Billing Detail)

> **Context:** After a billing record reaches `paid` status (or partially paid with an override), Nigeria Office Staff generate a Release Note directly from the Billing Detail page. This is the most critical missing flow — the `POST /v1/release-notes` call requires a `billing_id`, `carton_tags`, and optional `release_with_outstanding` + `approval_notes`. The billing detail page (Section 7.2) showed the button but not the modal.

**Trigger:** "Generate Release Note" button in Billing Detail page. Button is:
- **Enabled** (`accent-500` kola copper): when `payment_status = paid`
- **Enabled with warning** (amber outline): when `payment_status = partially_paid` — clicking opens the release-with-outstanding flow from Section 14.6
- **Disabled** (gray, tooltip): when `payment_status = unpaid` — tooltip reads "Customer must pay before goods can be released"

**Design as a `lg` modal (720px wide):**

**Heading:** "Generate Release Note"

**Customer & billing summary strip (read-only, light gray background):**
```
Customer: Ngozi Okonkwo   |   Container: MSCU1234567   |   Total Paid: ₦49,352   |   Status: PAID ✓
```

**Carton Selection section:**

Label: "Select cartons to include in this release note"
Helper: "All cartons are selected by default. Deselect cartons the customer is NOT collecting in this pickup."

Carton tag checklist — each carton as a row:
| ☑ | Tag | Description | Weight |
|---|---|---|---|
| ☑ | SHX-00001 | Electronics (mixed) | 12.8 kg |
| ☑ | SHX-00002 | Clothing (assorted) | 8.5 kg |
| ☑ | SHX-00003 | Phone accessories | 6.2 kg |
| ☐ | SHX-00004 | Spare parts | 9.1 kg |

- "Select all" / "Deselect all" links
- Running count: "3 of 4 cartons selected"

**If fewer than all cartons selected — Partial Release info banner (amber):**
> "⚠ You are generating a **partial release note**. A separate release note will be needed for the remaining 1 carton(s)."

**Approval Notes (optional textarea):**
- Placeholder: "Internal notes (not shown to customer)"

**Footer:** Cancel (ghost) + "Generate Release Note" (accent, large)

**Loading state:** "Generating..." spinner, button disabled

**Success state:** Modal closes → green toast "Release note RN-20260415-ABC123 generated." → An `info-500` blue inline card appears in Billing Detail:
```
Release Note Generated ✓
Reference: RN-20260415-ABC123
Cartons: 3 of 4 | Status: Active
[View Release Note →]   [Print →]
```

**Error state (release note already exists for some cartons):**
- Red inline error inside modal: "Cartons SHX-00001, SHX-00002 are already on release note RN-PREV-001. Deselect them or view the existing note."

---

### Screen 15.2 — Online Payment (Customer-Initiated via Gateway)

> **Context:** The platform supports payment via payment gateway (Paystack/Flutterwave) in addition to manual bank transfer and cash. When a customer on the billing page chooses to pay online, the flow uses a hosted payment page. The `POST /v1/payments/:billing_id/confirm` endpoint accepts `payment_method: "gateway"` and a `payment_reference` from the gateway callback.

**Placement:** Customer Billing Detail page (Screen 10.4) — replaces the "I've Paid" manual flow with a proper payment option.

#### Step A — Payment Method Selection (in Billing Detail, customer view)

Below the billing breakdown card, replace the single "I've Paid" button with:

**Payment Options Card:**

Heading: "How would you like to pay?"

Two options as large selectable cards (radio-button style):

**Option 1 — Pay Online (recommended)**
- Icon: credit card / lock icon
- Label: "Pay Online Now"
- Sub-label: "Secure payment via Paystack. Card, bank transfer, or USSD."
- Badge: "Instant confirmation"
- Border highlights `primary-500` (Odum Green) when selected, with `primary-50` Ice White background fill

**Option 2 — I've Already Paid**
- Icon: bank/transfer icon
- Label: "I've Made a Bank Transfer"
- Sub-label: "Notify us of your bank transfer. Our team will confirm within 2 hours."
- Badge: "Manual confirmation"

**"Proceed to Pay" button** (accent, full-width, large): enabled when an option is selected

#### Step B — Online Payment: Gateway Redirect

When "Pay Online" is selected and "Proceed to Pay" clicked:

**Transition screen (full page, white):**
- ShipX logo + company logo centered
- Circular spinner (large)
- "Taking you to secure payment..."
- "Powered by Paystack 🔒" below
- "Cancel and go back" link

→ Browser navigates to Paystack/Flutterwave hosted page (external)

#### Step C — Return from Gateway (callback URL)

**Success callback — URL: `/my-billing/:id/payment-success?ref=GATEWAY_REF`**

Full-page success state:
- Large green checkmark animation
- "Payment Successful! 🎉"
- Amount paid: ₦49,352.00
- Reference: GATEWAY_REF
- "Your release note will be generated shortly."
- "View My Billing" button (primary) | "Track My Shipment" (ghost)

**Failure callback — URL: `/my-billing/:id/payment-failed?reason=...`**

Full-page error state:
- Red X icon
- "Payment Failed"
- Reason: "Your card was declined." (or other gateway-provided reason)
- "Try Again" button (primary, retriggers gateway) | "Pay by Bank Transfer" (ghost, switches to manual)

#### Step D — Manual Payment Notification (customer-submitted)

When "I've Made a Bank Transfer" is selected:

**Manual Payment Form Card:**
- Amount Paid (NGN number input, pre-filled with outstanding)
- Bank / Account Debited (text input, e.g. "Zenith Bank")
- Transfer Reference (text input, required, e.g. "TRF20260415001")
- Date of Transfer (date picker)
- Optional note (textarea)
- "Notify Our Team" button (primary)

**After submission:** Replace form with:
```
✓ Payment notification sent!
We'll confirm your payment within 2 business hours.
Reference logged: TRF20260415001
```

**Staff-side notification:** Nigeria Office Staff receives a notification in their bell panel: "Ngozi Okonkwo has notified payment of ₦49,352. Reference: TRF20260415001" + "Confirm Payment" quick-action button.

---

### Screen 15.3 — Warehouse Attendant: Home Dashboard & Sidebar

> **Context:** The Warehouse Attendant role has no sidebar or home dashboard designed — they appear only in Screen 9.3 (Pickup Queue). This screen designs their full portal.

**Sidebar Navigation (Warehouse Attendant):**
- Company logo + name
- Role badge: "WAREHOUSE" in `warning-500` amber
- Nav (minimal — only what this role needs):
  - **Pickup Queue** (home — shows active release notes)
  - **Today's Pickups** (completed pickups recorded today)
  - **All Release Notes** (searchable history)
- Bottom: Avatar + name + "Warehouse Attendant" + Logout

---

**Home Page — Pickup Queue**

**URL:** `/warehouse` (home, same as Screen 9.3 but with full page design)

**Page header:** "Pickup Queue" + Today's date + "Good morning, Taiwo"

**Reference Lookup Bar (prominent, top of page):**
- Large white input box + "Look Up" button (accent, large)
- Placeholder: "Scan QR code or type release note reference (e.g. RN-20260415-ABC123)"
- Helper text: "Use the warehouse scanner or type the reference printed on the customer's release note"

**Alert counts row (3 small stat cards):**
- **Awaiting Pickup Today** — count (amber badge if >0)
- **Completed Today** — count (green)
- **Expired / Not Collected** — count (red)

**Active Queue Table (main content):**

Heading: "Ready for Pickup" + refresh icon (last updated: 2 min ago)

| Priority | Reference # | Customer Name | Container | Cartons | Authorized | Action |
|---|---|---|---|---|---|---|
| 🔴 Urgent | RN-20260415-001 | Ngozi Okonkwo | MSCU1234567 | 4 | 2h ago | Record Pickup |
| 🟡 Normal | RN-20260415-002 | Emeka Eze | MSCU1234567 | 2 | 4h ago | Record Pickup |
| 🟢 New | RN-20260415-003 | Adaeze Nwosu | MSCU9876543 | 6 | 10m ago | Record Pickup |

- Priority color: Urgent (red) = authorized >24h ago; Normal (amber) = 4–24h; New (green) = <4h
- Each "Record Pickup" button opens the Record Pickup modal (designed in Section 9.2)
- Row click → Release Note Detail (Section 9.2)

**Empty state (no active pickups):** "✓ All pickups cleared! No release notes awaiting collection." (green, positive)

---

**Today's Completions Page**

**URL:** `/warehouse/today`

**Page header:** "Today's Pickups" + date + completed count badge

**Completed Pickups Table:**

| Time | Reference # | Customer | Container | Cartons Released | Attendant | Delegate? |
|---|---|---|---|---|---|---|
| 09:42 | RN-20260414-005 | Ngozi Okonkwo | MSCU1234567 | 4 of 4 | Taiwo Adeyemi | No |
| 11:15 | RN-20260414-006 | Emeka Eze | MSCU9876543 | 2 of 2 | Taiwo Adeyemi | Yes |

- "Delegate" column: "Yes" → hover shows delegate name
- Row click → Release Note Detail (read-only at this point)

---

### Screen 15.4 — Usage Quota Alerts & Limit Enforcement

> **Context:** Each tenant subscription tier has limits (max users, max containers/month, max API calls, max SMS). When a tenant approaches or exceeds a limit, the UI must communicate this clearly at the right moment — not just return an HTTP 429.

#### A — Approaching Limit: Ambient Warning Banner

When a tenant is at ≥ 80% of any metered limit, show a dismissible banner in the Tenant Admin dashboard (Section 3.1) and at the top of affected pages:

**Banner design (amber, below top navbar):**

```
⚠ You've used 84% of your monthly API calls (4,200 / 5,000).
  Upgrade your plan to avoid service interruption.   [Upgrade Plan →]   [×]
```

- Shows whichever limit is most critical (highest percentage)
- "Upgrade Plan" link → Platform Admin contact page or upgrade flow (external)
- Dismissible per session (reappears next session)

#### B — Limit Reached: Blocking Error Screen

When an action fails because a limit is exceeded (API returns 429), show a dedicated full-page error instead of a generic error:

**URL:** handled inline (no redirect) — modal overlay

**Modal design (md, 560px):**
- Red icon: gauge at 100%
- Heading: "Monthly Limit Reached"
- Body:
  > "Your plan (**Starter**) allows **5,000 API calls per month**.
  > You've reached this limit for the current billing period.
  >
  > Your service will resume on **1 May 2026** (start of next billing period).
  > To continue now, upgrade to the **Professional** plan."
- Two buttons: "Contact Support" (ghost) + "Upgrade Plan" (primary)

**Specific limit messages per dimension:**

| Limit Hit | Message |
|---|---|
| Max users | "You've reached your user limit (10 users). Deactivate a user or upgrade to add more." |
| Max containers/month | "You've processed 20 containers this month — your Starter plan maximum. New containers can be created from 1 May." |
| SMS quota | "Your SMS notification quota is exhausted. Customers won't receive SMS alerts until your quota resets." |
| Storage | "Your storage quota (5 GB) is full. Delete old exports or upgrade for more storage." |

#### C — Platform Admin: Quota Warning View

In Platform Admin's Tenant Detail > Usage & Billing tab (Section 2.4), add quota status for each dimension:

**Quota Progress Bars section:**

```
API Calls       [████████████████░░░░] 4,200 / 5,000   84%  ⚠
SMS Sent        [████░░░░░░░░░░░░░░░░]   420 / 2,000   21%  ✓
Containers      [████████████████████] 20 / 20         100% 🔴 AT LIMIT
Active Users    [██████░░░░░░░░░░░░░░]    6 / 10        60%  ✓
Storage         [████████░░░░░░░░░░░░]  2.1 / 5 GB     42%  ✓
```

- Progress bar colors: green <80%, amber 80–99%, red 100%
- Red rows have "AT LIMIT" badge
- Platform Admin can "Override Limit" (one-time exception) with a notes field

---

### Screen 15.5 — Storage Fee Configuration (Tenant Admin)

> **Context:** Storage fees accrue per day after the free-storage period expires (default: 7 days free, then ₦500/day). Tenant Admins need to configure both the free period and the daily rate. Currently no UI exists for this — it would live in Tenant Admin Configuration (Section 4).

**Placement:** Add a "Storage Fees" item to the left nav in Section 4.1 (Company Settings), between "CBM Rate" and "Charge Types".

**URL:** `/admin/config/storage-fees`

**Page header:** "Storage Fee Policy" + subtitle: "Configure how storage fees are calculated when customers' goods remain in the warehouse beyond the grace period."

**Current Policy Card:**
```
Free Storage Period:      7 days after container clearance
Daily Storage Rate:       ₦500.00 per day
Applies to:               All customers (per billing record)
```

**Edit Policy Form:**

- Free storage period (number input + "days" label, min 0, max 30)
  - Helper: "Customers will not be charged storage for this many days after their container is cleared."
- Daily rate (NGN) (number input with ₦ prefix)
  - Helper: "Storage fees accrue per calendar day beyond the free period."
- Applies from (radio): "Next billing cycle only" | "All existing unpaid billing records"
  - Warning text for second option: "⚠ This will retroactively add storage fees to all current unpaid billing records."

"Save Policy" button (primary)

**Rate History section (below form):**
- Same pattern as Dollar Rate / CBM Rate history (Section 4.2)
- Columns: Free Period | Daily Rate | Changed By | Effective From

---

### Screen 15.6 — Container Status: Role-Restricted Stage Map

> **Context:** Container status has 8 stages. Not every role can update every stage — China Office Staff update China-side stages, Nigeria Office Staff update Nigeria-side stages. The UI must reflect this so staff don't see controls they cannot use. Currently Screens 5.3 and 6.4 mention status update without role restrictions.

**Design the "Update Status" dropdown with explicit stage availability per role:**

#### Status Stages and Who Can Set Them:

| Stage | Who can set it |
|---|---|
| `received_at_warehouse` | China Office Staff |
| `packed_in_container` | China Office Staff |
| `in_transit` | China Office Staff |
| `arrived_nigeria` | Nigeria Office Staff |
| `customs_clearance` | Nigeria Office Staff |
| `cleared` | Nigeria Office Staff |
| `ready_for_pickup` | Nigeria Office Staff (auto-set when release note generated) |
| `completed` | Nigeria Office Staff / Warehouse Attendant (auto-set on pickup) |

#### Update Status Dropdown Design (role-aware):

When China Office Staff opens the dropdown on a container in `packed_in_container` stage:
```
Current Status: Packed in Container

Available next stages:
  ○ In Transit        ← selectable (their jurisdiction)

Not available in your role:
  ○ Arrived Nigeria   (grayed, tooltip: "Updated by Nigeria Office")
  ○ Customs Clearance (grayed)
  ○ Cleared           (grayed)
```

When Nigeria Office Staff opens the same dropdown after `arrived_nigeria`:
```
Current Status: Arrived Nigeria

Available next stages:
  ○ Customs Clearance  ← selectable
  
Completed stages (locked):
  ✓ Received at Warehouse
  ✓ Packed in Container
  ✓ In Transit
  ✓ Arrived Nigeria
```

**Visual design rules:**
- Available stages: normal text, selectable radio button
- Role-restricted stages (other role's jurisdiction): grayed, cursor not-allowed, tooltip on hover
- Already-completed stages: checkmark icon, strike-through text, not selectable
- Forward-only: cannot go back to a previous stage (grayed with tooltip: "Cannot revert to a previous stage")

#### Status Progression Stepper (Container Detail header)

The horizontal stepper in Container Detail (Section 5.3) should show:

- Completed stages: filled circle with checkmark (`info-500` blue for China stages, `primary-500` Odum Green for Nigeria stages)
- Current stage: pulsing ring (uses the stage's jurisdiction color above)
- Future stages: gray empty circle (`neutral-300`)
- **Color coding:** China-side stages (stages 1–3) in `info-500` blue; Nigeria-side stages (stages 4–8) in `primary-500` Odum Green — uses the brand green for the home market (Nigeria) and a neutral cool blue for the originating market (China). Helps both sides visually understand their jurisdiction.

---

### Screen 15.7 — Notification Template: Variable Reference & Live Preview

> **Context:** Section 4.5 sketched the notification template editor but left the variable system vague. Admins need a clear variable reference and a live preview with real customer data so they know what the notification will look like before saving.

**Enhancements to Screen 4.5 (Notification Templates):**

#### A — Variable Reference Panel

Alongside each template text editor, show a collapsible side panel:

**"Available Variables" panel (right side, 240px):**

Heading: "Insert Variable" + search input

List of variables grouped by category:

**Customer:**
- `{customer_name}` — "Ngozi Okonkwo"
- `{customer_phone}` — "+234 801 234 5678"

**Container & Shipment:**
- `{container_number}` — "MSCU1234567"
- `{tracking_code}` — "SHX-2026-NGOZI-001"
- `{shipment_status}` — "Cleared"
- `{estimated_pickup_date}` — "20 Apr 2026"

**Billing:**
- `{amount_ngn}` — "₦49,352.00"
- `{outstanding_ngn}` — "₦24,000.00"
- `{invoice_number}` — "ACME-INV-20260415-0042"

**Company:**
- `{company_name}` — "Acme Logistics"
- `{warehouse_address}` — "12 Wharf Road, Apapa, Lagos"
- `{support_phone}` — "+234 1 234 5678"

Each variable: click to insert at cursor position in the editor.

**Validation:** If the editor contains `{unknown_variable}`, highlight it in red with tooltip: "Unknown variable — this will not be replaced."

#### B — Character Counter (SMS-specific)

For SMS channel only, show below the editor:

```
Characters: 142 / 160 ✓      SMS segments: 1
```

- Green when ≤ 160 (single SMS)
- Amber when 161–320 (2 segments — costs double)
- Red when > 320 (3+ segments — warn admin)

#### C — Live Preview Panel

Redesign the preview panel (right 30% of screen) to show a **realistic device mockup**:

**SMS/WhatsApp channel:** Show a phone frame (iPhone outline) with the message in a chat bubble:
```
 ┌─────────────────────────────┐
 │  Acme Logistics  🟢         │
 │                             │
 │  Dear Ngozi Okonkwo,        │
 │  Your cargo in container    │
 │  MSCU1234567 is cleared     │
 │  and ready for pickup.      │
 │                             │
 │  Amount due: ₦49,352.00     │
 │  Collect at: 12 Wharf Rd    │
 │  Lagos.                     │
 │                             │
 │  Acme Logistics             │
 │                  ✓✓ 14:32   │
 └─────────────────────────────┘
```

**Email channel:** Show a simplified email client frame with:
- Subject line (editable in template)
- From: "Acme Logistics <no-reply@acmelogistics.com>"
- Email body rendered as HTML (if HTML template) or plain text

"Send Test" button below the preview: sends the template to the admin's own phone/email with sample data.

---

### Screen 15.8 — Customer: Refund Preference Capture

> **Context:** When a refund is approved, the customer's preference matters: do they want an immediate bank transfer, or should the refund be applied as a credit to their next billing? The `customer_choice` field exists on `CreateRefundRequest` but there's no UI for the customer to specify this — it currently relies on staff entering it on the customer's behalf.

**Placement:** Customer Billing Detail (Screen 10.4) — when CBM dispute is resolved with adjustment, OR on a dedicated "Refund Request" screen accessible via "Request Refund" on billing detail.

#### A — Refund Request Link (Customer Billing Detail)

Below the CBM dispute section in Screen 10.4:

If billing status is `overpaid`: Amber banner:
> "You have overpaid by ₦5,648. Would you like a refund or credit?"
> [Request Refund →]

#### B — Refund Request Form (Customer)

**URL:** `/my-billing/:id/refund-request`

**Back link:** "← Billing"

**Page header:** "Request a Refund"

**Refund details card (read-only):**
- Overpayment amount: ₦5,648.00
- Or: Damage claim reference (if damage-related)
- Billing reference

**Customer preference section:**

Heading: "How would you like to receive your refund?"

Two large selectable option cards:

**Option A — Immediate Bank Refund**
- Icon: bank building
- Label: "Refund to my bank account"
- Sub-label: "We'll process the transfer within 3–5 business days."
- When selected: shows bank details fields:
  - Account Name (text input)
  - Account Number (number input, 10 digits)
  - Bank Name (dropdown: Zenith | GTBank | First Bank | Access Bank | UBA | Other)

**Option B — Apply as Credit**
- Icon: gift/credit card
- Label: "Apply as credit to my next shipment"
- Sub-label: "The amount will be automatically deducted from your next billing."
- When selected: no additional fields

**Notes (optional textarea):** "Any additional information about your refund request"

**Submit button:** "Submit Refund Request" (primary, full-width)

**Success state:** Full-width success card:
- "Your refund request has been submitted."
- "Our team will review and respond within 2 business days."
- Reference number shown
- "View My Claims" link

---

### Screen 15.9 — Staff: Add Customer Form

> **Context:** While customers can self-register (Screen 1.2), Nigeria Office Staff also add customers manually (`POST /v1/customers`). Section 3.5 (Customer List) shows an "Add Customer" button but the form was never designed.

**Trigger:** "Add Customer" button on Customer List page (`/admin/customers`).

**Design as a `md` modal (560px):**

**Heading:** "Add New Customer"

**Form fields:**

- Full name (required)
- Email address (required)
  - Helper: "Used for login. Cannot be changed after creation."
- Phone number (required, placeholder: "+234...")
- WhatsApp number (optional, placeholder: "+234... if different from phone")
- Address (optional, textarea)
- Contract details (optional, textarea)
  - Helper: "Internal notes about this customer's contract or special terms"
- Notification consent (multi-checkbox): "Notify via: ☐ SMS ☐ WhatsApp ☐ Email"
- Consent given at (date picker, defaults to today)
  - Helper: "Date the customer provided consent for data processing (GDPR)"

**Footer:** Cancel (ghost) + "Add Customer" (primary)

**Success state:** Modal closes, green toast "Customer Ngozi Okonkwo added. An invite email has been sent." + Customer List refreshes with new row highlighted.

**Error state (duplicate email):** Red inline alert inside modal: "A customer with this email already exists in your account."

---

### Screen 15.10 — CBM Dispute: Investigation Step (Nigeria Office)

> **Context:** After acknowledging a CBM dispute, Nigeria Office Staff begins an investigation before deciding to resolve locally or escalate to China. There is no investigation UI currently designed — Section 7.3 jumps from "acknowledge" to "escalate/resolve." This adds the missing investigation state.

**Placement:** Dispute Detail side panel / modal (Section 7.3), shown when `dispute_status = acknowledged`.

**Investigation Panel (shown when status = acknowledged):**

Label: "Investigation in Progress"

Two action paths in a split card:

**Path A — Resolve Locally** (Nigeria Office has enough information):
- "I have enough information to resolve this."
- "Resolve Dispute" button → opens existing Resolve modal (Section 7.3)

**Path B — Escalate to China Office**:
- "I need China Office to re-verify the CBM measurement."
- Internal notes textarea: "Notes for China Office" (required before escalating)
  - Helper: "Explain what evidence you've reviewed and why China re-measurement is needed."
- "Escalate to China Office" button (primary)

**Escalation confirmation dialog:**
- "Escalate dispute CBM-001 to China Office?"
- "Kwame Asante (China Office Staff) will be notified."
- Your notes: [preview of notes entered]
- Cancel + "Yes, Escalate" (primary)

**After escalation:** Dispute status badge changes to `escalated_china`, timeline adds event "Escalated to China Office by Amara Okafor", China Office notification sent.

**Dispute status timeline (visible throughout):** Vertical timeline showing all state transitions:
- ✓ Submitted — 15 Apr 14:32 — by Ngozi Okonkwo
- ✓ Acknowledged — 15 Apr 15:00 — by Amara Okafor (Nigeria Office)
- ⏳ Investigating — 15 Apr 15:01 — by Amara Okafor
- → [Escalated to China / Resolved]
