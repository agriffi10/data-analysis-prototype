# Results conversion — control plane

Saves a finished query's result set into a space the user may write to, as Parquet, JSON, Excel
or CSV. It exists because producing a new file from a result set of unbounded size needs polars
and must never run inside a request. **CSV is here on narrower terms than the other three**: the
CSV Athena wrote is still copied by the synchronous path whenever the file wanted is that object,
and a conversion is asked for only where the file keeps a SUBSET of the result's columns, or the
same columns in another order — which a copy cannot produce. **The input is the execution's result object, never the
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
where `NotifyFailure` tells it, reading the counts the two Excel refusals name from the seed's
`tokens`. The failure path — three seeds into `RecordFailure → NotifyFailure → Failed` — is
complete, with the top-level `TimeoutSeconds` and its EventBridge `TIMED_OUT` rule. The timeout
door reads the request off the EVENT and holds no `states:DescribeExecution`.

## The request envelope

`{requestId, traceparent, queryExecutionId, format, destination: {space, prefix, filename},
onConflict, submittedAt, identity, columnIndexes?}`. `columnIndexes` names result POSITIONS, in
the order the file is to carry them, and is the one optional field; absent, every column is
written in the result's own order. It travels the machine as `null` in that case rather than
being omitted, because a `Pass` state hard-fails on an absent key. Unknown top-level fields are rejected — which is why the
sender adding `traceparent` had to widen this plane's allowed set in the same change. **`destination.prefix` is RELATIVE
to the space root** — `paths.destination_key` builds `{root}{prefix}{filename}` — and a caller
sending an absolute in-space prefix instead writes `alice/alice/…` that nothing here refuses, since
`assert_inside_root` only proves containment and a doubled root is contained. Empty or
slash-terminated, both accepted. `MessageGroupId` is the actor's
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
- **The size cap is per format**, because Excel cannot stream: polars hands xlsxwriter a Python
  copy of every cell and xlsxwriter stores each again, so Excel's memory is spent per **CELL** —
  a one-byte NULL costs about 250 bytes. The streamed formats are bounded by the scratch disk;
  Excel by a cell count, which the converter takes from the CSV before it builds anything, and
  by the bytes those cells are already paid for. A byte cap alone admitted a result that ran the
  converter out of memory for ten minutes. The numbers live in `rccommon.config`, derived from a
  measured model that a corpus in the plane suite holds them to — and
  `scripts/measure_excel_peak.py` re-measures it — so quoting them here is how this line was wrong
  within an hour of being written, when the account's real memory ceiling moved all three.
- **The Excel model and its corpus guard are local, and a green guard is not production
  headroom.** The guard charges each measured shape the baseline plus its local per-cell cost at
  the largest input the caps admit. The model peaks at the fewest columns that reach the cell
  cap, which is `docs/testing/e2e.md` §4.3's at-cap row and the one input read in production at
  scale. There the guard's figure came in 125 MiB under the `REPORT` line and the model's 108
  over it. The model held only because that shape sets none of its terms. The shape that sets the
  per-cell term has about 25 MiB of slack over its own guard figure, though its admitted inputs
  model far below the budget. So a re-derivation, or any change to a cap, is validated by
  converting the new model-peak input live and reading its `REPORT` line against the model's
  figure. Regenerate that row's input for the new cap, keeping it under the byte cap.
- **polars' fast count (`select(pl.len())` on a CSV scan) miscounts a quoted newline once the file
  is split across threads**, in either direction — 65,104 rows for 100,000 at the converter's two
  threads. The Excel path counts through one projected column with the real reader instead, and
  asks the built frame's height again. **The CSV writer counts the same way, over the file it just
  wrote** — it can use neither the Parquet footer nor the JSON writer's newline count, because a
  CSV carries an embedded newline raw where JSON escapes it. A test of it needs a file large enough
  to be split; a three-line fixture is one chunk and passes against the broken count.
- **polars' STREAMING sink refuses a large CSV holding quoted newlines outright**, and this is a
  limit the plane has always had rather than one the CSV writer brought. Measured on 1.12.0: a
  generated result whose every tenth value is a 200-character multi-line document sinks fine at
  50,000 rows and raises `ComputeError: field is not properly escaped` at 60,000 — about 2 MB —
  from `sink_csv` and `sink_parquet` alike, on a file Python's own `csv` module and polars'
  non-streaming `collect` each read correctly. So Parquet and JSON have refused such a result
  since they shipped, as `results_unreadable`, whose sentence asks the user to cast a column and
  is wrong about the cause. Nothing here fixes it; a fix means reading without the streaming
  engine, which changes what bounds the size cap from the disk to memory and is a re-derivation
  rather than a patch.
- **`scan_csv` with `schema_overrides` renames columns to the override keys and applies types
  positionally when the header does not match**, silently. The verb checks the CSV's header
  against the metadata before the typed read for that reason alone.
- **A result column whose NAME holds a double quote fails every conversion, and leaving it out
  does not help.** polars 1.12 does not un-escape a doubled quote in a CSV *header*, only in the
  data: for a column Athena wrote as `"a""b"`, `collect_schema().names()` answers `a""b` where
  Python's own `csv` module answers `a"b`. So the header check above sees a disagreement and
  raises — an unexpected-fault notification rather than a named refusal, for a legal
  `SELECT 1 AS "a""b"`. Choosing columns cannot rescue it: the check is deliberately over the
  WHOLE header, because the object is still the whole result. Not a new fault and not a wrong
  file, but the one shape where an ordinary query reaches a fault the user cannot read.
- **The Excel formula fence is polars' own default.** It builds the workbook with
  `strings_to_formulas: False`; the verb must never pass a `workbook=` of its own. Only a
  leading `=` is ever evaluated — `+`, `-`, `@`, tab and CR are inert in `.xlsx` by the format.
- The registry read needs the `s3:prefix`-conditioned `ListBucket`, or an unregistered shared
  space raises `AccessDenied` instead of refusing.
- The post-validate state carries `username` flat, never `actor`; the plane's emitters read it
  by that name, and a reader built on `cpcommon.notify.actor_of` addresses nobody.
