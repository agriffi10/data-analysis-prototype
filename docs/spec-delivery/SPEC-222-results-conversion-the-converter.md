# Completed Spec — SPEC-222: Results Conversion, the Converter, the Three Writers & the Notification

## What was completed?

The plane stops ending at a placeholder. `Convert` reads a finished execution's result object
onto the function's own disk, types every column from the execution's metadata, writes one file
as Parquet, NDJSON or Excel, and uploads it under a conditional write; `Notify` says what
happened once, with a link to the folder. Still nothing a user can reach — the browser surface
is SPEC-223 — so the route is live and unflagged and no UI enqueues into it.

- **`rccommon.types`** — the Athena-type-to-polars-dtype table, closed over Athena's documented
  DML vocabulary. It refuses rather than falling back, because a closed vocabulary with a
  fallback is where an unmodelled type quietly becomes the wrong column.
- **`rccommon.parquet_footer`** — a written file's row count and compression codec, read from its
  trailer by seeking. polars 1.12 exposes no metadata reader, and counting rows through polars
  would have forced the streaming guard to narrow from "no frame is ever materialised" to a
  sweep over two function names that a helper walks straight past.
- **`rccommon.links`** — the in-app path the notification carries.
- **`rc_convert`** and **`rc_notify`**, the machine's `Convert → Converted → ConversionOutcome →
  Notify` path, and `ConvertRefusedSeed` for the refusals that route out through the failure
  terminal.
- **The execution role's first write**: `s3:PutObject` + `s3:AbortMultipartUpload` on the two
  space buckets, under the existing Deny on every app-managed folder.
- **`lambdas/fixtures/athena_result_all_types.*`** — a real captured execution, and
  `lambdas/test_image_requirements.py`, which couples the requirements files on disk to the two
  places `lambdas/Dockerfile` names each one.

### Deliberate deviations

- **Excel's 16,384-column ceiling is not a refusal this plane makes**, because it can never
  fire. The described columns ride on a Step Functions state capped at 256 KB, which a realistic
  column entry fills between about 2,500 and 6,400 columns — measured. A check at 16,384 would
  be a fence that stops nobody, so the cap is the transport's, lives in `describe-results`, and
  applies to every format. FR-004 was amended.
- **FR-003's round-trip criterion was false in both directions** and was rewritten. `date`, the
  one exception it named, is the type that *does* survive; five others (`tinyint`, `smallint`,
  `int`, `real`, `decimal`) do not, each because JSON carries no integer or float width and
  because the spec itself requires a decimal to be written as a string.
- **`Convert` retries on `TransientError` alone, once**, unlike every other Task here. The four
  Lambda service errors cover a response lost *after* the function completed, and a
  re-invocation then meets its own conditional `PutObject` and reports `destination_occupied`
  for a save that succeeded.
- **The per-format size cap** replaced the single `RESULTS_MAX_BYTES`. Excel's peak memory is a
  measured 23–32× the CSV because it cannot stream, so one number would either starve Parquet or
  promise an Excel conversion that runs out of memory two thirds of the way through.

## What changed from earlier specs?

- **`describe-results` carries `precision` and `scale`.** Athena reports a decimal's type as bare
  `decimal` and puts the parameters in sibling fields — captured, not assumed — so the verb was
  dropping the only copy of them. It is inside `columns`, which the `Described` Pass names
  opaquely, so no ASL moved.
- **`system_settings` joined the refused destinations**, which SPEC-219 wrote into this spec's
  dependencies: the role denies `*/system_settings/*` in both buckets, so with a write grant in
  hand a destination inside it would have reached the user as a bare `AccessDenied`. The refused
  set became a **superset** of the browser's picker rather than equal to it — the equality
  contradicted the rule `rccommon.paths` already stated, that the validator mirrors the Deny.
- **`check_prefix` refuses control characters**, as `check_filename` always did.
- **`rccommon` joined the mypy ratchet**, late; it entered at zero.
- **`docker-lambda` gained `ephemeral_storage_mb`**, declared statically for every function.

## Verification

`pytest lambdas/` green by exit code (2,912 passed, 90.10%), `ruff`, `mypy`, the three
validators, `tofu validate`, `tofu fmt -check -recursive`, and the portal's formatter, linter,
build and tests. Four fresh-context review frames — the plan, the PR grouping, and the diff
three times — the third spent deliberately because one fix was a mechanism change rather than a
correction in place, and it found that the moved cap had shipped with no test at all.

**In production, after the merge:** the converter is Active at `MemorySize 3008`,
`EphemeralStorage 2048`, `Timeout 600`. A real execution was run through the Query workspace and
its result object captured as the fixture. **The end-to-end conversion itself is owed** — see
[`docs/testing/owed.md`](../testing/owed.md); this plane has no browser surface until SPEC-223,
so a live conversion needs an authenticated API call rather than a click.

## The apply is the only thing that knows an account quota

`main` went red on this spec. `CreateFunction` refused the converter — `'MemorySize' value
failed to satisfy constraint: Member must have value less than or equal to 3008` — because this
account's Lambda memory quota is 3,008 MB, not the 10,240 MB Lambda documents.

Every gate was green: `tofu validate` type-checks, `docker-lambda`'s validation block enforces
Lambda's *documented* range, and a plan never calls `CreateFunction`. The apply found out on
`main`, with the write grant, both log groups and `notify` already applied and only `convert`
refused — which `Deploy Lambdas` then reported as *"planned but never pointed at this commit's
code"*, the reconcile gate's signature for a refused create.

The fence is in [`decisions/infrastructure.md`](../decisions/infrastructure.md#fences); the guard
is `test_fleet_derivation.py`, fleet-wide because the next function to want more memory will be
in a different module and its author will have the same information: none.
