# Results conversion — control plane

Saves a finished query's result set into a space the user may write to, as Parquet, JSON or
Excel. It exists because producing a new file from a result set of unbounded size needs polars
and must never run inside a request. **The input is the execution's result object, never the
source table**: Athena writes every result set as one CSV object under the actor's own results
prefix, so the converter reads one shape whatever was queried, no second query starts and nothing
is billed.

**Ownership is a question about a path.** An execution is the actor's iff Athena recorded its
output under `cpcommon.results.user_results_prefix(bucket, username)` — the one builder the API
starts every query with. An unknown id and an execution written elsewhere refuse with one code.

## The machine

`infra/modules/results-conversion/state-machine.asl.json.tftpl`

`ValidateAuthorize → Validated → DescribeResults → Described → Convert → Converted →
ConversionOutcome → Notify → Succeeded`

`Convert` is the only state that writes. `ConversionOutcome` is a `Choice`: an **expected
refusal is a return value**, routed to `ConvertRefusedSeed` and out through the failure path,
because the path a raise takes cannot carry the row count the two Excel refusals name. The
failure path — three seeds into `RecordFailure → NotifyFailure → Failed` — is complete, with the
top-level `TimeoutSeconds` and its EventBridge `TIMED_OUT` rule. The timeout door reads the
request off the EVENT and holds no `states:DescribeExecution`.

## The request envelope

`{requestId, queryExecutionId, format, destination: {space, prefix, filename}, onConflict,
submittedAt, identity}`. Unknown top-level fields are rejected. `MessageGroupId` is the actor's
username; `MessageDeduplicationId` is the `requestId`.

## Traps

- The execution role's **only** write is `s3:PutObject` + `s3:AbortMultipartUpload` on the two
  space buckets, under an explicit Deny on every app-managed folder in both; the validator's
  protected-folder rule mirrors that Deny at any depth, which is stricter than the browser's
  picker in a personal space on purpose.
- **`Convert` retries on `TransientError` alone, once.** The four `Lambda.*` service errors cover
  a response lost after the function completed, and a re-invocation there meets its own
  conditional `PutObject` and reports `destination_occupied` to a user whose save succeeded. The
  verb raises `TransientError` only before the upload begins.
- **The size cap is per format**, because Excel cannot stream: polars materialises the frame and
  xlsxwriter builds the workbook beside it, at a measured 23–32x the CSV. The streamed formats
  are bounded by the scratch disk and Excel by memory, an order of magnitude apart. The numbers
  live in `rccommon.config` and are derived from the function's memory and disk by a test —
  quoting them here is how this line was wrong within an hour of being written, when the
  account's real memory ceiling moved all three.
- **`scan_csv` with `schema_overrides` renames columns to the override keys and applies types
  positionally when the header does not match**, silently. The verb checks the CSV's header
  against the metadata before the typed read for that reason alone.
- **The Excel formula fence is polars' own default.** It builds the workbook with
  `strings_to_formulas: False`; the verb must never pass a `workbook=` of its own. Only a
  leading `=` is ever evaluated — `+`, `-`, `@`, tab and CR are inert in `.xlsx` by the format.
- The registry read needs the `s3:prefix`-conditioned `ListBucket`, or an unregistered shared
  space raises `AccessDenied` instead of refusing.
- The post-validate state carries `username` flat, never `actor`; the plane's emitters read it
  by that name, and a reader built on `cpcommon.notify.actor_of` addresses nobody.
