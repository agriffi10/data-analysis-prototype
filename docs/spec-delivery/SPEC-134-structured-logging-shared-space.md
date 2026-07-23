# Completed Spec — SPEC-134: Instrument the Shared-Space Control Plane

## What was completed?

All eight verbs join the pipe as `service="shared-space"`, and **the coverage guard becomes a
fleet-wide harness** that every plane registers with. No behaviour change. Two PRs: infra, then
code.

## The harness (FR-007) — why shared-space went first

`data-quality-common/test_instrumentation_coverage.py` enumerated its plane's verbs so a tenth
couldn't be added without instrumenting it. **Four planes each keeping their own copy is how three
of them end up subtly different** — the argument that put the emitters behind one door in
SPEC-130.

It now lives in `control-plane-common` as a parameterized harness over `Plane` descriptors.
Registering a plane is **one entry**. Two details make it a guard rather than decoration:

- **`verb_count` is a literal per plane**, so an enumeration finding too few *fails* instead of
  passing vacuously.
- **The service name is checked against `log_sweep.SERVICE_RE` itself.** A name failing that
  pattern does not error — it quietly files every one of that plane's events under
  `logs/_unrouted/` (SPEC-129).

data-quality's own module was deleted **only after** the harness was run filtered to that plane
and reproduced all 64 of its assertions.

**Corrected by SPEC-135:** the harness originally matched verb modules by filename prefix, which
swept in `table-builder-execute-ddl/athena_run.py` — a helper beside the verb it serves — and
demanded it carry a traced handler. A verb module is one that **defines a top-level `handler`**;
it now matches on that, and `module_prefix` is gone from every descriptor.

## FR-002 — the decorator difference is declared, not discovered

Data-quality, table-builder and table-share wrap every handler in `@notifies_on_failure`, and
`@traced` must sit **above** it or a failed-and-notified invocation closes its span `status: "ok"`.
**Shared-space verbs notify explicitly from inside the handler**, so `@traced` is the only
decorator — and the harness asserts exactly that, so adding `notifies_on_failure` here later
**fails** until someone establishes the ordering.

Without declaring it on the descriptor, the next reader sees the ordering rule stated three times
and reasonably concludes it was forgotten on the fourth plane.

## What the narrative says

The **five stores** a request touches — registry, per-user cache, Glue, Lake Formation, Cognito
slots — named per verb. This plane's characteristic bug is two of them disagreeing, and its
characteristic debugging session is reconstructing which writes landed: #153–155, #163/#164 and
#165 were all that session.

`forget`'s cache-only path states what it **deliberately left**. Otherwise it is indistinguishable
from a half-done teardown.

Both `add-members` and `remove-members` record that access is live at grant time while the
**principal tag** needs a token re-mint — the lag that has repeatedly presented as "the grant
didn't work", answered in the log instead of prompted by it.

## Per-member events, and why that is not inconsistent

The roster fan-out emits one event per member. That is a deliberate exception to SPEC-131 FR-005's
per-item prohibition, and **the bound is structural, not hopeful**: membership is capped at ten
Cognito attribute slots. The sweep's prohibition exists because its per-message count is unbounded
*and* it emits into the queue it drains — neither holds here.

Slot exhaustion is an **ERROR with a stable token**, not only a user notification: "how often are
people hitting the cap" is a product question, and a notification cannot be counted.

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1319 passed / 2 skipped at merge.

**Fourteen mutations, all observed to fail — one survived the first round.** Silencing the
per-member roster-failure warning changed nothing, because FR-005's test did not exist yet. That
test now drives a five-member fan-out with the **third** member's cache broken — the shape that
leaves a roster correct for four people and stale for one, invisible from either side — and
asserts the other four land, the per-member `warning` fires, and the summary counts are right.

## Still owed — live

**SPEC-125's shared-space smoke run** (create → add-member → leave → delete) has been owed since
125 shipped, and this spec makes exactly that sequence legible in the store. The two should be
done as one run: it costs one execution and produces far better evidence than either alone. The
specific risk 125 carries is a shared layer's import-time `_require` failing at **cold start**
(PR #196) — which is why the run must follow a deploy, not a warm container.
