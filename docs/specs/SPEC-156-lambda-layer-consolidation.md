# Spec: Lambda Layer Consolidation — Folding the Deliberate Twins onto `cpcommon`

**ID:** SPEC-156
**Status:** Draft
**Last Updated:** 2026-08-05
**Depends On:** SPEC-107 (`cpcommon`, the shared layer this spec consolidates onto), SPEC-125 (which `dqcommon/index_store.py:20` names as the point where the CAS twins converge — it has shipped), SPEC-151 (fixes `casio.is_precondition` **in place**; this spec then moves it — land 151 first), SPEC-153 (the `conftest` snapshot and paginating fakes that make cross-layer refactoring safe)

> **Reference:** from the 2026-08-05 codebase audit. Pure consolidation in the Lambda layers, with no behaviour change and no new infrastructure.
>
> **The ordering matters and is stated once here.** SPEC-151 fixes the 409 predicate *in place* in `casio`; this spec then moves the fixed predicate into `cpcommon`. Doing it the other way round means fixing a bug during a move, which is the combination that makes a refactor unreviewable. Likewise SPEC-153's `conftest` snapshot must cover the domain layers before this spec starts moving modules between them — without it, an unrestored patch in one suite silently changes another.
>
> **Several of these duplications are self-documenting.** `dqcommon/index_store.py:20` says *"this is a deliberate twin, not drift. Keep the semantics identical"* and names SPEC-125 as the convergence point — SPEC-125 shipped, and the twin has since drifted in exactly the way the comment was written to prevent. `tbcommon/results.py` warns that a divergent results prefix "only shows up as a Lake Formation denial on whichever path is exercised less", and a third copy was written anyway. `cpcommon/auth.py:1-18` claims "One JWKS-verification path for the whole repo"; there are two. **In each case the repo already decided; this spec executes the decision.**
>
> **One finding here is not duplication but its cause.** `cpcommon/config.py:33-38` `_require`s six environment variables **at module import**, which is why `notifications-writer` could not import `cpcommon.auth` and grew its own verifier instead. FR-004 fixes the cause; the deduplication follows from it.

## Overview

The Lambda fleet is organised as one cross-plane layer (`cpcommon`) plus four domain layers. That structure is sound, and where `cpcommon` owns something — error classification, observability, S3 listing, DDL rendering, state-machine helpers — the planes use it consistently.

What the audit found is a set of helpers that were duplicated for a reason that has since expired. A conditional-write CAS loop exists three times, in a module whose own docstring names the spec that was supposed to converge them and which has since shipped. A `failure_message` resolver exists three times, and the two copies that do not use `cpcommon.messages.Resolver` pay for it visibly — `tscommon` has no tokens mechanism at all, so a message that needs a value has the value baked into its literal and the exception's `tokens` are discarded. A results-location builder exists three times in three shapes, in defiance of a comment warning that exactly this divergence surfaces as a Lake Formation denial on the less-travelled path. The JWKS verification path — the fleet's authentication boundary — exists twice, because the shared one cannot be imported without six environment variables that the function in question does not set.

None of this is broken today. All of it is a maintenance surface where a fix reaches one copy, and in two cases the drift has already happened.

---

## Scope

### In Scope

- **One CAS implementation** in `cpcommon`, replacing the three copies.
- **One `failure_message` resolver path**, with the three domain modules reduced to their message tables.
- **One `results_location`** builder.
- **One JWKS verification path**, unblocked by making `cpcommon.config` resolve lazily.
- **One SQS envelope parser**, with the shared-space caller adopting it.
- **One Athena DDL runner**, replacing the two identical per-plane wrappers.
- **Dead-code removal** and two stale-docstring corrections.

### Out of Scope

- **Any behaviour change.** Every message a user can receive, every error code, every retry count and every notification body is byte-identical afterwards. Where two copies differ, the difference is resolved explicitly under FR-001 and FR-002 — never silently.
- **Fixing bugs found during the move.** SPEC-151 owns the `casio` 409 fix, the Glue transient classification and the `jwks(url)` cache key. If this spec's work surfaces a new defect, file it; do not fix it in a consolidation PR.
- **Browser-side consolidation** — SPEC-155.
- **New infrastructure, new layers or a change to which layer a function attaches.** If a move would change a function's layer attachment, stop: that is a `deploy-lambdas.yml` matrix change with SPEC-137's failure mode attached, and it needs its own treatment.
- **Merging the domain layers into `cpcommon` wholesale.** The domain layers stay; only the genuinely cross-plane helpers move.
- **`log-foundry` or the observability door.** `cpcommon.observability` remains the only entry point.

---

## Functional Requirements

### FR-001: One conditional-write CAS

#### Description

`shared-space-common/casio.py:41-67` (`cas_mutate`), `dqcommon/index_store.py:110-183` and `log-sweep/log_sweep.py:167-257` implement the same read → mutate → conditional-put → retry loop. `index_store.py:20` names SPEC-125 as the convergence point and instructs that the semantics be kept identical; they have already drifted — two handle the racing 409 and one does not, and the retry caps are 6, 5 and 5.

#### Acceptance Criteria

- [ ] `cpcommon.cas` exports the loop and the `is_precondition` predicate, handling `PreconditionFailed`/`412` **and** `ConditionalRequestConflict`/`409` (the union SPEC-151 establishes).
- [ ] All three call sites use it; the three local copies are deleted.
- [ ] **The retry-cap divergence is resolved explicitly** — one value, chosen deliberately, with the reason recorded. Preserving three caps through a "consolidation" is a failed consolidation.
- [ ] Each call site's distinctive behaviour is preserved: `index_store`'s same-`requestId` replacement and cap, `log_sweep`'s append semantics, `casio`'s callers' expectations.
- [ ] The existing tests for all three pass unchanged, including `log-sweep`'s `test_a_read_failure_never_overwrites_an_existing_day` and `index_store`'s contention tests.
- [ ] `index_store.py:20`'s docstring is updated — the twin no longer exists, so the instruction to keep it in sync must not survive.
- [ ] `shared-space-common` gains no new layer dependency it did not already have (`casio.py:21` already imports from `cpcommon.errors`).

### FR-002: One failure-message resolver path

#### Description

`tbcommon/messages.py:112-142`, `tscommon/messages.py:69-93` and `dqcommon/messages.py:127-143` each do: access-denied short-circuit → body table lookup → marker substitution → prefix sentence. Only `dqcommon` uses `cpcommon.messages.Resolver`. The cost is explicit: `tscommon/messages.py:31-33` documents that it has **no tokens mechanism**, so `too_many_recipients` bakes the cap into its literal and `tscommon.notify.emit_failure` discards `err.tokens` even though `TerminalError` carries them. The dedup-id builder is copied verbatim between `tbcommon/notify.py:41-43` and `dqcommon/notify.py:63-65`.

#### Acceptance Criteria

- [ ] `cpcommon.messages.Resolver` gains an optional prefix template and access-denied clause, so all three planes can express their wording through it.
- [ ] The three domain modules retain only their message **tables**; the resolution logic is shared.
- [ ] `tscommon` gains the tokens mechanism it lacks, and `tscommon.notify.emit_failure` passes `err.tokens` through rather than discarding them.
- [ ] `too_many_recipients` takes its cap from a token rather than a baked literal, and renders the same text as today for the current cap.
- [ ] The dedup-id builder moves to `cpcommon.notify`; both copies are deleted.
- [ ] **Every message string a user can receive is byte-identical** — asserted by the existing message tests passing unchanged across all three planes.
- [ ] The dedup-token rule (one per *outcome*, not per verb — SPEC-114) is preserved.

### FR-003: One results-location builder

#### Description

`tbcommon/results.py:11-17`, `table-share-create-table/table_share_create_table.py:33-35` and `data-quality-start-profile-query/dq_start_profile_query.py:41-56` build the Athena results prefix three ways, plus ad-hoc `ddl_output` prefixes at `dq_create_temp_tables.py:137` and `dq_drop_temp_tables.py:100`. `tbcommon/results.py`'s docstring states why this must not be duplicated.

#### Acceptance Criteria

- [ ] `cpcommon.results.results_location(bucket, database, actor, *, sub=None)` is the single builder.
- [ ] All five sites use it; the three local copies are deleted.
- [ ] **The prefix each plane produces is unchanged**, asserted per plane — this is the Lake Formation denial risk the original comment names, so a differing prefix is a failure of this FR, not a tidy-up.
- [ ] If the three shapes genuinely differ today, the difference is enumerated in the delivery doc and each is expressed through the shared builder's parameters rather than normalised away.

### FR-004: One JWKS verification path, and a lazily-resolving config

#### Description

`notifications-writer/notifications_writer.py:46-108` re-implements the issuer and JWKS URLs, the cached `PyJWKClient`, `jwt.decode` with the same options, and the `token_use`/`cognito:username` checks — plus its own boto3 S3 factory at `:62-68`. `cpcommon/auth.py:1-18` claims to be the fleet's single verification path. The blocker is real: `cpcommon/config.py:33-38` `_require`s six environment variables **at import**, and this function sets three.

#### Acceptance Criteria

- [ ] `cpcommon.config` resolves lazily — module `__getattr__` or accessor functions — so importing `cpcommon.auth` or `cpcommon.clients` does not require variables the importing function does not use.
- [ ] A missing variable still fails **loudly at first use**, with the same error text as today. Laziness must not become silence.
- [ ] `notifications-writer` uses `cpcommon.auth` for verification and `cpcommon.clients` for S3; its local copies are deleted.
- [ ] The two verifiers are asserted to accept and reject identically **before** the deletion — a parity test written against both, run once, then reduced to the shared path.
- [ ] `test_layer_import_safety.py`'s scrubbed-environment probe covers `notifications-writer` and still passes: this function is one of the three singletons SPEC-137 took down, so its cold-start import safety is the acceptance criterion that matters most here.
- [ ] The other two singletons are checked for the same eager-import blocker and adopted if they carry it.
- [ ] `cpcommon/auth.py:1-18`'s docstring becomes true, or is corrected.

### FR-005: One SQS envelope parser and one Athena runner

#### Acceptance Criteria

- [ ] `cpcommon.events.parse_sqs_request` gains an `exc=` factory parameter defaulting to `TerminalError`; `shared-space-validate/validate.py:57-77`'s `_extract_record` + `_parse_request` are deleted in favour of it, passing `AuthorizationError`.
- [ ] `cpcommon/events.py:11-13`'s docstring — which states that table-share verbs do **not** adopt this — is corrected: `table_share_validate_authorize.py:139` calls it.
- [ ] `cpcommon.athena.bound_runner(fail_reason, timeout_reason)` returns the bound DDL runner; `table-builder-execute-ddl/athena_run.py` and `tscommon/athena.py` are deleted in favour of it.
- [ ] `_now`/`_sleep` remain injectable at call time so the existing timing tests keep working.
- [ ] Poll constants and both planes' reason codes are unchanged.

### FR-006: Dead code and over-public helpers

#### Acceptance Criteria

- [ ] `cpcommon/bounded_read.py:145-154` `S3RangeReader.readall` is deleted — verified to have no caller anywhere in the tree, and its own docstring concedes "the footer probe never calls it". `io.RawIOBase` supplies a default if one is ever needed.
- [ ] `cpcommon/s3_listing.is_ignored` is made private (`_is_ignored`) **or** left public with a one-line note that it is public for its own test's benefit. It is **not** dead — `s3_listing.py:79` calls it internally — so deletion is wrong.
- [ ] No other module or function is removed without a tree-wide grep recorded in the PR.

---

## Implementation Phases

Each FR is independently landable and should be its own PR. Consolidation PRs must be reviewable as "nothing changed", so keep them narrow.

### Phase 1: The blocker

- FR-004's lazy `cpcommon.config`, landed **alone**, with the loud-at-first-use assertion and the scrubbed-import probe green.
- Nothing else moves until this is proven, because it is the reason the JWKS duplication exists and it touches every function's import path.

### Phase 2: The authentication boundary

- The rest of FR-004 — parity test, then adopt `cpcommon.auth`/`clients` in `notifications-writer`, then delete.

### Phase 3: CAS

- FR-001. **Requires SPEC-151's 409 fix to have landed**, so the move carries no behaviour change.

### Phase 4: Messages and results

- FR-002 (resolver, tokens, dedup builder), FR-003 (results location).

### Phase 5: The small ones

- FR-005 (SQS parser, Athena runner, stale docstrings), FR-006 (dead code).

### Phase 6: Completion

- Completion ritual per `CLAUDE.md`.
- Update `component-inventory` for the new `cpcommon` modules.
- The convergence itself is worth a short `decisions.md` note — the "deliberate twin" comments pointed at SPEC-125 and are now discharged, and a future reader should find that recorded rather than inferring it from a deleted comment.
