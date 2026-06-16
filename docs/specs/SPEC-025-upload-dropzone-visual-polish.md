# Spec: Upload Dropzone Visual Polish

**ID:** SPEC-025  
**Status:** Draft  
**Last Updated:** 2026-06-16  
**Depends On:** SPEC-021

## Overview

The upload dropzone (`UploadDropzone.tsx`) currently uses generic Tailwind blue/gray classes and lacks the visual treatment defined in the design system. This spec updates it to match the design: a dashed-border drop target that shifts to indigo on hover/drag-over, a 6px accent progress bar with percentage, and the correct muted + accent-text typography. The write-controls wrapper in `FileBrowser.tsx` (the "New folder" button toggle row) is also aligned to design system button styles — this work was partially done in SPEC-024 but the dropzone area itself is deferred here.

## Scope

### In Scope

- `apps/portal/src/features/file-browser/UploadDropzone.tsx` — all JSX and `className` props.
- The write-controls area in `FileBrowserContent` (the `{writable && ...}` block in `FileBrowser.tsx`) — specifically the error alert banner and the spacing/layout of the dropzone within it. (Button styling was handled in SPEC-024 FR-002.)

### Out of Scope

- Multi-file queue / SPEC-020 upload drawer — that is a new component, not a restyle of this one.
- Any changes to `useFileUpload` hook logic.

---

## Functional Requirements

### FR-001: Dropzone idle state

#### Description

When no upload is in progress, the dropzone is a dashed-border box with neutral background, upload icon, headline, "browse" link, and a hint line.

#### Acceptance Criteria

- [ ] Container: `rounded-lg border-2 border-dashed border-border bg-surface-2 p-8 text-center transition-colors`.
- [ ] No upload icon currently exists — add a 32×32 centered upload SVG (cloud-with-arrow-up or simple arrow-up circle) in `text-text-3` above the text.
- [ ] Headline: `text-sm font-medium text-text mt-3` — "Drag a file here".
- [ ] Sub-line with "browse" link: `text-sm text-text-2 mt-1` — "or{' '}<button ...>choose a file</button>".
- [ ] "choose a file" link: `text-accent-text font-medium hover:underline disabled:opacity-45 disabled:cursor-not-allowed` (no button border/background — looks like a text link).
- [ ] Hint line: `text-xs text-text-3 mt-2` — "Up to 5 GB per file · multipart handled automatically".

### FR-002: Dropzone drag-over state

#### Description

When a file is dragged over the dropzone, the border shifts to accent and the fill shifts to `accent-soft`.

#### Acceptance Criteria

- [ ] `dragOver` state adds `border-accent bg-accent-soft` and removes `border-border bg-surface-2` (use conditional class merging, not inline style).
- [ ] The transition is `transition-colors duration-150`.
- [ ] The icon color shifts to `text-accent` when `dragOver` is true.
- [ ] `disabled` state: `opacity-60 pointer-events-none` on the outer container.

### FR-003: Upload in-progress state

#### Description

While uploading, the dropzone shows the filename (if available), a progress percentage, and an accent progress bar.

#### Acceptance Criteria

- [ ] Container switches to `border-solid border-accent bg-accent-soft` while `uploading` is true.
- [ ] Progress percentage: `text-sm font-medium text-text mt-3` — "Uploading… {progress}%".
- [ ] Progress bar track: `mt-3 w-full h-1.5 rounded-full bg-border overflow-hidden`.
- [ ] Progress bar fill: `h-full rounded-full bg-accent transition-[width] duration-200` with `style={{ width: \`${progress ?? 0}%\` }}`.
- [ ] The ARIA `role="progressbar"` and `aria-valuenow`/`aria-valuemin`/`aria-valuemax` attributes are preserved from the current implementation.

### FR-004: Upload icon SVG

#### Description

The upload icon above the dropzone text is a clean, inline SVG — no external library.

#### Acceptance Criteria

- [ ] A 32×32 outlined cloud-with-arrow or arrow-up SVG is centered above the headline.
- [ ] Uses `stroke="currentColor"` with `className="h-8 w-8 mx-auto"` and inherits color from the container (idle: `text-text-3`, drag-over: `text-accent`, uploading: `text-accent`).
- [ ] Suggested SVG (arrow-up in circle, 32×32):

```tsx
<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5"
     className="h-8 w-8 mx-auto" aria-hidden="true">
  <circle cx="16" cy="16" r="13" />
  <path strokeLinecap="round" strokeLinejoin="round" d="M16 21v-9m0 0l-3 3m3-3l3 3" />
</svg>
```

---

## Data Model

_No new TypeScript types._

---

## File & Folder Structure

```
apps/portal/src/features/file-browser/
└── UploadDropzone.tsx    ← visual update
```

---

## Implementation Phases

### Phase 1: Update UploadDropzone.tsx

Replace all Tailwind classes. The upload icon SVG is added. Logic (`onFile`, `progress`, `dragOver` state, `inputRef`) is untouched.

#### Checkpoint

`npm run dev`: open the files page. The dropzone should show a soft gray dashed box at rest. Drag a file over it — border turns indigo, fill turns indigo-tint. Upload a small file — the progress bar fills in accent, then the dropzone returns to idle.

### Phase 2: Verify write-controls error banner

The write error alert (`writeError`) inside `FileBrowserContent` uses `bg-danger-soft border-danger text-danger` classes (these were styled in SPEC-024; verify they are consistent with the dropzone container).

#### Checkpoint

`npm run test -w apps/portal` passes (UploadDropzone tests check structure/ARIA, not visual classes).

---

## Open Questions

_None._
