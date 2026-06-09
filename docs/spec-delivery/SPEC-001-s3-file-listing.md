# Completed Spec - S3 File Listing (SPEC-001)

## What was completed from this spec?

Full implementation of the S3 file listing feature across all three phases: data/service layer, React hook, and UI component.

**New files created:**

| File | Purpose |
|---|---|
| `src/types/s3.types.ts` | Shared types: `S3FileItem`, `S3FolderItem`, `S3Item`, `FileList`, `ServiceResult<T>` |
| `src/lib/s3Client.ts` | Singleton `S3Client` initialised from `VITE_AWS_*` env vars |
| `src/features/file-browser/fileBrowser.service.ts` | `listFiles(bucket, prefix?)` — calls `ListObjectsV2` with `/` delimiter, normalises files and folders, sorts folders then files alphabetically, never throws (returns `ServiceResult`) |
| `src/features/file-browser/fileBrowser.service.test.ts` | 7 unit tests covering happy path, sorting, prefix-key exclusion, empty/undefined responses, SDK error, and correct command input |
| `src/features/file-browser/useFileBrowser.ts` | `useFileBrowser(bucket, prefix?)` hook — returns `{ files, folders, isLoading, error, refresh }`, fetches on mount and on `prefix` change, cancels stale in-flight requests on cleanup |
| `src/features/file-browser/useFileBrowser.test.ts` | 7 unit tests covering loading state, success, error, prefix change re-fetch, `refresh()`, loading-during-refresh, and error recovery |
| `src/features/file-browser/FileBrowser.tsx` | Component with breadcrumb navigation, loading/error/empty/populated states, folder drill-down, and human-readable file size and date |
| `src/features/file-browser/FileBrowser.test.tsx` | 14 render tests across loading, error, empty, populated, drill-down, and breadcrumb suites |
| `src/features/file-browser/index.ts` | Barrel export for `FileBrowser`, `useFileBrowser`, `UseFileBrowserResult` |
| `.env.example` | Documents `VITE_AWS_REGION`, `VITE_AWS_ACCESS_KEY_ID`, `VITE_AWS_SECRET_ACCESS_KEY`, `VITE_S3_BUCKET_NAME` |

**Dependencies added:**

| Package | Type | Purpose |
|---|---|---|
| `@aws-sdk/client-s3` | runtime | S3 SDK v3 modular client |
| `tailwindcss` | dev | Utility-first CSS |
| `@tailwindcss/vite` | dev | Tailwind v4 Vite plugin |
| `vitest` | dev | Test runner |
| `@vitest/ui` | dev | Vitest UI mode |
| `@testing-library/react` | dev | React hook and component testing |
| `@testing-library/jest-dom` | dev | DOM assertion matchers |
| `jsdom` | dev | Browser-like environment for tests |

**Test count on completion:** 28 tests across 3 files, all passing.

## What has changed?

This is the first spec — no prior delivery to change. The following existing scaffold files were modified:

- **`src/App.tsx`** — replaced the Vite default scaffold with a `<FileBrowser bucket={import.meta.env.VITE_S3_BUCKET_NAME} />` render.
- **`src/index.css`** — prepended `@import "tailwindcss"` to activate Tailwind alongside the existing global styles.
- **`vite.config.ts`** — added the `@tailwindcss/vite` plugin; switched `defineConfig` import from `vite` to `vitest/config` so the `test` configuration block type-checks correctly under `tsconfig.node.json`.
- **`tsconfig.app.json`** — added `"vitest/globals"` to `types` so test globals (`describe`, `it`, `expect`, etc.) are available in `src/` without explicit imports.
- **`package.json`** — added `test` and `test:ui` scripts.
