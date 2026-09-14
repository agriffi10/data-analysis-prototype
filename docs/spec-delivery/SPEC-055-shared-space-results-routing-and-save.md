# Completed Spec — SPEC-055: Shared-Space Query Results Routing & Save

Makes the query workspace fully usable against a shared connection: results of a shared-DB
query land in the shared space (so collaborators see them), and Save-results can read from a
shared result and write into the user's own space **or** a shared space. Frontend-only — the
SPEC-050/056 membership-slot grants already cover write/list/copy on the shared space.
Delivered in one PR.

## What was completed?

- **Routing by connection kind (Phase 1, FR-001/002):** `resultOutputLocation(connection, username)`
  (query.service.ts) chooses the Athena `OutputLocation` — personal →
  `s3://{user-space}/{username}/athenaresults/` (unchanged, SPEC-034); shared →
  `s3://{shared-space}/{name}/athenaresults/{username}/`. `runQuery` gained an optional
  `outputLocation` param (defaults to personal, so internal DDL via `runStatementToCompletion`
  stays personal). `QueryWorkspace` resolves the **active connection** (not just its DB name)
  from `useConnections` + `useActiveDatabase` and passes the routed location. History records
  the active DB (already did) and the result `outputLocation` reflects the shared path. Results
  display is location-agnostic (Athena `GetQueryResults` by execution id) — no change needed.
- **Cross-bucket copy (Phase 2, FR-004):** `copyObject` (fileBrowser.service.ts) gained an
  optional `destBucket` (defaults to `bucket`); the collision HEAD + `CopyObjectCommand` target
  the destination bucket while `CopySource` stays the source bucket. Same-bucket callers
  (move/rename/copy-folder) are unchanged.
- **Save from/into shared (FR-003):** `SaveResultsDialog` gained a **destination-space selector**
  (personal first, then each shared space the user belongs to); the picker remounts per space
  (keyed) and excludes each space's protected `athenaresults/`. `QueryWorkspace`'s save derives
  the **source bucket** from the result's `outputLocation` (was hardcoded to the user space) and
  performs a same- or cross-bucket copy; collision warn-and-confirm carries both buckets. The
  "View in Files" deep-link is offered **only for personal-space saves** — see below.

Design decision (asked + recorded): a shared-destination save shows a plain success toast with
**no "View in Files" link**, because the Files browser only renders the personal space until
SPEC-057. No dead UI (mirrors SPEC-052 omitting entry points until their targets exist).

> **Superseded:** the condition lapsed when SPEC-057 let Files browse shared spaces, so a
> shared-space save now carries the link too, as `/files?space={id}&prefix={folder}`
> (`useSaveResults`; the toast is described in `docs/design/design-system.md` §6).

## What changed from earlier specs?

- **`runQuery`** (SPEC-034): optional `outputLocation`. **`copyObject`** (SPEC-019/039):
  optional `destBucket` (cross-bucket). **`SaveResultsDialog`** (SPEC-049): `bucket`/`rootPrefix`
  props replaced by a `spaces: DestinationSpace[]` list + a selector; `onSave` now returns
  `destBucket`. **`QueryWorkspace`:** routes results by active-connection kind and builds the
  Save destination list. **No IAM/infra change** — membership-slot grants (SPEC-050/056) already
  permit `PutObject`/`GetObject`/`ListBucket` on the shared space + the `athenaresults/`
  delete-deny.
- **Config:** `VITE_S3_SHARED_SPACE_BUCKET` (already in `.env.example`) is now **read by the app**,
  wired into `deploy-app.yml`, and the GH repo variable was set to `dat-prod-shared-space`
  (the `VITE_*` deploy lesson — a new var the app reads must be in the workflow build env AND a
  repo variable, or prod ships it undefined).

## Verification

`npm run lint` / `format:check` / `test` green (675 tests). Coverage: `resultOutputLocation`
picks shared vs personal; `runQuery` honors an explicit location; `copyObject` cross-bucket
(CopySource from source, write + collision-HEAD on dest); `SaveResultsDialog` space selector;
`QueryWorkspace` routes a shared query to the shared prefix, lists personal + shared Save
destinations, performs same- and cross-bucket saves (shared-dest omits the Files link), and a
copy error writes nothing + shows an error toast. e2e doc gains a SPEC-055 section (live checks).
Frontend deploys with the app bundle.
