---
type: Decision
title: "A data-quality request id is claimed by one execution before anything is named from it (data quality)"
description: "`inspect-source` claims a data-quality request id under `If-None-Match: *` at `data-quality/claims/{requestId}.json` before anything is named from it; no lifecycle rule may expire that prefix, and only a lower-case hyphenated UUID is accepted."
---

**Every per-run name on this plane is derived from a request id the caller chooses.** The temp
tables, the report folder and everything under it — the manifest, the DDL and query output,
`report.json` — and the Athena `ClientRequestToken`s all come from `requestId`, which the API admits
as any string within its bound, and the queue forgets after five minutes. An id sent again past that
window while its first run was still going met the `IF NOT EXISTS` create as a no-op and inherited
the first run's LOCATION: a folder check reusing a root single-file check's id carried no `"$path"`
predicate over it. Only an accident refused those queries — the Athena tokens derive from the id
too, and Athena refuses a known token with a changed `QueryString` — and AWS documents no lifetime
for a token, so once one was forgotten the check reported over the whole space. It also overwrote
the first run's manifest and report, and either
run's cleanup dropped the other's table. In a shared space another member's ids are readable from
`index.json`.

**The id is claimed instead, once, by the execution.** `inspect-source` first writes
`data-quality/claims/{requestId}.json` to the admin bucket under `If-None-Match: *`, naming the
execution ARN that `StampExecution` puts on the state. A `412` reads the claim back: this
execution's own ARN is a Task retry and carries on, and anything else — a claim that does not parse
included — is refused `request_id_reused` before the verb lists a file. A `409` means a concurrent
request interrupted the create, and is retried. Nothing releases, takes over or expires THIS
plane's claim; a test keeps every expiring admin-bucket lifecycle rule off the prefix. **That is
data quality's choice, not a rule about claims** — the archive plane took the other side
deliberately, putting its claim under a prefix that expires at 30 days and pinning the arithmetic
that makes the expiry safe instead
([why](../archive-and-restore/the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)). The refusal puts no
`manifestKey` on the state, so the failure path's cleanup drops nothing.

**A claim makes the names unique only if distinct ids derive distinct names, and they did not.** A
table's name is the id with its hyphens stripped, and Glue folds names to lower case, so `ab-cd` and
`abcd`, or an id and its upper-case twin, would hold two claims and share one table. The validator
and the claim both refuse anything but a lower-case hyphenated UUID as `invalid_request`, which is
exactly what the browser mints. The API still admits any string; the plane is the boundary.

**Rejected.** *Names derived from the execution:* `report.json` and the index row stay keyed on the
request id, which the browser computes, so closing that arm is a contract change. *A read-back of
the temp table's LOCATION*, table-builder's post-condition: it closes the predicate bypass alone,
adds a Glue and Lake Formation read this plane never made, and leaves the report, manifest, token
and cleanup arms open. *A claim beside the report:* it would sit inside the space, only as safe as
every route that can write or delete there, and be one claim per space rather than per id.
*Claiming in `validate-authorize`:* its payload is the raw Pipe array, one of the trace-adoption
shapes, and reaching the ARN there means reshaping it.

**Decided 2026-09-16 (Andrew): the refusal is silent.** The browser mints a fresh id per submit, so a
reuse comes from a request built by hand, which has nothing it should be told, and the run it
collided with is the one that reports. The question put to Andrew also gave a redelivery of one
click as the realistic trigger, one that would tell a person a running check had failed. That rested
on redelivery starting a second execution, and [reusing an execution name was measured](../../../infra/modules/control-plane/README.md#a-redelivered-message-is-not-a-re-run)
to return the first run instead — only that a redelivery reuses its name is inferred — so the
decision stands on the reason above. The code and the predicate that keeps it quiet now live in the
shared layer, [where file operations and archive read them too](a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is.md). That a notice under a borrowed id
could drop someone else's is closed for every plane at the queue, by [per-recipient deduplication](notifications-deduplicate-per-recipient-so-a-borrowed-request-id-cannot.md).

**What stays open.** Runs from before the claim hold none, so reusing one of their ids claims it
afresh and overwrites that run's report and index row; there are no production users, so there is no
backfill. A reusing execution whose claim fails loudly — its retries run out, or reading the holder
back meets an unexpected error — is notified to its own sender, generically. And Deploy Lambdas and Deploy
Infrastructure race on the merge that introduced this: a verb pointed before the machine stamps the
ARN refuses every check `invalid_request` until the apply lands.

## History

### 2026-09-16

- **Settled:** entered the register.
