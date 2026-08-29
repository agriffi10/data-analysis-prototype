# Handoff — SPEC-198 PR 2 (the browser port)

**Written 2026-08-29.** Pick this up in a fresh session. It is self-contained: you should not need
to read the session that produced it.

---

## Where things are

**Branch:** `spec-198/browser-port`, in the worktree
`.claude/worktrees/spec-198-s3-surface`. HEAD is `309cad8c` (a WIP commit — see below), parent is
`6eb15c8e` = `origin/main`.

**PR 1 is merged and deployed.** [#543](https://github.com/agriffi10/data-analysis-prototype/pull/543)
landed the whole server-side surface: nine object routes, two presign routes, the free-name route,
the space/protection layer, the typed `params` transport, and both buckets' CORS. `Deploy
Infrastructure` and `Deploy Lambdas` went green, so the routes are **live in the account and called
by nothing**.

**PR 2 is roughly half done and its tests are red.** `npm run test` in `apps/portal`:
**2201 passing, 19 failing, exit 1.**

| Failing file | Count | Why |
|---|---|---|
| `src/features/saved-queries/savedQueries.service.test.ts` | 13 | its service calls `objectExists` / `deleteObject`, which are still on the SDK |
| `src/features/data-explorer/saveExploration.test.tsx` | 6 | same, one layer up |

**Every one of the 19 has the same single cause: `fileBrowser.service.ts` has not been ported yet.**
There is no second problem hiding behind them.

## The one thing to do next

**Port `apps/portal/src/features/file-browser/fileBrowser.service.ts`** (1064 lines, ~15 S3 call
sites, 1293-line test). Everything else in Phase 3a is already done and green. The call sites, from
`grep -n "new .*Command\|getSignedUrl\|new Upload"`:

| Function | Line | Route it becomes |
|---|---|---|
| `listFiles` | 80 | `objects.list` |
| `ensurePrefixMarker` | 182, 194 | `objects.exists` + `objects.writeContent` |
| `deleteObject` | 241 | `objects.delete` |
| `deleteObjects`, `deleteFolder`, `moveFolder`, `copyFolder` | 271–760 | **DELETED — see FR-002 below** |
| `copyObject` | 479 | `objects.copy` |
| `moveObject` | 497 | `objects.move` (ONE route, not copy-then-delete from the browser) |
| `getDownloadUrl` | 785–794 | `objects.downloadUrl` |
| `objectExists` | 811 | `objects.exists` |
| `folderExists` | 839 | `objects.list` with `MaxKeys: 1` — **note the route hard-codes 25; decide whether that matters** |
| `uploadFile` | 940 | `objects.uploadUrl` + `XMLHttpRequest` (Phase 3b) |
| `createFolder` | 1010 | `objects.writeContent` |
| `getObjectMetadata` | 1036 | `objects.metadata` |

`withAuthenticatedClient` (line 148) goes away — the credential retry moved server-side.

## What is already built and working — reuse it, do not reinvent

- **`apps/portal/src/lib/objectSpace.ts`** (new) — `spaceFor(bucket, key)` returns the `SpaceRef` the
  routes take, deriving the space name from the key's first segment. This is what lets nineteen
  call sites keep `bucket` in their signatures. There is also `spaceForRoot` for a listing prefix.
- **`apps/portal/src/lib/serviceResult.ts` → `fromApiFailure(error, fallback)`** (new) — use this,
  **never `toServiceError`, for an API failure.** `toServiceError` reads `e.message ?? fallback`, and
  `??` does not fall back on the empty string, which is exactly what `apiRequest` returns. Passing an
  API failure through it yields a blank message and drops the code.
- **`apps/portal/src/test/apiMock.ts`** (new) — programs `apiRequest` **by route id**, not by call
  order, so a service that stops calling a route cannot satisfy the mock. An unprogrammed route
  throws with a message naming what was programmed.
- **The six ported test suites** are the pattern to copy: `clientAdapters`, `queryServices`,
  `featureFlags`, `notifications`, `sharedSpaces`, `dataQuality`. `queryServices` is the best model —
  its whole port was rewriting one stateful `fakeBucket` helper, and its sixteen tests were untouched.

## Traps this port has already sprung — do not re-learn them

1. **`??` does not fall back on `''`.** See `fromApiFailure` above. This would have blanked every
   error message in the app.
2. **`readJsonDocument`'s `try/catch` around `parse` is load-bearing.** The port dropped it and a
   test caught it. `parse` is documented as total; the catch is the net under it, and it must keep
   using `toServiceError` so a parser bug surfaces the same message it always did.
3. **An empty object must reach `parse` as `undefined`, not `''`.** Every caller's parser is
   `raw ?? 'null'`; `JSON.parse('')` throws. This only shows up on a document nobody has written to
   yet. Already handled in `s3Json.ts` — preserve the same mapping anywhere else it applies.
4. **The space name is the key's FIRST SEGMENT.** A toy key like `k.json` derives a nonsense space.
   Use realistic keys (`alice/user_settings/x.json`) in tests.
5. **A route call is `(routeId, options)`.** Assertions go on `options.body` / `options.query`, never
   on an SDK command's `.input`.
6. **The bucket no longer travels.** Any assertion of the form `expect(input.Bucket)` has no
   successor — the API resolves the space from verified claims. Assert the route id and the derived
   space instead.

## What remains after `fileBrowser.service.ts`

**Phase 3b** (the rest of PR 2):
- `uploadFile` over `XMLHttpRequest`, and **assert an intermediate progress value** — a `fetch`
  implementation uploads correctly and leaves the bar at 0% until it jumps to 100%.
- Per-file URL minting in the upload queue (one `upload-url` per file, after that file's `start`).
- `maxUploadBytes()` in `uploadLimits.ts` clamped to 5 GiB — **not** a `MAX_UPLOAD_BYTES` constant.
- FR-010's five passthrough codes minted client-side from `{code, params}`, byte-identical wording.
- `abortSignal` threaded, **with SPEC-155 FR-006's superseded marker in the same commit** — aborting
  now stops the browser waiting, not the request on the wire.
- **FR-002's deletion**: `deleteObjects`, `deleteFolder`, `moveFolder`, `copyFolder`,
  `listAllKeysUnderPrefix`, `deleteInBatches`, `BULK_KEY_PAGE_SIZE`, `DELETE_BATCH_SIZE`, plus the
  `onProgress(processed, total)` shape — **and the three hooks that still call them**
  (`useDelete.ts:71,84`, `useMove.ts:109,191`, `useCopy.ts:145,238`). Andrew accepted the consequence
  on 2026-08-28: with `asyncFileOperations` off, folder operations become **unavailable** rather than
  synchronous. The `GATED_SURFACES` row and the rename/move/copy/delete Help guide must say so.
- Delete `buildCopySource` (`fileBrowser.service.ts:431`, used at 482) and the TypeScript
  `numberedName` in `useCopy.ts`.

**Then PR 3** (Phase 4b, the retirement) and **PR 4** (Phases 5–6, live checks and the completion
ritual). The full plan is at
`/private/tmp/claude-503/.../scratchpad/SPEC-198-implementation-plan.md` — **rev 3, twelve phases,
four PRs.** If that scratchpad is gone, the spec's own Implementation Phases plus this document are
enough; the plan's value was the PR grouping and the premises table, both summarised here.

## Process notes for whoever picks this up

- **Andrew's standing instruction (2026-08-28, twice):** once the plan's reviewers are done, build
  straight through. Do not stop for approval between phases. A summary that ends the turn reads as a
  request for approval, whatever it says.
- **Group phases into PRs**, cutting on dependency or risk class, not on phase boundary. PR 2 is
  Phases 3a+3b because it is the switchover — the only PR where user-visible behaviour changes.
- **Each PR still gets a fresh-context diff review before its push.** PR 1's review found four
  defects by planting them, three of which were vacuity in tests that already looked right.
- **Capture test names before any sweep.** The 159-name baseline for the seven affected files was
  taken at the start of this port; regenerate it with
  `npx vitest run --reporter=verbose <the seven files>` and diff names, never pass counts.
- **A mechanical splice damaged a test file during this port** (`sharedSpaces.service.test.ts` went to
  "no tests" and was reverted). Exact-string replacement only; never index-based splicing.

## Gates

From the repo root: `python3 -m pytest lambdas -q`, `ruff check lambdas/ scripts/ .github/scripts/`,
`python3 -m mypy`, `python3 scripts/validate_docs.py`, and `python3 scripts/generate_api_contract.py`
must produce no diff. From `apps/portal`: `npm run format:check`, `npm run lint`, `npm run build`
(the only typecheck), `npm run test`. **Check exit codes, not printed counts.** The worktree needs
`npm ci` once.
