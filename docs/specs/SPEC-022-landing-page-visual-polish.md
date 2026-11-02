---
type: Spec
id: SPEC-022
title: "Landing Page Visual Polish"
description: "Restyles the unauthenticated landing page as a centered auth gate with a brand mark, clear hierarchy, indigo accent, and the design system's type scale and button styles."
spec_status: Completed
depends_on: [SPEC-021]
---

## Overview

The landing page (`/`) is the first thing unauthenticated users see. It currently uses default Tailwind grays and lacks the design system's indigo accent, Inter type scale, and spacing rhythm. This spec updates `LandingPage.tsx` to match the design defined in `docs/design/landing.html` and `docs/design/design-system.md`: a centered, minimal auth gate with a brand mark, clear hierarchy, and the standard button styles.

## Scope

### In Scope

- Update `apps/portal/src/routes/LandingPage.tsx` to use design system token classes.
- Page layout: full-screen centered column on `bg-bg` canvas.
- Brand mark: the portal wordmark with the same rounded accent-square icon used in the header (see SPEC-023 for the shared icon pattern — reuse it here).
- Primary action (Sign in): `bg-accent text-white hover:bg-accent-hover`, height 36px, `rounded-md`, full-width up to 200px.
- Secondary action (Create account): `bg-surface border border-border text-text hover:bg-surface-2`, same dimensions.
- Description copy: `text-text-2 text-sm`.
- Username hint line: `text-text-3 text-xs`.
- Inline `<code>` elements in the hint line: `bg-surface-2 border border-border rounded-sm px-1 text-xs font-mono`.

### Out of Scope

- Changes to auth logic or routing.
- Any animation or transition beyond the button hover colors already present.
- Responsive breakpoint variants (the page works fine on all widths with max-width clamping).

---

## Functional Requirements

### FR-001: Page container

#### Description

The page must fill the viewport height and center its content both vertically and horizontally on the `bg-bg` canvas.

#### Acceptance Criteria

- [ ] The page root is `flex flex-col items-center justify-center min-h-screen bg-bg`.
- [ ] The content card is centered, max-width 384px (`max-w-sm`), with `text-center` alignment and `px-6` horizontal padding.

### FR-002: Brand mark

#### Description

A small brand mark appears above the heading: a 32×32 rounded accent square (indigo fill, `rounded-md`) containing a white icon (a simple upload arrow or the letter S), followed by the portal name as `text-md font-semibold text-text`.

#### Acceptance Criteria

- [ ] The mark is an SVG or `<div>` with `bg-accent rounded-md w-8 h-8`, centered inline.
- [ ] The wordmark below it reads "S3 File Portal" in `text-md font-semibold text-text`.
- [ ] The mark and wordmark are wrapped in a `flex flex-col items-center gap-3` container.

### FR-003: Heading and description

#### Description

A page heading and one-sentence description explain what the portal does.

#### Acceptance Criteria

- [ ] Heading: `text-xl font-semibold text-text` — "S3 File Portal" (or leave if the brand mark already serves as the name; in that case, omit the duplicate heading).
- [ ] Description: `text-sm text-text-2 mt-2` — "Securely upload and download files in your personal S3 space."

### FR-004: Button styles

#### Description

Sign in and Create account use the design system's primary and default button patterns.

#### Acceptance Criteria

- [ ] **Sign in** button: `bg-accent text-white text-base font-medium rounded-md px-4 h-9 w-full max-w-[200px] hover:bg-accent-hover disabled:opacity-45 disabled:cursor-not-allowed`.
- [ ] **Create account** button: `bg-surface border border-border text-text text-base font-medium rounded-md px-4 h-9 w-full max-w-[200px] hover:bg-surface-2 disabled:opacity-45 disabled:cursor-not-allowed`.
- [ ] Buttons are stacked vertically in a `flex flex-col items-center gap-3 mt-8` wrapper.
- [ ] Button text matches current labels ("Sign in", "Create account") — no copy changes.

### FR-005: Username hint

#### Description

The hint below the buttons that describes the username format constraint uses muted type and styled `<code>` tags.

#### Acceptance Criteria

- [ ] Hint text: `text-xs text-text-3 mt-4 leading-relaxed`.
- [ ] Each inline code token (`. _ @ -`) is wrapped in `<code className="bg-surface-2 border border-border rounded-sm px-1 font-mono text-xs">`.
- [ ] Copy matches the existing hint text.

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/routes/
└── LandingPage.tsx    ← sole file changed
```

---

## Implementation Phases

### Phase 1: Update LandingPage.tsx

Replace all Tailwind classes on every element in the file. Logic, routing, and click handlers are untouched — only the `className` props and JSX structure of the visual elements change.

Use this structure:

```tsx
<div className="flex min-h-screen flex-col items-center justify-center bg-bg px-6">
  <div className="w-full max-w-sm text-center">

    {/* Brand mark */}
    <div className="flex flex-col items-center gap-3 mb-8">
      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent">
        {/* white SVG icon */}
      </div>
      <span className="text-md font-semibold text-text">S3 File Portal</span>
    </div>

    <p className="text-sm text-text-2">
      Securely upload and download files in your personal S3 space.
    </p>

    <div className="mt-8 flex flex-col items-center gap-3">
      <button className="h-9 w-full max-w-[200px] rounded-md bg-accent px-4 text-base font-medium text-white hover:bg-accent-hover ...">
        Sign in
      </button>
      <button className="h-9 w-full max-w-[200px] rounded-md border border-border bg-surface px-4 text-base font-medium text-text hover:bg-surface-2 ...">
        Create account
      </button>
    </div>

    <p className="mt-4 text-xs text-text-3 leading-relaxed">
      Your username becomes your private file space: 3–63 characters,
      starts with a letter, lowercase letters, numbers, and underscores only.
    </p>

  </div>
</div>
```

#### Checkpoint

Run `npm run dev -w apps/portal` and open `/`. Verify:
- Background is light gray (`#f7f8fa`), not white.
- "Sign in" button is indigo, not gray/black.
- "Create account" button has a hairline border and white fill.
- Inter renders at 14px base.
- The brand mark accent square is visible above the name.

---

## Open Questions

_None — design is fully specified in `docs/design/landing.html`._
