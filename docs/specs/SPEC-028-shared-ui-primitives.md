# Spec: Shared UI Primitives

**ID:** SPEC-028  
**Status:** Completed  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021

## Overview

The visual polish specs (SPEC-022–027) each repeat the same class strings for buttons, inputs, banners, and pills across every component file. This is intentional in the polish specs — it keeps each file self-contained during the restyle — but it leaves the codebase with duplicated style logic that will drift as the app grows.

This spec extracts those repeated patterns into a small set of typed, composable primitives in `src/components/`. Each primitive is a thin wrapper: it accepts a `variant` prop (or similar discriminant), assembles the correct class string, and forwards all standard HTML attributes and `ref`. No new visual design is introduced — the primitives codify exactly what the polish specs specify. Once the primitives exist, every consumer (landing page, header, dialogs, file browser) is updated to use them, eliminating the inline class repetition.

**When to implement:** After SPEC-022–027 are complete, so the primitive API is grounded in actual usage rather than speculation.

## Scope

### In Scope

The following primitives, all in `src/components/`:

| Component | Encapsulates |
|---|---|
| `Button` | Four variants: primary, default, ghost, danger |
| `IconButton` | Ghost icon-only circular/rounded button (close, row actions) |
| `Input` | Single-line text input with validation-error state |
| `Badge` | Neutral type pill (file/folder type labels) |
| `Banner` | Dismissible status banner: success, warning, danger, info |
| `BrandMark` | Accent-square icon + wordmark (used in Header + LandingPage) |

### Out of Scope

- Form primitives beyond `Input` (select, checkbox, radio) — not yet needed.
- A design-system Storybook or visual test harness — deferred.
- Any component that exists only in one place and has no reuse candidate (e.g. the file table row, the dropzone).
- Changes to hook or service logic.
- Any third-party component library (shadcn, Radix, etc.) — the stack is intentionally vanilla; these primitives are the lightweight alternative.

---

## Functional Requirements

### FR-000: `cx` utility

#### Description

A local class-name helper used by all primitives to merge base classes, variant classes, and caller-supplied `className` props.

#### Acceptance Criteria

- [ ] Located at `src/lib/cx.ts`, named export `cx`.
- [ ] Implementation:
  ```ts
  type CxArg = string | false | null | undefined;

  export function cx(...args: CxArg[]): string {
    return args.filter(Boolean).join(' ');
  }
  ```
- [ ] A co-located test `src/lib/cx.test.ts` verifies: filters falsy values, joins truthy strings, returns empty string for all-falsy input.
- [ ] No external dependency is added.

### FR-001: Button

#### Description

A single `<Button>` component that accepts a `variant` prop and renders the correct design-system class combination. All standard `<button>` attributes pass through via rest props.

#### Acceptance Criteria

- [ ] Located at `src/components/Button.tsx`, named export `Button`.
- [ ] Props:
  ```ts
  type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: 'primary' | 'default' | 'ghost' | 'danger';
    size?: 'sm' | 'md';  // sm = h-8 px-3 text-sm; md = h-9 px-4 text-base (default)
  };
  ```
- [ ] `variant` defaults to `'default'` when omitted.
- [ ] Class mapping:
  - `primary`: `bg-accent text-white hover:bg-accent-hover`
  - `default`: `bg-surface border border-border text-text hover:bg-surface-2`
  - `ghost`: `text-text-2 hover:bg-surface-2 hover:text-text`
  - `danger`: `bg-danger text-white hover:bg-danger/90`
- [ ] All variants share: `rounded-md font-medium inline-flex items-center justify-center gap-2 disabled:opacity-45 disabled:cursor-not-allowed transition-colors`.
- [ ] `size="sm"` adds `h-8 px-3 text-sm`; `size="md"` (default) adds `h-9 px-4 text-base`.
- [ ] `className` prop merges with the generated classes (additional classes win on conflict — use `clsx` or a simple concatenation; see note below).
- [ ] The component is a `forwardRef` so callers can attach a ref (e.g. the Cancel button `cancelRef` in `DeleteConfirmDialog`).
- [ ] A test file `Button.test.tsx` verifies: renders with each variant, forwards `disabled`, forwards `onClick`, applies `className` additions.

**Note on class merging:** The app uses a local `cx` utility (see FR-000) instead of `clsx` or `tailwind-merge`. All primitives import `cx` from `src/lib/cx.ts`.

### FR-002: IconButton

#### Description

A ghost icon-only button — square, rounded — used for close buttons and row action buttons where only an SVG icon is shown (no text label).

#### Acceptance Criteria

- [ ] Located at `src/components/IconButton.tsx`, named export `IconButton`.
- [ ] Props:
  ```ts
  type IconButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
    size?: 'sm' | 'md';  // sm = h-7 w-7; md = h-8 w-8 (default)
    label: string;       // required; applied as aria-label
  };
  ```
- [ ] Base classes: `inline-flex items-center justify-center rounded-md text-text-3 hover:bg-surface-2 hover:text-text disabled:opacity-45 disabled:cursor-not-allowed transition-colors`.
- [ ] `size="sm"` → `h-7 w-7`; `size="md"` → `h-8 w-8`.
- [ ] `label` prop sets `aria-label` (the visible children are the icon — `aria-label` is the accessible name).
- [ ] `forwardRef`.

### FR-003: Input

#### Description

A single-line text input with built-in error state styling and associated error message.

#### Acceptance Criteria

- [ ] Located at `src/components/Input.tsx`, named export `Input`.
- [ ] Props:
  ```ts
  type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
    error?: string | null;   // when set, shows error message + invalid ring
    label?: string;          // if provided, renders a <label> above the input
    id?: string;             // wired to label htmlFor and error aria-describedby
  };
  ```
- [ ] Input base classes: `w-full rounded-md border border-border bg-surface px-3 h-9 text-base text-text placeholder:text-text-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:border-accent disabled:opacity-45 transition-colors`.
- [ ] When `error` is set: border becomes `border-danger`, ring becomes `ring-danger/40`; `aria-invalid="true"` is set.
- [ ] Error message renders as `<p className="mt-1.5 text-xs text-danger" role="alert" id="{id}-error">` when `error` is set.
- [ ] `label` prop renders `<label htmlFor={id} className="block text-sm font-medium text-text mb-1.5">` above the input when provided.
- [ ] `forwardRef`.
- [ ] Test: renders label, error message, aria-invalid when error is set.

### FR-004: Badge

#### Description

A neutral pill label for file/folder type indicators in the file table. Single appearance — no variants needed.

#### Acceptance Criteria

- [ ] Located at `src/components/Badge.tsx`, named export `Badge`.
- [ ] Props: `React.HTMLAttributes<HTMLSpanElement>` (children = label text, e.g. "PDF", "Folder").
- [ ] Classes: `inline-flex items-center rounded-full bg-surface-2 border border-border px-2 py-0.5 text-xs font-medium text-text-2`.
- [ ] No `forwardRef` needed (non-interactive).

### FR-005: Banner

#### Description

A dismissible status banner for inline success/warning/danger/info feedback. Used in multiple places in `FileBrowser.tsx` (delete result, move result, download error, write error) and potentially elsewhere.

#### Acceptance Criteria

- [ ] Located at `src/components/Banner.tsx`, named export `Banner`.
- [ ] Props:
  ```ts
  type BannerProps = {
    variant: 'success' | 'warning' | 'danger' | 'info';
    title?: string;            // bold first line (optional)
    children: React.ReactNode; // body content
    onDismiss?: () => void;    // if provided, renders a Dismiss button
    role?: 'alert' | 'status'; // defaults to 'alert'
    className?: string;
  };
  ```
- [ ] Variant class mapping:
  - `success`: `bg-success-soft border-success-soft text-success`
  - `warning`: `bg-warning-soft border-warning-soft text-warning`
  - `danger`: `bg-danger-soft border-danger-soft text-danger`
  - `info`: `bg-accent-soft border-accent-soft text-accent-text`
- [ ] Container: `rounded-lg border p-3 text-sm flex items-start gap-3 {variantClasses}`.
- [ ] `title` renders as `<p className="font-medium">{title}</p>` before `children`.
- [ ] Dismiss button (when `onDismiss` provided): right-aligned `text-xs font-medium opacity-70 hover:opacity-100 hover:underline ml-auto shrink-0` — label "Dismiss".
- [ ] No `forwardRef` needed.
- [ ] Test: renders each variant, shows dismiss button when `onDismiss` provided, calls `onDismiss` on click.

### FR-006: BrandMark

#### Description

The rounded accent square + wordmark used in both `Header` (SPEC-023) and `LandingPage` (SPEC-022). Extracted so both callers reference one definition.

#### Acceptance Criteria

- [ ] Located at `src/components/BrandMark.tsx`, named export `BrandMark`.
- [ ] Props:
  ```ts
  type BrandMarkProps = {
    size?: 'sm' | 'md';   // sm = 24px square + text-base; md = 32px square + text-md (default)
    showWordmark?: boolean; // default true
    className?: string;
  };
  ```
- [ ] Renders the `bg-accent rounded-md` square with the white upload-arrow SVG icon, followed by "S3 File Portal" wordmark if `showWordmark` is true.
- [ ] `size="sm"` → `h-6 w-6` square, `text-base` wordmark. `size="md"` → `h-8 w-8` square, `text-md` wordmark.
- [ ] The upload-arrow SVG is the same one defined in SPEC-023.
- [ ] The outer wrapper is `flex items-center gap-2`.

### FR-007: Consumer updates

#### Description

Once the primitives exist, every caller from SPEC-022–027 is updated to import and use them, eliminating all inline repetition of button/input/badge/banner/brand-mark class strings.

#### Acceptance Criteria

- [ ] `LandingPage.tsx` uses `<Button variant="primary">` and `<Button variant="default">` and `<BrandMark>`.
- [ ] `Header.tsx` uses `<Button variant="primary">` (sign in), `<Button variant="ghost">` (sign out), `<IconButton>` is not needed here (no icon-only buttons), and `<BrandMark>`.
- [ ] `FileBrowser.tsx` uses `<Button>` for all toolbar and selection-bar buttons, `<Banner>` for all dismissible result/error banners, `<Badge>` for type pills in `FileRow`.
- [ ] `CreateFolderDialog.tsx`, `RenameDialog.tsx`, `MoveDialog.tsx` use `<Button>` and `<Input>`.
- [ ] `DeleteConfirmDialog.tsx` uses `<Button variant="ghost">` (Cancel) and `<Button variant="danger">` (Delete).
- [ ] `CollisionPrompt.tsx` uses `<Button>` for all three action buttons.
- [ ] `MetadataPanel.tsx` uses `<IconButton>` for the close button.
- [ ] No bare `<button>` or `<input>` with design-system class strings remain in any of those files (only primitives or intentionally-unstyled elements such as the hidden file input in `UploadDropzone`).
- [ ] All existing tests still pass after the refactor.

---

## Data Model

```ts
// src/components/Button.tsx
export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md';

// src/components/Banner.tsx
export type BannerVariant = 'success' | 'warning' | 'danger' | 'info';
```

---

## API / Interface Contract

Example usage after this spec:

```tsx
// Dialogs
<Button variant="ghost" onClick={onCancel} disabled={isBusy}>Cancel</Button>
<Button variant="danger" onClick={onConfirm} disabled={isDeleting}>
  {isDeleting ? 'Deleting…' : 'Delete'}
</Button>

// Toolbar
<Button variant="default" onClick={() => setCreatingFolder(true)} disabled={isBusy}>
  New folder
</Button>
<Button variant="primary" onClick={openUpload}>Upload</Button>

// Inline input
<Input
  id="new-folder-name"
  value={name}
  onChange={e => setName(e.target.value)}
  error={showError ? validationError : null}
  label="New folder name"
  autoFocus
/>

// File type pill
<Badge>PDF</Badge>

// Dismissible banner
<Banner variant="danger" onDismiss={dismissError}>
  Could not download {file.name}: {error}
</Banner>

// Success with title
<Banner variant="success" role="status" onDismiss={del.dismissSummary}
  title={`Deleted ${del.summary.deletedCount} items.`}>
  {del.summary.errors.length > 0 && <ul>...</ul>}
</Banner>

// Brand mark
<BrandMark />               // in Header (md, with wordmark)
<BrandMark size="md" />     // in LandingPage
```

---

## File & Folder Structure

```
apps/portal/src/lib/
├── cx.ts              ← new
└── cx.test.ts         ← new

apps/portal/src/components/
├── BrandMark.tsx      ← new
├── Button.tsx         ← new
├── Button.test.tsx    ← new
├── Banner.tsx         ← new
├── Banner.test.tsx    ← new
├── Badge.tsx          ← new
├── IconButton.tsx     ← new
├── Input.tsx          ← new
├── Input.test.tsx     ← new
├── Header.tsx         ← updated (uses Button, BrandMark)
├── ProtectedLayout.tsx← no change needed
└── RootLayout.tsx     ← no change needed

apps/portal/src/features/file-browser/
├── FileBrowser.tsx         ← updated (uses Button, Badge, Banner)
├── CreateFolderDialog.tsx  ← updated (uses Button, Input)
├── CollisionPrompt.tsx     ← updated (uses Button)
├── DeleteConfirmDialog.tsx ← updated (uses Button)
├── RenameDialog.tsx        ← updated (uses Button, Input)
├── MoveDialog.tsx          ← updated (uses Button)
└── MetadataPanel.tsx       ← updated (uses IconButton)

apps/portal/src/routes/
└── LandingPage.tsx         ← updated (uses Button, BrandMark)
```

---

## Implementation Phases

### Phase 1: `cx` utility + Button, IconButton, Badge

Start with `cx` (FR-000) — it's a prerequisite for all primitives. Then build and test Button, IconButton, and Badge.

#### Checkpoint

`npm run test -w apps/portal` — new `Button.test.tsx` passes. Spot-check by temporarily using `<Button variant="primary">Test</Button>` in `LandingPage.tsx` and confirming the indigo button renders correctly in the dev server.

### Phase 2: Primitives — Input, Banner, BrandMark

Build these three. `Input` and `Banner` have the most test surface area.

#### Checkpoint

`Button.test.tsx`, `Input.test.tsx`, `Banner.test.tsx` all pass. Confirm `Banner variant="danger"` renders `bg-danger-soft` and the Dismiss button calls `onDismiss`.

### Phase 3: Consumer updates

Update all six component files (LandingPage, Header, FileBrowser, dialogs, MetadataPanel) to import and use the primitives. Work file by file; run tests after each to catch regressions early.

#### Checkpoint

`npm run test -w apps/portal` — all tests pass. `npm run build -w apps/portal` — no TypeScript errors. Open the dev server and exercise: create folder, delete, move, download, open metadata panel — all visual styles match what was established in SPEC-022–027.

---

## Open Questions

_None — the `cx` approach is decided (local utility, no external dependency)._
