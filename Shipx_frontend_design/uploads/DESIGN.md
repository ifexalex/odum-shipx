---
version: alpha
name: Odum
description: >
  Odum is the parent brand for products including ShipX (a B2B logistics SaaS
  for China–Nigeria cargo). This design system is green-anchored with a kola
  copper accent, drawing on Igbo cultural symbolism (the three-lobed kola nut)
  and modern geometric form language.
colors:
  # Canonical roles
  primary: "#1C7922"
  secondary: "#0B2F0D"
  tertiary: "#9A3412"
  neutral: "#1C1B1C"

  # Primary green family (Odum Greens)
  primary-deep: "#14471A"
  primary-strong: "#155F1B"
  primary-bright: "#2DC438"
  primary-soft: "#D6F5DA"
  primary-tint: "#F3FCF4"

  # Tertiary / accent family (Kola Copper)
  tertiary-deep: "#7C2D12"
  tertiary-hover: "#C2410C"
  tertiary-soft: "#FED7AA"

  # Status palette
  success: "#16A34A"
  success-strong: "#14532D"
  success-soft: "#DCFCE7"
  warning: "#D97706"
  warning-strong: "#7C2D0E"
  warning-soft: "#FEF3C7"
  error: "#DC2626"
  error-strong: "#991B1B"
  error-soft: "#FEE2E2"
  info: "#2563EB"
  info-strong: "#1E3A8A"
  info-soft: "#DBEAFE"

  # Neutrals (Odum-warm gray family)
  neutral-strong: "#374151"
  neutral-mid: "#666666"
  neutral-soft: "#6B7280"
  neutral-line: "#CCCCCC"
  neutral-line-soft: "#E5E7EB"
  surface-page: "#F3F4F6"
  surface-muted: "#F9FAFB"
  surface: "#FFFFFF"

  # Role accents (used to orient users across multi-role portals)
  role-platform: "#7C3AED"
  role-china: "#4F46E5"
typography:
  display-lg:
    fontFamily: Averta
    fontSize: 32px
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: -0.01em
  display-md:
    fontFamily: Averta
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: -0.005em
  headline-lg:
    fontFamily: Averta
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.4
  headline-md:
    fontFamily: Averta
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.5
  body-lg:
    fontFamily: Kumbh Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
  body-md:
    fontFamily: Kumbh Sans
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.43
  body-sm:
    fontFamily: Kumbh Sans
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.33
  label-md:
    fontFamily: Kumbh Sans
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.43
  label-sm:
    fontFamily: Kumbh Sans
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.33
    letterSpacing: 0.04em
  mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.54
rounded:
  none: 0px
  sm: 8px
  md: 10px
  lg: 14px
  xl: 12px
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 64px
  gutter: 24px
  card-padding: 24px
  sidebar-width: 240px
  content-max: 1280px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 36px
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.surface}"
  button-primary-active:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.surface}"
  button-accent:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.surface}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 36px
  button-accent-hover:
    backgroundColor: "{colors.tertiary-hover}"
    textColor: "{colors.surface}"
  button-accent-active:
    backgroundColor: "{colors.tertiary-deep}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 36px
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 12px
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.surface}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 12px
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: 12px
    height: 40px
  input-focus:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
  input-error:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.md}"
    padding: 24px
  card-stat:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.xl}"
    padding: 24px
  badge-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success-strong}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  badge-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-strong}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  badge-error:
    backgroundColor: "{colors.error-soft}"
    textColor: "{colors.error-strong}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  badge-info:
    backgroundColor: "{colors.info-soft}"
    textColor: "{colors.info-strong}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  badge-accent:
    backgroundColor: "{colors.tertiary-soft}"
    textColor: "{colors.tertiary-deep}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  badge-neutral:
    backgroundColor: "{colors.neutral-line-soft}"
    textColor: "{colors.neutral-mid}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  modal:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.lg}"
    padding: 24px
  sidebar:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.surface}"
    width: 240px
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-line}"
    typography: "{typography.label-md}"
    padding: 12px
    height: 40px
  nav-item-active:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.surface}"
    typography: "{typography.label-md}"
  toast-success:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.md}"
    padding: 16px
  toast-error:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.md}"
    padding: 16px

  # Surfaces & containers
  app-surface:
    backgroundColor: "{colors.surface-page}"
    textColor: "{colors.neutral}"
  card-muted:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.neutral}"
    rounded: "{rounded.md}"
    padding: 24px

  # Table row states (used everywhere data tables appear)
  table-row-hover:
    backgroundColor: "{colors.primary-tint}"
    textColor: "{colors.neutral}"
  table-row-selected:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.neutral}"

  # Focus ring (the bright green at 35% alpha lives in prose; the base color anchors here)
  focus-ring:
    backgroundColor: "{colors.primary-bright}"

  # Helper text & secondary copy roles
  text-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-strong}"
    typography: "{typography.body-md}"
  text-helper:
    backgroundColor: "transparent"
    textColor: "{colors.neutral-soft}"
    typography: "{typography.body-sm}"

  # Role badges (orient users in multi-role portals)
  role-badge-platform:
    backgroundColor: "{colors.role-platform}"
    textColor: "{colors.surface}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px
  role-badge-china:
    backgroundColor: "{colors.role-china}"
    textColor: "{colors.surface}"
    typography: "{typography.label-sm}"
    rounded: "{rounded.full}"
    padding: 8px

  # Status indicators — used as toast left borders, timeline event dots, status dots in lists
  indicator-success:
    backgroundColor: "{colors.success}"
    width: 4px
  indicator-warning:
    backgroundColor: "{colors.warning}"
    width: 4px
  indicator-info:
    backgroundColor: "{colors.info}"
    width: 4px
---

# Odum Design System

## Overview

Odum is the parent brand for a portfolio of B2B and operational products — most prominently **ShipX**, a multi-tenant logistics platform for China–Nigeria cargo. The brand exists to be "the lion of the business world": bold, decisive, and confident, built for operators who *lead* rather than follow.

The visual identity is rooted in Igbo cultural symbolism — specifically the three-lobed kola nut (*Oji Ikenga / Oji Dike*), a traditional symbol of strength, bravery, and the unity of body, mind, and spirit. This translates visually into geometric forms with **beveled, rounded corners** and a green-anchored palette that evokes growth, stability, and trust.

The UI feels: **dense but legible**, **bold but not flashy**, **professional but warm**. We avoid corporate-navy clichés in favor of the deeper, more grounded forest greens. CTAs use a kola-nut-inspired warm copper that pops against the green brand surfaces — culturally rooted, never random orange.

Voice in the UI is active and ownership-driven: prefer "Lead every shipment" over "Track shipments"; prefer "Confirm payment" over "Submit form." Headings carry weight; body copy stays functional.

## Colors

The palette has two protagonists — Odum's green family for brand and primary actions, and a single warm copper accent reserved for the most important CTAs.

- **Primary (#1C7922) — Odum Green:** The brand color. Used for primary buttons, links, active states, brand surfaces. Confident and grounded.
- **Secondary (#0B2F0D) — Dark Green:** Sidebar background and the deepest brand contrast. A near-forest tone, never corporate-navy.
- **Tertiary (#9A3412) — Kola Copper:** The single CTA driver. Reserved for "Confirm Payment," "Generate Release Note," and other key conversion actions. Earth-toned, distinct from any warning state.
- **Neutral (#1C1B1C) — Odum Black:** Primary text. Slightly warm, never pure black — it should feel like ink, not void.

The palette also includes:
- A **bright accent green** (`primary-bright` `#2DC438`) for focus rings, progress indicators, and active highlights — Pantone 15-0146 TCX *Green Flash* approximates this.
- A **functional status palette** — `success` `#16A34A` (lime-leaning, distinct from brand green), `warning` `#D97706` amber, `error` `#DC2626` red, `info` `#2563EB` blue. Each has a `-soft` background variant for badges and banners.
- A **neutral gray family** that runs warm (`neutral-mid` `#666666` is the Odum Dark Grey) rather than cool, to harmonize with the green primary.
- **Role accents** for multi-role applications: `role-platform` `#7C3AED` deep purple (Platform Admin), `role-china` `#6366F1` indigo (China Office Staff). The Nigeria role uses `tertiary` to root it culturally.

## Typography

The type system pairs **Averta** (Kostas Bartsokas) for display and headings with **Kumbh Sans** (Saurabh Sharma) for body and UI text.

- **Averta** carries the Odum identity. Its geometric construction and consistent stroke weight echo the brand's beveled-form vocabulary; its open counters in *d, u, m* are a direct visual reference to the Odum wordmark. Use it sparingly but boldly — headlines should *land*, not whisper.
- **Kumbh Sans** is the workhorse. It's free on Google Fonts, has a complete weight range, and stays legible at small sizes — essential for dense logistics tables and form-heavy screens.
- **JetBrains Mono** handles tracking codes, container numbers, monetary amounts, and any tabular figures.

> **Licensing note:** Averta is a commercial font (license via Type Department). If unavailable, fall back to **Inter** at the same scale and weights — it's the closest free geometric alternative.

The scale runs from `display-lg` (32px Averta Bold for page heroes) to `body-sm` (12px Kumbh for captions and metadata). `label-sm` is uppercase with 0.04em letter-spacing for status badges and tags. Never italicize — the brand's bold voice prefers weight contrast over slant.

## Layout

The app uses a fixed sidebar (`spacing.sidebar-width` = 240px) on desktop with a scrollable main content area capped at `spacing.content-max` = 1280px centered. Tablet collapses the sidebar to icon-only at 64px wide. Mobile (<768px) replaces the sidebar with a bottom navigation bar (max 5 icons) and converts the sidebar into a slide-in drawer.

The spacing scale is a strict 4px base — every dimension is a multiple of 4. The standard rhythm: `xs` 4px (tight inline gaps), `sm` 8px (icon gutters), `md` 16px (component-internal), `lg` 24px (between cards, card padding), `xl` 32px (between major sections), `2xl` 48px and `3xl` 64px (page-level breathing room). Section gutters use 24px; card internal padding is 24px.

Tables stay dense — body rows use `body-md` (14px Kumbh Regular) with 1px `neutral-line-soft` separators rather than zebra striping. Avoid heavy stripes; the geometric clarity of clean rows reinforces Odum's "engineered" feel.

## Elevation & Depth

Elevation is conveyed primarily through **green-tinted shadows** rather than pure black, so depth feels cohesive on green brand surfaces.

- **Card resting:** `0 1px 3px rgba(11,47,13,0.08), 0 1px 2px rgba(11,47,13,0.05)`
- **Card hover:** `0 4px 12px rgba(11,47,13,0.10), 0 2px 4px rgba(11,47,13,0.06)` — a subtle lift, no border color change.
- **Modal:** `0 10px 25px rgba(11,47,13,0.18)` — a deeper recess, signals overlay context.
- **Focus ring:** `0 0 0 3px rgba(45,196,56,0.35)` — bright green at 35% alpha, applied on every focusable input, button, and link. This is non-negotiable for accessibility.

Modal scrims use `rgba(11,47,13,0.55)` — green-tinted backdrop, not generic black, so the brand voice carries even when content is dimmed.

## Shapes

The shape language is **beveled-but-bold** — a direct echo of the Odum kola-nut logomark, where rounded corners soften geometric strength without sacrificing structure. Avoid both razor-sharp corners (too austere for the warm Odum voice) and pillowy fully-rounded shapes (too consumer-friendly for B2B logistics).

- **Buttons & inputs:** `rounded.sm` (8px) — slightly more rounded than typical SaaS, less than a CTA pill.
- **Cards:** `rounded.md` (10px) — the everyday container radius.
- **Stat tiles & hero metrics:** `rounded.xl` (12px) — slightly larger to feel monumental for big numbers.
- **Modals:** `rounded.lg` (14px) — most-rounded, signals the overlay's stage moment.
- **Badges & pills:** `rounded.full` (9999px) — fully rounded for status chips, since they read as flowing markers (echoing the open counters in the Odum wordmark).

Mix radii within a screen freely *across* component types (a `rounded.full` badge inside a `rounded.md` card is fine), but never within the same component family — don't mix `sm` and `md` buttons in the same view.

## Components

**Buttons** come in five variants: `primary` (Odum Green for standard actions), `accent` (Kola Copper, reserved for the single most important conversion action per screen), `secondary` (outlined, for low-emphasis), `ghost` (text-only, for tertiary actions and links inside content), and `danger` (red, for destructive actions). Three sizes: `sm` 28px, `md` 36px (default), `lg` 44px. States cycle through default → hover (one tone deeper) → active/pressed (one tone deeper still) → disabled (50% opacity, no pointer) → loading (spinner replaces label).

**Input fields** use 1px `neutral-line` border at rest, switch to a 2px `primary` border with the green focus ring on focus, and 1px `error` border + inline error message below on validation failure. Labels sit above (`label-md` Kumbh Medium `neutral-strong`); helper text sits below (`body-sm` `neutral-soft`); error text replaces helper.

**Cards** default to `surface` white with a 1px `neutral-line-soft` border and the resting card shadow. The `card-stat` variant uses `rounded.xl` (12px) and contains a large `display-md` Averta Bold number, a `label-md` label, and a small trend indicator in `success` or `error` with an arrow icon.

**Badges** are pill-shaped (`rounded.full`) with a small filled dot indicator on the left and `label-sm` uppercase text. Map statuses to color families: green `success` for paid/cleared/picked-up/verified/active; blue `info` for in-transit/processing/acknowledged; amber `warning` for pending/draft/under-inspection; copper `tertiary` for discrepancies/investigating (active human review); red `error` for rejected/cancelled/suspended/seized/overdue; gray `neutral` for inactive/expired/closed.

**Sidebar** uses `secondary` Dark Green background, with `nav-item` text in `neutral-line` light gray for legibility on dark green. Active nav items get the `primary-deep` row background plus a 3px `primary-bright` left border accent. Section labels above nav groups are `label-sm` uppercase in `neutral-line` with extended letter-spacing.

**Modals** are 480/560/720/960px wide depending on context (alert/form/long-form/detail), centered with the green-tinted scrim. Header has `display-md` Averta Bold title + close icon; footer has right-aligned action buttons (cancel ghost + confirm primary/accent/danger).

**Toast notifications** appear top-right, stack with 8px gaps, 360px wide, auto-dismiss at 4s (success/info) or 7s (warning/error). Each variant uses a 4px left border in its status color + matching status icon.

## Do's and Don'ts

- **Do** use `tertiary` (Kola Copper) only for the single most important conversion action per screen. If two CTAs are present, only one is `accent` — the other is `primary`.
- **Don't** use `tertiary` and `warning` next to each other — they're close enough on the warm spectrum that contrast suffers. Separate them spatially.
- **Do** maintain WCAG AA contrast — `primary` on `surface` white passes (4.96:1); `tertiary` on `surface` white passes (5.76:1); white on `secondary` passes (16.4:1).
- **Don't** italicize. The Odum voice is bold and upright — emphasis comes from weight (`label-md` 500, `label-sm` 600), not slant.
- **Do** use `mono` for any tracking code, container number, or monetary amount in a table — operators read these in scanning patterns and need character-grid alignment.
- **Don't** use pure black (`#000`) anywhere. `neutral` is `#1C1B1C` for a reason — pure black against green brand surfaces feels harsh.
- **Do** tint shadows with the dark-green RGB (`rgba(11,47,13,…)`) instead of black, so depth reads as cohesive on green canvases.
- **Don't** mix radii within a component family — all primary buttons are `rounded.sm`, all stat tiles are `rounded.xl`. Cross-family mixing is fine; same-family mixing breaks rhythm.
- **Do** keep the `neutral-line` 1px border on every form input, even at rest — visible affordance matters more than minimalism in a dense logistics UI.
- **Don't** stack two consecutive `display-lg` headings on a page. There's only one hero per screen.
