# `results-conversion` — the save-a-query's-results-as control plane

Takes a **finished Athena execution** and writes its result set into a space the actor may write
to, as Parquet, JSON, Excel or CSV. This module is the whole plane: the queue, the pipe, the machine,
the execution role and five verbs. Users reach it through the **Format** choice in the Query tab's
save-results dialog and the Data Explorer's export dialog (SPEC-223), gated on the
`resultsConversion` flag; the route itself is unflagged.

The shape this module shares with the other seven is in
[`../../info/control-plane-shape.md`](../../info/control-plane-shape.md); the orchestration and the
domain layer are in [`lambdas/info/planes/results-conversion.md`](../../../lambdas/info/planes/results-conversion.md).

## The input is the RESULT object, never the source table

Athena writes every result set as one CSV object under the actor's own results prefix, whatever it
was queried from — so the converter reads one shape, **no second query is started and nothing is
billed**. No intermediate file is made either: that CSV exists whether or not this plane runs,
because it *is* the query's result. The path that avoids it is `UNLOAD`, and it is the one that
writes several files under names Athena chooses and cannot produce Excel at all.

## Ownership is a question about a PATH

An execution is the actor's **iff Athena recorded its output under
`cpcommon.results.user_results_prefix(bucket, username)`** — the one builder the API starts every
one of that user's queries with. So a guessed execution id names nothing the actor cannot already
read. An id Athena does not know and an execution written anywhere else refuse with the **same**
reason code and the same sentence, or the refusal answers "does this execution exist?" for any id
a caller cares to try.

## The Deny ships before the Allow it bounds

`policies/execution.json.tftpl` carried an explicit `s3:PutObject` **Deny** on every protected
folder in both space buckets from the first apply, a spec BEFORE it held any `PutObject` Allow.
That order was deliberate and it paid: the write grant arrived with SPEC-222 beside the verb that
uses it, into a role where a validator defect already could not reach a results, receipt,
settings or shared-tables folder. Measured against the deployed role — `explicitDeny` under
`athenaresults/`, `archive/`, `shared_tables/` and `user_settings/`, `implicitDeny` for an ordinary
path — so the Deny discriminates rather than merely existing.

⚠ **The validator mirrors the DENY, not the browser's picker.** The Deny's wildcard sits where the
space name goes and an IAM wildcard matches `/`, so it reaches those folders at **any depth in
both buckets**. `rccommon.paths.protected_refusal` is anchored the same way, which is stricter than
the picker in a personal space on purpose: a validator anchored at the root would accept a
destination IAM then refuses at the write, turning a named refusal into an `AccessDenied`.

## `MessageGroupId` is the actor's username

One user's conversions are started in order while different users start independently; the runs
themselves overlap, since the Pipe is `FIRE_AND_FORGET`, and the conditional write is what makes that
harmless (`pipe.tf`). Raw rather
than hashed, which is safe here and not on the space-keyed planes: a username is bounded at 63
characters by the catalog identifier rule, well inside SQS's 128, where an S3 key reaches 1024.
`MessageDeduplicationId` is the request id, so a browser retry of one submit is one execution.

## No `states:DescribeExecution`, unlike file-send

The `TIMED_OUT` door reads the request from the **event's own input**. What makes that safe is not
a cap of this plane's: SQS refuses a message over 256 KB at the send and EventBridge carries an
event of that size, so no request that reached the machine can be too big for the rule to carry. A
test asserts the route declares no body cap of its own, so the argument cannot be invalidated by
one being added later.

## The ceiling is PROVISIONAL

`local.state_machine_timeout_seconds` is sized for a machine that does no data work yet. SPEC-222
re-derives it with the converter's budget, in the same test that sizes the converter. What holds it
honest meanwhile is a test summing every Task's timeout times its attempts along the longest path,
and the timeout notification words the same constant, so the sentence cannot outlive the number.
