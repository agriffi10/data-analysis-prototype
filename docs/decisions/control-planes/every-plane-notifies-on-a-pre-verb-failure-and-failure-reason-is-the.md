---
type: Decision
title: "Every plane notifies on a pre-verb failure, and `failure_reason` is the only decoder (SPEC-152)"
description: "**Every plane notifies on a pre-verb failure** — a `NotifyFailure` before `Fail`, reached on every path, because the no-verb-ran paths cannot be selected for in ASL."
---

All four control planes now carry a `NotifyFailure` state ahead of their terminal `Fail`, reached on
every failure path, invoking a thin per-plane verb that decodes the raw `{Error, Cause}` with
`cpcommon.errors.failure_reason` and emits through the plane's own notifier.

**The gap this closes was named by the repo's own design and closed in one of four planes.**
`@notifies_on_failure` needs handler code to run. SPEC-126's DLQ drain covers requests that never
started an execution. Neither covers the middle: an execution that started and then failed **before or
outside** any verb's Python — a `States.Timeout`, a `States.DataLimitExceeded`, a task-level throttle,
a Lambda that fails at **import**. In that window the user got no notification, no DLQ message, and a
request that never completed — against SPEC-114's rule that the notification **is** the completion
channel, with no admin UI to check and no reason to suspect anything but slowness. Not theoretical:
SPEC-137's nine-day `ModuleNotFoundError` and PR #196's shared-layer cold-start crash are both exactly
this shape.

**One error in that list is not closed by it.** `States.DataLimitExceeded` is caught only by a
catcher that names it, and none in the fleet does, so it still ends a run FAILED without reaching
`NotifyFailure`; so does `States.Runtime`, which `States.ALL` never catches. No event rule matches
FAILED. The machines are built so neither is raised, which is why the data-quality footer carries
no "always".

**That gap is accepted, not scheduled.** On archive and file-ops the silence can follow a move or a
delete. On archive, data-quality, table-builder and table-share, an uncaught error after the notify
state ends a run the user was already told had succeeded. A second EventBridge rule, matching
`FAILED` only for those two error names, was SPEC-236, which Andrew cancelled on 2026-09-16; its
draft keeps the per-plane survey. **Three traps wait for whoever adds a `FAILED` door.** Every door
picks its wording on the detail-type alone and never reads `detail.status`, so a `FAILED` event
reaching today's handler would be worded as a timeout. Every plane's failure sentence opens by
asserting failure ("Couldn't archive that: "), which would contradict a success already delivered.
And `lambdas/test_timeout_doors_fleet.py` reads only the first `event_pattern` in a file, so a second
rule admitting `FAILED` would pass it green.

**A fifth plane cannot ship without it.** `test_state_machines_cpcommon.py` enumerates every
`state-machine.asl.json.tftpl` under `infra/modules/` and asserts each has a `NotifyFailure` Task with
a `States.ALL` Catch, plus that its `RecordFailure` copies `$.error` **whole**. The exemption list is
an empty dict — an entry is a decision to leave users in the dark, not a formality. The second
assertion is not redundant with the throwing-intrinsic guard: a plane could satisfy that one perfectly
by copying `$.error.Error` alone, and every message would silently degrade to the generic.

**The duplicate-suppression mechanism differs per plane, and the difference is forced, not stylistic.**
This state sits on *every* failure path, because the paths where no verb ran cannot be selected for in
ASL — so an ordinary failure would otherwise notify twice.

- **Six of the eight planes** suppress in Python via `_verb_already_notified`, on **one name**:
  `Error == "TerminalError"` — table-builder and table-share, which this clause used to name
  alone, plus archive, file-ops, file-send and results-conversion. `data-quality` and
  `shared-spaces` carry none at all. **Counted 2026-09-09** — this clause named two of the six
  and had not been widened since it was written against four planes. The name is the only
  *positive* evidence available — a verb raised it
  deliberately and the decorator's `emit_terminal` fired — and it is the only case where the
  decorator's message is strictly better, because it carries `err.tokens` (without which a
  `columns_removed` refusal cannot name the columns). Everything else notifies, including an
  exhausted `TransientError`, which the decorator deliberately leaves un-notified — a gap this spec
  therefore also closes.

  **The obvious generalisation is wrong in the dangerous direction, and was caught in review.** An
  earlier version inferred the same thing from the *absence of a dot*: bare class name means a
  handler ran, dotted engine name means it did not. But `cpcommon.config` calls `_require` at
  **module scope** and raises a bare `RuntimeError` — not a hypothetical, this fleet's own recorded
  outage (`lambda.tf`: "check-table-absent: RuntimeError COGNITO_USER_POOL_ID unset", PR #196). The
  heuristic would have suppressed it, silencing the exact class of failure the spec exists to
  report. The set of dot-free names meaning "a verb notified" is unbounded and unknowable from the
  payload; the set meaning `TerminalError` is one string.

  **The price is a duplicate on the unexpected-exception path** — a `KeyError` inside a verb
  notifies through `emit_unexpected` and again here, same generic sentence. FR-002 settles it: a
  duplicate is preferable to none. A guess that suppresses is unrecoverable; a duplicate is a
  papercut on a path that is already a bug.

  **A seeded error must not wear a verb's name.** table-builder's `DiffMissingSeed` (the
  `RouteByChange` `Default`) manufactured `Error: "TerminalError"` for a case where `diff-schema`
  *returned successfully* without a `$.diff` — so no exception was raised and no decorator fired. It
  now seeds `DiffMissing`, because a defensive seed whose whole purpose is the shouldn't-happen case
  is the last thing that should buy itself a `Fail` state and silence. The user-facing text is
  unchanged: neither code is registered, so both render the generic clause.
- **shared-spaces** cannot use that test, because five of its seven verbs emit **no** failure message
  at all and a "did a verb run" guard would restore their silence. It reproduces the verb's **FIFO
  dedup token** byte-for-byte instead (`{requestId}:{action}-failed:{actor}`), so SQS drops the second
  message where a verb already spoke and delivers it where none did.
- **data-quality** is unchanged: `dqcommon` centralises one `FAILURE_STEP`, so its pair already
  collapses on an identical token. Unifying `tbcommon`'s per-verb steps to match would change
  notification behaviour on paths that already work.

**shared-spaces needed structural work, not just a state.** Its seven verb `Catch` blocks carried **no
`ResultPath`**, so the error object *replaced* the state and the verified actor was discarded — there
was no recipient to notify even in principle. They now merge under `$.error`; a `ValidateFailureSeed`
covers the pre-identity path (its Catch cannot carry a `ResultPath` — you cannot merge a key into an
array), and the router's `Default` gets an `UnknownActionSeed` whose **literal** `Result` merged under
`ResultPath` is the one seed form that reads no path and so cannot itself raise.

**`$.mode` on table-builder's `RecordFailure` supersedes the rule that forbade it.** The old test
banned `mode.$` there; its stated *reason* was that `ValidateFailureSeed` did not seed it and a Pass
state hard-fails on an absent key. The ban was never the invariant — the seeding was. `mode` is now
seeded, and the test asserts the general form: `RecordFailure` may read nothing `ValidateFailureSeed`
does not seed. Without it a failed **refresh** tells the user their **create** failed.

**shared-spaces gained a `failure_message` resolver** (`shared-space-common/messages.py`), the last
plane to get one. Its domain table is **empty on purpose**: every reason that can reach this path is a
raw engine name that SPEC-106 FR-008 forbids showing, so what varies is the **action**, not the reason.
Going through `cpcommon.messages.register` rather than hard-coding the clause means a code registered
later renders through the same path.

> **No longer empty.** The table now maps the class names of the plane's own terminal exceptions —
> `MembershipRefused`'s subclasses among them — to sentences a user can act on. For any exception
> but a `TerminalError`, `failure_reason` returns the engine's `Error` field, which is the raised
> class's name, so the keys are class names verbatim and a newly raised refusal renders the generic
> clause until its class is registered.

**No deploy-role IAM was needed, and that was verified rather than assumed.** All three planes' deploy
policies scope `lambda:CreateFunction`, `iam:PassRole` and `logs:CreateLogGroup` to
`{project}-*-<plane>-*` wildcards, and each plane's SFN invoke grant renders from the same `locals.tf`
map the new function was added to. SPEC-143's `load-table-definition` is the live precedent. The
spec's Phase 1 assumed an expansion and sequenced a separate land-and-apply around the self-grant
timing trap; neither was required.

**The cold-start probe is the one gate that would have caught SPEC-137.** `test_notify_failure_import_safety.py`
imports each new verb in a fresh interpreter whose `sys.path` is **exactly** what the deployment gives it.
`conftest.py` puts every shared root on `sys.path` for the whole suite by design, and `update-function-code`
succeeds against a function that cannot import. **Superseded in part by the container image (SPEC-213/214):**
the probe used to grant exactly the layers a function's deploy-table row named, and a wrong ROW failed there.
There are no rows and no per-function layer grants — one image gives every function every shared package —
so that half cannot fire and the probe no longer claims it. What survives is the half that still can: these
verbs must import at all, in a minimal environment. The environment is
**inherited**, unlike `test_layer_import_safety.py` which withholds `cpcommon.config`'s six: these verbs
reach their DOMAIN config through their notifier, whose import-time `_require` is *supposed* to run.
(`cpcommon`'s own six resolve on first access since SPEC-156 FR-004, so they are no longer part of what
an import demands from anyone.) Only `sys.path` is scrubbed, because packaging is what is under test.

**One layer needs a second guard, and only one.** The probe puts layer SOURCE TREES on `sys.path`, so a
module present on disk but absent from a layer's *build* is invisible to it. Every layer copies a
**package** (`cp -r cpcommon`) except `shared-space-common`, which publishes **flat modules** from an
explicit `for m in config casio auth …` list in the workflow — so a new module there ships only if
someone remembers to name it. Review confirmed the gap was live: deleting `messages` from that list left
the entire suite green while the deployed layer lost it. A test now joins the workflow's list against the
directory — SPEC-153 moved it to the packaging harness and generalised it; ~~SPEC-214 moved it again, to
`lambdas/test_image_layout.py`~~, when the harness it lived in went with the function table. **SPEC-214's
next PR then RETIRED it, because the list itself is gone**: `assemble.shared_layout` publishes what a
`lambdas/*-common/` directory holds, so there is nothing a module can be missing from. What now holds
`/opt/python` honest is `test_the_shared_layout_is_exactly_what_the_shared_sources_publish`, which walks
those directories independently of the assembler and compares.

That intermediate move was nearly a silent loss and is worth the sentence, because the trap is general:
the reasoning that first retired the guard — "there is no list any more, the assembler copies the
directory" — was true of where SPEC-214 ENDS and false a PR earlier, while `assemble.shared_layout` still
read the list. Measured on the commit that dropped it: a module planted on disk and absent from the list
passed all 2,388 tests, and importing it lazily from a verb passed the image's behaviour matrix too. The
retirement was safe only once the same plant reached `/opt/python` on its own. See *A layer gate must
check the copy list, not the flag map* below.

## History

### 2026-09-16

- **Changed:** Andrew cancelled SPEC-236's `FAILED` rule, so an uncaught `States.DataLimitExceeded` or `States.Runtime` telling nobody is accepted rather than scheduled.

### 2026-09-09

- **Changed:** The suppression clause was recounted and widened: six of the eight planes suppress on `TerminalError`, and data-quality and shared-spaces carry none.

### 2026-08-05

- **Settled:** SPEC-152.
