# Completed Spec — SPEC-192: Runtime Configuration & the Provider Block

## What was completed?

The SPA reads its configuration at **runtime**, from a same-origin `/config.json`, instead of the
`VITE_*` values Vite inlines at build time. Nothing a user can see changes. What ships is the
precondition for the rest of the arc: one artifact, promotable between environments without a
rebuild.

- `types/runtimeConfig.types.ts` — the document shape and the **20-key** classification (7 required,
  13 optional). `lib/runtimeConfig.ts` — `loadRuntimeConfig` / `configValue` /
  `missingRequiredConfig` / `isPortalConfigured` / `setRuntimeConfigDocument`, plus
  `RuntimeConfigNotLoadedError`.
- `lib/env.ts` is now the **dev fallback and nothing else**: `VITE_NAME` (the single list of variable
  names, with `PortalEnvVar` derived from it), the literal `readEnv` table, `devFallbackValue` and
  `warnIfMisconfigured`. `envVar`, `REQUIRED_ENV`, `OPTIONAL_ENV`, `missingRequiredEnv` and
  `isPortalConfigured` are gone; seven importers moved.
- `main.tsx` is a bootstrap — load → configure Amplify → `await import('./AppRoot')` → render — with
  five static imports and `components/BootFailure.tsx` for the failure. `AppRoot.tsx` holds the
  provider tree that used to live in `main.tsx`.
- `lib/amplify.ts` exports `configureAmplify()` and `isAmplifyConfigured()` as **functions**;
  `lib/s3Client.ts`'s `s3Client` const became `devS3Client()`; `fileBrowser.types.ts`'s
  `MAX_UPLOAD_BYTES` became `maxUploadBytes()` in a new `features/file-browser/uploadLimits.ts`.
- `deploy-app.yml` renders the document from the same repository variables it feeds the build and
  publishes it with `--cache-control no-store`, **refusing to publish one whose required keys are
  empty**. `infra/modules/app/cloudfront.tf` gives `/config.json` a `Managed-CachingDisabled`
  behaviour with the response-headers policy re-attached.
- The OIDC provider block (`OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_USERNAME_CLAIM`) is
  specified in `architecture.md` as the API's **verifier** configuration. No code, no infrastructure
  — SPEC-193 provisions it and SPEC-195 consumes it.

**Shipped as three PRs, and the order is the risk control.** #495 published the document while the
app still read the inlined values, so nothing in production depended on it; the deployed
`/config.json` was read back by hand before #496 made the app depend on it; #498 is the provider
block and this ritual. Reverting #496 alone restores a working bundle.

### Deliberate deviations

- **The spec's inventory was stale and is corrected here.** Measured against `main` at
  implementation time: `VITE_ARCHIVE_QUEUE_URL` was **already** in `lib/env.ts`, so FR-008's "this
  test fails today" no longer held — the agreement test ships green and keeps the gap closed rather
  than closing it. Arc A's `VITE_FILE_OPS_QUEUE_URL` had landed, making the document **20** keys, not
  nineteen (the end-of-arc figure of ten is unchanged — it joins group (b)). Eight enqueue services,
  not seven; **10** `notConfiguredMessage` paths, not seven; three ternary bucket picks, not two; and
  **25** moving code lines, not 23. A sixth `import.meta.env.VITE_*` site existed that the spec's
  five-file set did not cover — a JSDoc `@example` in `lib/enqueueFifo.ts`, updated rather than
  exempted.
- **`apiBaseUrl` gets no `VITE_*` variable.** The spec's Environment Variables section says "no new
  `VITE_*` variable", and nothing reads `apiBaseUrl` before SPEC-197, so a dev fallback for it would
  be dead weight in every `.env` file. It is rendered from a non-`VITE_` repository variable
  (`API_BASE_URL`) and its `VITE_NAME` entry is `null` — which makes the agreement test's single
  exemption **derived from the table** rather than hand-kept.
- **A CloudFront cache behaviour was added, which the spec put out of scope.** FR-001 assigns the
  `no-store` header to SPEC-194 and Out of Scope says this spec creates no infrastructure. It creates
  no new *resource type* and needs no deploy-role change, but the header alone cannot deliver FR-001
  AC5 on the interim static site: `Managed-CachingOptimized` applies its 1 s MinTTL **even against an
  origin `no-store`**, and an object that ever reaches the edge without the header takes the 24-hour
  DefaultTTL. The spec gained a criterion under FR-008 in the same change.
- **The `no-store` negative control is withdrawn, not deferred.** After that behaviour lands the edge
  caches nothing whether or not the object carries the header, and the loader's own `cache:'no-store'`
  stops the browser either way — so no observation distinguishes a present from a missing origin
  header. The header is verified by direct read. A check that cannot redden is not a check.
- **The bundle assertion is a CI step, not a Vitest test.** `npm run test` on a fresh clone has no
  `dist/`, and a test that skips when the artifact is missing reads as a pass. It runs after the
  build in `ci.yml` and hard-fails on a missing bundle.
- **`maxUploadBytes()` did not stay in `fileBrowser.types.ts`.** FR-006 fixes the shape, not the
  home; `*.types.ts` is type-only by convention and excluded from coverage.

## What changed from earlier specs?

- **`lib/env.ts`'s public surface is replaced** (SPEC-154's registry). Its call-time rule and the
  literal-member-expression constraint on `readEnv` survive unchanged and are still load-bearing.
- **`lib/amplify.ts` no longer configures itself at import** — the coupling `lib/env.ts`'s docstring
  cited as its own counter-example. `AuthProvider` reads `isAmplifyConfigured()` once per mount.
- **SPEC-106 wording, in two places that predated it.** `FilesPage` rendered
  "VITE_S3_USER_SPACE_BUCKET is not set. Add it to your .env file." to any user, and `AuthProvider`
  set "Authentication is not configured. Set the Cognito environment variables.", which `Header`
  rendered verbatim. Both advised setting variables a deployed portal no longer reads. They now come
  from `errorMessages.ts` (`SpaceUnavailable`, `RuntimeConfigUnavailable`).
- **`archive.service.ts`'s two degraded paths gained test rows.** `Archiving`/`Restoring is not
  configured` were absent from the shared `notConfiguredMessage` table, so FR-006's "a test per
  service still proves it" could not have held for them.
- **`lib/s3Client.ts`'s `s3Client` export is renamed** to `devS3Client()`; three test files mocked it.

## Help & guides

**Nothing to update, checked rather than assumed.** `helpContent.ts` names no `VITE_*` variable, no
`config.json`, and neither of the two error strings this spec rewrote. No label, route, flag or
affordance moved. The one new surface (`BootFailure`) is reachable only when the app cannot boot, and
documenting it in an in-app guide would put the explanation behind the failure it explains.

Two user-visible strings did change, both error states for conditions a production build cannot
reach: the file browser's configuration alert and the header's authentication-not-configured message.
Neither appears in any guide.

## Verification

Local: `format:check`, `lint`, `build` (`tsc -b`), the full suite (**2890 tests, exit 0**), coverage
92.9 / 89.1 / 92.4 / 94.8 against the 91/86/89/93 floors, `check:bundle` clean at 113 chunks,
`tofu fmt`, `validate_docs.py`. The infra plan was **0 to add, 1 to change in-place, 0 to destroy**.

Deployed and read back: `GET /config.json` returns 200 / `application/json` / `no-store` /
`version: 1` with all 20 keys, and a second request is still `x-cache: Miss from cloudfront`. After
the switchover the app boots with **one** `config.json` fetch per page load (Performance API), zero
console errors, and **no configuration alert** — which is the observable proving the document's four
Cognito values reached `Amplify.configure()`, since their absence renders one.

Owed, and not dischargeable from a signed-in session: the staged boot-failure and unparseable paths,
the promotion check, and a fresh sign-in from a private window. Recorded in
`docs/testing/arc-b-api-container-e2e.md` §A. Everything the container owns — the entrypoint's
rendering of the document, nginx's header, image promotion itself — belongs to SPEC-194's checks.

> **Read this beside the ledger, not on its own (2026-09-02).** The arc script was deleted when Arc B closed; its durable checks are `docs/testing/e2e.md` §4.18 and its results are in `docs/testing/sessions.md`. **[`owed.md`](../testing/owed.md) is authoritative for what has since been run** — several of the items below have been discharged, and this doc is a record of the day it shipped rather than a live status.

