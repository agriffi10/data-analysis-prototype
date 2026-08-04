# Completed Spec — SPEC-144: Refresh Table — Schema Diff & Apply

## What was completed?

The back half of the refresh pipeline. A refresh now runs end to end: it classifies the change,
refuses a removal the user did not opt into, and rebuilds the table when there is something to do.
**Still not user-reachable** — SPEC-145 owns the browser surface.

- **`table-builder-diff-schema`** — `compute_diff` (pure, partition-key exclusion done *itself*),
  the `columns_removed` refusal, and the no-op short circuit. It emits the `unchanged` notification
  because no Lambda runs after it on that path.
- **`table-builder-apply-refresh`** — `DROP TABLE IF EXISTS` then `CREATE EXTERNAL TABLE`, back to
  back, followed by a post-condition `GetTable`.
- **`allowRemovals`** on the envelope, validated in `validate-authorize`.
- **A refresh-aware message layer** — mode-aware prefix and access-denied short-circuit, a refresh
  `success_message`, the `tokens` channel through `emit_failure`, and the `columns_removed` link.
- **`cpcommon.ddl`** gains `storage_from_definition`, `if_not_exists`, `table_properties`, `literal`
  and column `COMMENT` rendering; **`cpcommon.athena.run_ddl`** gains `client_request_token`;
  **`tbcommon.results`** holds the Athena output location both DDL verbs use.
- **ASL:** `DiffSchema` → `RouteByChange` → {`ApplyRefresh` | `RecordSuccess`}, `RecordSuccess`
  threads `$.status`, SPEC-143's `not_implemented` stub deleted, `DiffMissingSeed` added.
- **IAM:** `glue:DeleteTable`, scoped to the same resources as the existing Glue actions.
- Six PRs: #351, #354, #355, #356 (plus #350's ritual and the branch merge).

### Decisions worth carrying forward

- **The removal opt-in mechanism** — full entry in `docs/decisions.md`, including the two designs the
  spec rejected and the honest statement of what the guarantee is and is not.
- **Both DDL statements carry an Athena `ClientRequestToken`.** Without one, a Step Functions Retry
  after a transient error that arrived *after* submission re-runs the statement — on a DROP + CREATE
  pair, that is a retry dropping the table it just rebuilt. `cpcommon.athena.start_query` has carried
  this warning since SPEC-111; `run_ddl` never offered the parameter until now.
- **The two statements share ONE poll budget.** Two independent 240 s caps inside a 300 s function
  allowed 480 s, letting Lambda be killed *between* the drop and the create — table gone, and **no
  notification at all**, because the process dies before `notifies_on_failure` can run.
- **The post-condition compares a NAME SET, not a count** (see Deviations — the count was wrong).
  The read is **terminal, never transient**: the drop and create are committed, so a retryable
  verification would re-run the destructive pair because a *read* failed.
- **Carried properties beat the format default.** A capture is a fact about a table that exists; the
  default is a guess about one that does not. A headerless CSV table with `skip.header.line.count=0`
  must not come back with `1`.
- **Column comments are carried through the rebuild.** Inference returns names and types and has
  nothing to say about what a column *means*, so a comment is metadata only the old table holds.

### Deliberate deviations

- **FR-001's case-sensitive matching is REVERSED.** Its premise — that Athena treats `Amount` and
  `amount` as distinct — is not what this pipeline sees: the create path issues `CREATE EXTERNAL
  TABLE` through Athena, whose Hive-backed DDL folds column names, so a `Amount` header is stored as
  `amount`. Case-sensitively, **every column of every mixed-case table reads as both added and
  removed** on a folder where nothing changed — firing the data-loss warning over the user's whole
  schema — and it is unescapable, because opting in rebuilds with `Amount`, Athena folds it again,
  and the next refresh repeats it. Matching folds; names are still *reported* as they appear, and a
  true rename is still caught. **The premise is confirmed by the owed live check, not by a unit
  test** — we author the fixtures on both sides.
- **FR-006 AC1 was FALSE and is amended.** The Pipe invokes `StartExecution` as `FIRE_AND_FORGET`,
  so the FIFO `MessageGroupId` serializes *delivery*, not *execution*: two refreshes on one database
  can overlap, and a second one reaching `GetTable` inside the drop window sees `table_not_found`.
  Accepted and recorded (user decision) — refresh is not browser-reachable until SPEC-145.
- **`storage_from_definition` takes the create path's clause only when the capture REALLY IS that
  clause**, parameters included. Keying on the SerDe library alone would rebuild a tab-separated
  table with `separatorChar=','` and a Hive-JSON table with the OpenX SerDe.
- **FR-004's `table_properties` note about `portal.managed` was corrected** while building SPEC-143:
  `clone_definition` strips the marker, so it is re-emitted by the builder rather than reproduced
  from the capture.

## What changed from earlier specs?

- **SPEC-070:** `execute_ddl._results_location` moved to `tbcommon.results` so both DDL verbs use one
  construction; `RecordSuccess` threads `$.status` instead of hard-coding `"created"`.
- **SPEC-111:** `cpcommon.athena.run_ddl` gained `client_request_token`; `build_create_table_ddl`
  gained `if_not_exists`, `table_properties` and `COMMENT` rendering. Data-quality's generated DDL is
  **byte-identical** — verified across three formats plus the raw-line table.
- **SPEC-106/107:** `tbcommon.failure_message` takes `mode` and `tokens`; `emit_failure` forwards
  both and constructs the `columns_removed` link. **Every message that shipped before this spec is
  byte-for-byte unchanged**, pinned by a literal expectation table covering all 26 bodies.
- **SPEC-143:** `load-table-definition` now carries column comments on `existingColumns`.
- **SPEC-145 FR-005 was corrected** (see below).

## Verification

`ruff check lambdas/` clean; **1739 tests pass, 2 skipped**; `tofu fmt -check -recursive` and
`tofu validate` clean. Every PR merged on green with `main` confirmed green after each.

One correction worth recording because it was a *spec* error with a security-shaped consequence:
**SPEC-144 FR-009 and SPEC-145 FR-005 both claimed the `columns_removed` link was "URL-safe by
construction" because every component is a catalog-safe identifier.** The database and table are.
**Column names are not** — `infer-schema` reads them verbatim from a CSV header and nothing in the
plane validates them. Unencoded, `Order ID` puts a raw space in the URL, `&` invents a query
parameter and `#` truncates the rest into a fragment. Worse, SPEC-145 required re-validating each
name with `CATALOG_IDENTIFIER_RE`, which rejects `id`, `ts` and `Amount` — so for most real tables
the *whole* link would have been discarded and the dialog would have fallen back to abstract copy,
silently defeating the criterion it sits under. Names are now percent-encoded and both specs are
corrected.

**Owed live checks (none can be settled from a unit test):**

1. **FR-010's sequence** — build a table from a CSV folder, add a file with a new column, refresh and
   confirm it appears; remove a column, refresh and confirm the block, its named columns and the
   link; then refresh with the opt-in and confirm the column is gone.
2. **The casing premise** — build from a header carrying `Amount`, then `GetTable` and read back what
   Glue stored. If folded, FR-001's amendment is confirmed.
3. **FR-005 AC4** — `aws iam simulate-custom-policy` confirming the execution role can
   `glue:DeleteTable` and cannot delete any S3 object.

**Two exposures recorded rather than fixed** (user decision): the fire-and-forget overlap window
above, and a committed drop followed by exhausted retries notifying nobody — `notifies_on_failure`
stays quiet on `TransientError` by design and `RecordFailure` is a `Pass` with no notification path.
Both are pre-existing plane characteristics; the novelty is a destructive side effect.

No Help & guides change and no component-inventory row: nothing in `apps/portal/` changed, and
nothing is user-reachable until SPEC-145 (SPEC-074 FR-005).
