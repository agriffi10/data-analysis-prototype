# Completed Spec - Browse Prefixes (SPEC-002)

## What was completed from this spec?

Full implementation of both spec phases: anonymous S3 client fallback, environment-variable-driven app wiring with a configuration error state, and breadcrumb root-prefix clamping.

**No new files created** — all changes are modifications to existing files.

**Test count on completion:** 31 tests across 3 files, all passing (3 new root-clamping tests added).

## What has changed?

### `src/lib/s3Client.ts`

- Credentials are now conditional: if `VITE_AWS_ACCESS_KEY_ID` is set, the S3 client is initialised with static credentials (same as SPEC-001). If the variable is absent or empty, the client is created with no `credentials` field, which causes the AWS SDK to use unsigned (anonymous) requests — suitable for publicly accessible buckets during local development.
- A comment documents that the anonymous mode is dev-only; production auth uses STS-issued credentials.

### `src/App.tsx`

- Reads `VITE_S3_BUCKET_NAME` and `VITE_S3_ROOT_PREFIX` from environment variables at module level.
- Normalises `VITE_S3_ROOT_PREFIX`: if non-empty and missing a trailing `/`, one is appended to prevent user error.
- Renders a styled `role="alert"` configuration error message (instead of a broken UI) when `VITE_S3_BUCKET_NAME` is not set.
- Passes `prefix={rootPrefix}` and `rootPrefix={rootPrefix}` to `FileBrowser` so the browser starts at and cannot navigate above the configured prefix.

### `src/features/file-browser/FileBrowser.tsx`

- `Props` type extended with optional `prefix?: string` (initial prefix; defaults to `''`) and `rootPrefix?: string` (navigation floor; defaults to the `prefix` prop value).
- Internal prefix state initialised from the `prefix` prop: `useState(prefixProp || undefined)`, so an empty string correctly resolves to `undefined` (bucket root).
- `buildBreadcrumbs` accepts a second `rootPrefix: string` argument:
  - When empty, behaves exactly as before (Home crumb → `undefined`).
  - When set, the leftmost crumb is the last path segment of `rootPrefix` and navigates to `rootPrefix`; only segments at or below `rootPrefix` are rendered; no `Home` crumb is shown.

### `src/features/file-browser/FileBrowser.test.tsx`

Three new tests added under the `root prefix clamping` suite:
1. Root prefix folder name appears as the leftmost crumb (not `Home`) and is `aria-current="page"` when at the root.
2. Navigating deeper shows only sub-segments, with no `Home` and the root prefix as a clickable button.
3. Clicking the root prefix crumb calls the hook with `rootPrefix`, not `undefined`.

### `.env.example`

Reordered and expanded to document `VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX` (with an inline example), and the anonymous credential fallback (empty `VITE_AWS_ACCESS_KEY_ID` = unsigned requests).
