# Spec: Landing Page Full Design

**ID:** SPEC-029  
**Status:** Draft  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021, SPEC-022

## Overview

SPEC-022 restyled the minimal auth-gate card (the current `LandingPage.tsx`) with design system tokens. The full landing page design in `docs/design/landing.html` is a proper marketing page: a sticky frosted-glass nav, a hero section with a headline, CTAs, a reassurance line, and a static app-preview illustration, followed by a three-column features section, an accent CTA strip, and a footer. This spec replaces the minimal card with that full page.

The landing page uses its own self-contained nav — not the app's `Header.tsx` — because the two serve different purposes (marketing vs. authenticated app shell). `RootLayout.tsx` must be updated to suppress `Header` on the landing route.

## Scope

### In Scope

- `apps/portal/src/routes/LandingPage.tsx` — full rewrite to the five-section marketing page.
- `apps/portal/src/components/RootLayout.tsx` — conditionally hide the app `Header` on the `/` route so the landing page renders its own nav.
- A static `AppPreview` sub-component (inline in LandingPage.tsx) that renders the browser-chrome mockup illustration shown in the hero. No real data — it is `aria-hidden="true"`.

### Out of Scope

- "Docs" and "Security" nav links — they're anchor links in the mockup and have no real destinations; render them but point to their page-section anchors (`#features`, `#security`). No routing changes needed.
- Privacy and Terms footer links — render them as `<a href="#">` placeholders.
- Any animation beyond CSS transitions already defined in the design system.
- Real routing for the "Docs" link.

---

## Functional Requirements

### FR-001: Layout and route isolation

#### Description

The landing page must not render the app's `Header` component. It has its own nav. `RootLayout` must detect the landing route and omit the header there.

#### Acceptance Criteria

- [ ] `RootLayout.tsx` uses `useLocation()` (already imported via react-router-dom) to check `location.pathname === '/'`. When true, the `<Header />` is not rendered.
- [ ] The `<Outlet />` fills the full viewport on the landing route.
- [ ] On all other routes (e.g. `/files`, `/not-found`) the `<Header />` renders as before.
- [ ] Existing `RootLayout` tests still pass.

### FR-002: Sticky nav bar

#### Description

A sticky top nav with frosted glass effect, the brand mark, anchor nav links, and auth action buttons.

#### Acceptance Criteria

- [ ] Nav: `sticky top-0 z-20 h-16 bg-white/80 backdrop-blur-sm backdrop-saturate-150 border-b border-border`.
- [ ] Inner: `max-w-[1080px] mx-auto px-6 h-full flex items-center gap-4`.
- [ ] Brand: `<BrandMark />` (from SPEC-023/028) — links to `#` (or `/`).
- [ ] Nav links (desktop only, hidden `sm:hidden` or `hidden md:flex`): `flex items-center gap-5 ml-8`. Each link: `text-base text-text-2 font-medium hover:text-text` — "Features" (`href="#features"`), "Security" (`href="#security"`).
- [ ] Spacer: `flex-1`.
- [ ] Actions: `flex items-center gap-2`.
  - Sign in: ghost button (`h-10 px-5`) — calls `signIn()`.
  - Create account: primary button (`h-10 px-5`) — calls `signUp()`.
- [ ] Authenticated redirect (FR already in current code): if `status === 'authenticated'`, `<Navigate to="/files" replace />` fires before anything renders.

### FR-003: Hero section

#### Description

The hero is centered text content — eyebrow pill, h1, lead paragraph, CTAs, reassurance line — followed by the app preview illustration.

#### Acceptance Criteria

- [ ] Section: `py-16 text-center` with `max-w-[1080px] mx-auto px-6`.
- [ ] **Eyebrow pill**: `inline-flex items-center gap-2 text-xs font-semibold tracking-wide text-accent-text bg-accent-soft border border-[#e0e3ff] rounded-full px-3 py-1.5 mb-5`.
  - Contains a 13×13 shield SVG (stroke, currentColor) and the text "Secure, per-user file storage on AWS".
- [ ] **Heading** `<h1>`: `text-[46px] leading-tight font-bold tracking-[-0.02em] max-w-[760px] mx-auto mb-5`. Two-part copy: "Your files in the cloud, " + `<span className="text-accent">scoped to you</span>.`
- [ ] **Lead** `<p>`: `text-lg text-text-2 max-w-[600px] mx-auto mb-8`. Copy: "Upload, organize, and share files in your own private space — and connect to shared project data when you need it. Backed by AWS, with isolation enforced at the infrastructure layer."
- [ ] **CTA row**: `flex gap-3 justify-center flex-wrap`.
  - "Create your account" → primary `Button`, `size="lg"` (height 46px, px-6, text-md — add `lg` to `Button` size prop in SPEC-028, or apply classes directly here).
  - "Sign in" → default `Button`, same `lg` size.
- [ ] **Reassurance line**: `flex gap-2 items-center justify-center mt-5 text-sm text-text-3`.
  - 14×14 checkmark SVG in `text-success`.
  - "Sign-in and sign-up are handled by AWS Cognito — we never see your password."

### FR-004: App preview illustration

#### Description

A static browser-chrome card below the hero that illustrates the file browser UI. It is decorative — `aria-hidden="true"` — and does not contain any real data or interactive elements.

#### Acceptance Criteria

- [ ] Container: `mt-10 mx-auto max-w-[920px] bg-surface border border-border rounded-lg shadow-lg overflow-hidden` with `aria-hidden="true"`.
- [ ] Browser chrome bar: `h-[38px] flex items-center gap-[7px] px-4 border-b border-border bg-surface-2`. Three dot "buttons" (non-interactive): `w-[11px] h-[11px] rounded-full bg-border`.
- [ ] Body: `grid grid-cols-[200px_1fr] min-h-[320px]`. On mobile (`sm:grid-cols-1`), collapse to single column with the sidebar hidden.
- [ ] **Sidebar** (left): `border-r border-border-2 p-4 bg-surface`. Section label: `text-xs font-semibold uppercase tracking-[.04em] text-text-3 px-2 pb-1`. Nav items: `flex items-center gap-2 px-2 py-[7px] rounded-sm text-text-2 text-sm`. Active item: `bg-accent-soft text-accent-text font-semibold`. Dot indicator: `w-[7px] h-[7px] rounded-full bg-current opacity-50`. Content: My Files (label) → "alice" (active item); Shared (label) → "Project Alpha", "Project Beta".
- [ ] **Main content** (right): `p-4 pl-5`. Rows are a CSS grid: `grid-cols-[22px_1fr_80px_90px] items-center gap-3 h-[42px] border-b border-border-2 text-sm`. Header row: `text-text-3 text-xs uppercase tracking-[.03em] font-semibold`. Data rows: folder (indigo SVG icon, `text-accent`), name `text-text font-medium`, size/date `text-text-3`. Four rows: one folder ("2026-q1") + three files ("annual-summary.pdf", "revenue-model.xlsx", "dataset-export.csv") with plausible sizes and dates.

### FR-005: Features section

#### Description

A three-column feature card grid below the hero.

#### Acceptance Criteria

- [ ] Section: `id="features"`, `py-10`, `max-w-[1080px] mx-auto px-6`.
- [ ] Section head: `text-center mb-8`. Heading `<h2>`: `text-[30px] font-bold tracking-[-0.01em]` — "Everything you need to manage your files". Sub-text: `text-text-2 text-md mt-3` — "A focused workspace — no clutter, just your files where you expect them."
- [ ] Grid: `grid grid-cols-1 md:grid-cols-3 gap-5`.
- [ ] Each card: `bg-surface border border-border rounded-lg p-6 shadow-sm`.
  - Icon block: `w-10 h-10 rounded-md bg-accent-soft text-accent grid place-items-center mb-4`. Contains a 20×20 SVG.
  - Card heading `<h3>`: `text-md font-semibold mb-2`.
  - Card body `<p>`: `text-text-2 text-sm`.
- [ ] Three cards (copy and icons from `docs/design/landing.html`):
  1. **Fast, resilient uploads** — upload-arrow SVG — "Drag and drop files up to several gigabytes. Large files switch to multipart upload automatically, with live progress for every file."
  2. **A space that's yours** — folder SVG — "Browse, organize into folders, rename, move, and download. Your space is private to you — no one else can see or touch it."
  3. **Connect to shared data** — link/chain SVG — "Link the shared project prefixes you have access to and work with them alongside your own files, all from one place."

### FR-006: CTA strip

#### Description

An accent-background strip that restates the security value prop and offers the sign-up / sign-in actions.

#### Acceptance Criteria

- [ ] Section: `id="security"`, `py-8 pb-10`, `max-w-[1080px] mx-auto px-6`.
- [ ] Inner box: `bg-accent rounded-lg text-white px-8 py-10 text-center shadow-md`.
- [ ] Heading `<h2>`: `text-[28px] font-bold tracking-[-0.01em] mb-3` — "Isolation enforced at the infrastructure layer".
- [ ] Body `<p>`: `text-[#dfe0fb] text-md max-w-[480px] mx-auto mb-6` — "Authentication runs on AWS Cognito and every user is scoped to their own storage by AWS IAM — not by application code. Get started in under a minute."
- [ ] CTA row: `flex gap-3 justify-center flex-wrap`.
  - "Create account": `bg-white text-accent-text border-white hover:bg-[#f3f4ff]`, `h-[46px] px-6 text-md font-semibold rounded-md` — calls `signUp()`.
  - "Sign in": `bg-white/10 text-white border border-white/40 hover:bg-white/20`, same height/padding — calls `signIn()`.
- [ ] These two buttons are specific enough to the CTA strip that they do not use the `Button` primitive — raw `<button>` elements with these one-off classes is acceptable here.

### FR-007: Footer

#### Description

A simple footer with brand and copyright.

#### Acceptance Criteria

- [ ] `<footer>`: `border-t border-border bg-surface`.
- [ ] Inner: `max-w-[1080px] mx-auto px-6 flex items-center gap-4 h-16`.
- [ ] Brand: `<BrandMark size="sm" />` linked to `/`.
- [ ] Spacer: `flex-1`.
- [ ] Meta: `text-text-3 text-sm` — "© 2026 FilePortal · " + links "Privacy" and "Terms" (`href="#"`, `text-text-2 hover:text-text`).

### FR-008: Username hint removed

#### Description

The username-format hint that existed on the minimal card (SPEC-022) is not present in the marketing page design. It is removed.

#### Acceptance Criteria

- [ ] No username-format hint text appears anywhere on the landing page.

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/
├── routes/
│   └── LandingPage.tsx     ← full rewrite
└── components/
    └── RootLayout.tsx       ← suppress Header on '/'
```

---

## Implementation Phases

### Phase 1: RootLayout route isolation

Update `RootLayout.tsx` to suppress `<Header />` on the `/` route. Verify that `/files` still shows the header and `/` does not.

#### Checkpoint

`npm run dev`: navigate to `/`. No app header. Navigate to `/files` — app header present.

### Phase 2: Nav + Hero (above the fold)

Build the sticky nav and the hero section (eyebrow, h1, lead, CTAs, reassurance line). Leave `AppPreview` as an empty placeholder `<div>` for now.

#### Checkpoint

The hero is centered and readable. CTAs call the existing `signIn`/`signUp` functions. The nav sticks on scroll.

### Phase 3: App preview illustration

Build the static `AppPreview` sub-component (browser chrome + sidebar + file rows).

#### Checkpoint

The preview card renders below the hero with the browser chrome dots, sidebar nav, and file rows at the correct sizes.

### Phase 4: Features section + CTA strip + Footer

Build the remaining three sections.

#### Checkpoint

Full page renders. `npm run test -w apps/portal` passes. On mobile viewport (≤ 768px): features stack to single column, preview sidebar hides.

---

## Open Questions

_None — design is fully specified in `docs/design/landing.html`._
