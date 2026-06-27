# Spec: App Shell Visual Polish

**ID:** SPEC-023  
**Status:** Completed  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021

## Overview

The app shell — the topbar, root layout, and auth-loading state — is the persistent chrome that frames every page. Currently `Header.tsx` is a simple `border-b bg-white` bar with a text wordmark and plain sign-in/sign-out buttons. This spec replaces it with the design system's 56px topbar: a branded mark on the left, a right-side user zone (username label + initials avatar + sign-out ghost button), and a sign-in primary button for unauthenticated visitors. The root layout's body background and the protected layout's loading state are also updated.

## Scope

### In Scope

- `apps/portal/src/components/Header.tsx` — full visual update to match the design system topbar spec.
- `apps/portal/src/components/RootLayout.tsx` — use `bg-bg` for the root background; the header height no longer depends on implicit sizing.
- `apps/portal/src/components/ProtectedLayout.tsx` — replace the loading spinner's gray text with the design system's muted color; no structural change.
- Export a `BrandMark` sub-component (or inline it) from `Header.tsx` that renders the rounded accent square + wordmark — this exact element is also used by SPEC-022's landing page, so it should be extractable (move to `src/components/BrandMark.tsx` if sharing is convenient, or duplicate for now and note it in component-inventory).

### Out of Scope

- Sidebar / left nav — not built yet; deferred to a future spec when connections are implemented.
- Search field in the topbar — not yet functional; deferred.
- Help icon button in the topbar — not yet functional; deferred.
- Error banner inside the header — keep the existing red error alert but apply design token colors.

---

## Functional Requirements

### FR-001: Topbar height and background

#### Description

The header must be exactly 56px tall, stick to the top on scroll (position fixed is not required if the layout uses a flex column — the header simply doesn't scroll away), and sit on a `surface` background with a bottom hairline border.

#### Acceptance Criteria

- [ ] Header element has `h-14` (56px) and `bg-surface border-b border-border`.
- [ ] Inner flex container is `h-full px-4 flex items-center gap-4` — no arbitrary max-width constraint (the full-width topbar pattern from the design replaces the `max-w-4xl` currently in use).

### FR-002: Brand mark (left side)

#### Description

The left side of the topbar shows a 32×32 rounded accent square with a white upload-arrow SVG inside, followed by the wordmark "S3 File Portal" in `text-md font-semibold text-text`.

#### Acceptance Criteria

- [ ] Mark: `<div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent shrink-0">` containing a 16×16 white SVG icon.
- [ ] Wordmark: `<span className="text-md font-semibold text-text">S3 File Portal</span>`.
- [ ] Mark + wordmark are wrapped in `<div className="flex items-center gap-2">`.
- [ ] A suitable SVG: a simple upward-arrow (e.g. a chevron or outlined upload icon). Use an inline SVG with `stroke="currentColor"` and `className="text-white"`, 16×16, `stroke-width="2"`.

### FR-003: Spacer

#### Description

A `<div className="flex-1" />` separates the brand (left) from the user zone (right), as specified in the design system topbar pattern.

#### Acceptance Criteria

- [ ] The flex-1 spacer exists between the brand and the user zone.

### FR-004: Unauthenticated state — Sign in button

#### Description

When auth status is `unauthenticated`, show only the "Sign in" primary button on the right.

#### Acceptance Criteria

- [ ] Button: `bg-accent text-white text-base font-medium rounded-md px-4 h-9 hover:bg-accent-hover`.
- [ ] Label: "Sign in".
- [ ] No username or sign-out button is shown.

### FR-005: Authenticated state — user zone

#### Description

When auth status is `authenticated`, the right side shows the username label, an initials avatar, and a sign-out ghost button.

#### Acceptance Criteria

- [ ] Username label: `<span className="text-sm text-text-2">{user.username}</span>`.
- [ ] Avatar: a 32×32 circle (`h-8 w-8 rounded-full flex items-center justify-center text-xs font-semibold text-white`) with a gradient background (`bg-gradient-to-br from-accent to-accent-hover`). Displays the first two characters of the username, uppercased.
- [ ] Sign out button: ghost style — `text-sm font-medium text-text-2 hover:text-text hover:bg-surface-2 rounded-md px-3 h-8` — label "Sign out".
- [ ] All three are in a `flex items-center gap-3` wrapper.

### FR-006: Loading state

#### Description

While auth resolves (status `loading`), show a subtle indicator in the user zone rather than flashing buttons.

#### Acceptance Criteria

- [ ] A single `<span className="text-sm text-text-3" aria-hidden="true">&hellip;</span>` is shown in the right user zone.

### FR-007: Error banner

#### Description

The existing auth error banner below the topbar is kept but uses design token colors.

#### Acceptance Criteria

- [ ] Error banner: `border-t border-danger-soft bg-danger-soft px-4 py-2 text-center text-sm text-danger`.

### FR-008: RootLayout background

#### Description

The root layout's body background matches the design canvas color.

#### Acceptance Criteria

- [ ] `RootLayout.tsx` uses `bg-bg` on the outer wrapper div, not `bg-gray-50`.

### FR-009: ProtectedLayout loading state

#### Description

The loading screen shown while auth resolves uses muted design token color.

#### Acceptance Criteria

- [ ] Loading div uses `text-text-3`, not `text-gray-400`.

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/components/
├── Header.tsx           ← visual update
├── RootLayout.tsx       ← bg-bg update only
└── ProtectedLayout.tsx  ← text-text-3 update only
```

If the brand mark is extracted:
```
apps/portal/src/components/
└── BrandMark.tsx        ← new shared component (optional)
```

---

## Implementation Phases

### Phase 1: Update Header.tsx

Replace the JSX and all `className` props. Logic (signIn, signOut, status checks) is unchanged. Target structure:

```tsx
<header className="h-14 bg-surface border-b border-border">
  <div className="h-full px-4 flex items-center gap-4">

    {/* Brand */}
    <div className="flex items-center gap-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent shrink-0">
        <svg ...16×16 white upload icon... />
      </div>
      <span className="text-md font-semibold text-text">S3 File Portal</span>
    </div>

    <div className="flex-1" />

    {/* User zone */}
    <div className="flex items-center gap-3 text-sm">
      {/* loading / unauthenticated / authenticated states */}
    </div>

  </div>

  {/* Error banner */}
  {error && (
    <div className="border-t border-danger-soft bg-danger-soft px-4 py-2 text-center text-sm text-danger">
      {error}
    </div>
  )}
</header>
```

### Phase 2: Update RootLayout.tsx and ProtectedLayout.tsx

Two one-line class changes — straightforward.

#### Checkpoint

Run `npm run dev -w apps/portal`. Verify:
- Topbar is 56px, white surface, hairline bottom border.
- Brand mark: indigo accent square + "S3 File Portal" wordmark.
- Authenticated: username text, gradient avatar circle with initials, "Sign out" ghost button.
- Unauthenticated: only "Sign in" indigo button.
- Body background is `#f7f8fa` behind the topbar.
- `npm run test -w apps/portal` passes (existing Header tests check structure, not visual classes).

---

## Open Questions

_None._
