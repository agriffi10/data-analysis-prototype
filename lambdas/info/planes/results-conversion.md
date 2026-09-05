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

`ValidateAuthorize → Validated → DescribeResults → Described → Placeholder → Succeeded`

`Placeholder` stands where `Convert` will; this machine ends having written nothing. The failure
path — `ValidateFailureSeed`/`RequestFailureSeed → RecordFailure → NotifyFailure → Failed` —
is complete from day one, with the top-level `TimeoutSeconds` and its EventBridge `TIMED_OUT` rule.
The timeout door reads the request off the EVENT and holds no `states:DescribeExecution`.

## The request envelope

`{requestId, queryExecutionId, format, destination: {space, prefix, filename}, onConflict,
submittedAt, identity}`. Unknown top-level fields are rejected. `MessageGroupId` is the actor's
username; `MessageDeduplicationId` is the `requestId`.

## Traps

- The execution role holds **no `s3:PutObject` Allow** and an explicit Deny on every app-managed
  folder in both space buckets; the validator's protected-folder rule mirrors that Deny at any
  depth, which is stricter than the browser's picker in a personal space on purpose.
- The registry read needs the `s3:prefix`-conditioned `ListBucket`, or an unregistered shared
  space raises `AccessDenied` instead of refusing.
- The post-validate state carries `username` flat, never `actor`; the plane's emitters read it
  by that name, and a reader built on `cpcommon.notify.actor_of` addresses nobody.
