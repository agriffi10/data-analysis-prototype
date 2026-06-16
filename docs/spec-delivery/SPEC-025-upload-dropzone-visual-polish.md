# Completed Spec - SPEC-025 Upload Dropzone Visual Polish

## What was completed from this spec?

`UploadDropzone.tsx` was restyled onto the design system (styling only):

- **Idle**: `rounded-lg border-2 border-dashed border-border bg-surface-2 p-8 text-center`
  with a new 32×32 arrow-up-in-circle SVG (`text-text-3`), headline "Drag a file here"
  (`text-sm font-medium text-text`), an "or **choose a file**" sub-line (link in
  `text-accent-text`), and the hint "Up to 5 GB per file · multipart handled automatically"
  (`text-xs text-text-3`).
- **Drag-over**: container gains `border-accent bg-accent-soft`; the icon shifts to
  `text-accent`. Transition is `transition-colors duration-150`.
- **Uploading**: container switches to `border-solid border-accent bg-accent-soft`;
  "Uploading… {progress}%" in `text-sm font-medium text-text`; a 6px (`h-1.5`) `bg-border`
  track with an `bg-accent rounded-full` fill (`transition-[width] duration-200`).
- **Disabled**: `pointer-events-none opacity-60`.

## What has changed?

Styling only — `onFile`/`progress`/`dragOver`/`inputRef` logic is unchanged. The
`role="progressbar"` + `aria-valuenow/min/max` attributes and the `aria-label="Upload file"`
hidden input are preserved, and the "choose a file" link text is unchanged (FileBrowser
tests assert its presence/absence by the `writable` flag).

The write-controls error banner referenced in FR Phase 2 was already migrated to
`danger-soft` tokens in SPEC-024, so no further change was needed there.

`lint`, `test` (225), and `build` all green.
