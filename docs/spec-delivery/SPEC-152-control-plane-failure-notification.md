# Completed Spec — SPEC-152: Control-Plane Failure Notification — Telling the User When No Verb Ran

## What was completed?

The silent-failure hole the repo's own design already named, closed in the three planes that never
had it. Every control plane now ends **every** failure path in a message.

- **FR-001 — a `NotifyFailure` state in all four machines.** table-builder, table-share and
  shared-spaces gained one ahead of their terminal `Fail`, mirroring data-quality. A fleet test in
  `test_state_machines_cpcommon.py` enumerates every `state-machine.asl.json.tftpl` under
  `infra/modules/` and asserts each has the state as a **Task** with a `States.ALL` Catch, so a fifth
  plane cannot omit it. The exemption dict is empty.
- **FR-002 — a thin failure-notifier verb per plane.** `tb_notify_failure.py`, `ts_notify_failure.py`,
  `ss_notify_failure.py`. Each decodes the raw `{Error, Cause}` with `cpcommon.errors.failure_reason`,
  emits through its plane's own notifier, resolves the recipient only from the verified `actor`, and
  is total — no payload shape makes it raise.
- **FR-003 — deployed, layered and pinned.** Three matrix rows, three `locals.tf` entries, three
  `stepfunction.tf` ARNs, and `test_notify_failure_import_safety.py`: a cold-start import of each verb
  in a fresh interpreter whose `sys.path` is exactly what its matrix row grants.
- **FR-004 — 50 tests across the three verbs**, every assertion on the notification body the user
  would receive.

`cpcommon.errors.failure_reason` went from **one** production consumer to **four**.

### Three things the build found that the spec did not predict

**Phase 1 was a no-op.** The spec sequenced a deploy-role IAM expansion first, to avoid the
self-grant timing trap. No expansion was needed: all three planes' deploy policies scope
`lambda:CreateFunction`, `iam:PassRole` and `logs:CreateLogGroup` to `{project}-*-<plane>-*`
wildcards, and each plane's SFN invoke grant renders from the same `locals.tf` map the function was
added to. SPEC-143's `load-table-definition` is the live precedent — it shipped with no base-policy
change. Verified across all three policies rather than assumed from one.

**shared-spaces needed structural work, not a state.** Its seven verb `Catch` blocks carried **no
`ResultPath`**, so the error object *replaced* the state and the verified actor was discarded — there
was no recipient to notify even in principle. They now merge under `$.error`. A `ValidateFailureSeed`
covers the pre-identity path (whose Catch cannot carry a `ResultPath`, because you cannot merge a key
into an array), and the router's `Default` — an unknown action, previously straight to `Fail` — gets
an `UnknownActionSeed` whose **literal** `Result` merged under `ResultPath` is the one seed form that
reads no JSONPath and therefore cannot itself raise. It also gained the plane's first
`failure_message` resolver, with a deliberately **empty** domain table: every reason reaching this
path is a raw engine name SPEC-106 FR-008 forbids showing, so what carries the information is the
**action**.

**FR-002's suppression could not be one mechanism.** `NotifyFailure` sits on every failure path —
the paths where no verb ran cannot be selected for in ASL — so an ordinary failure would notify
twice. table-builder and table-share suppress on one positively-identified name,
`Error == "TerminalError"`; everything else notifies, including an exhausted `TransientError`, which
closes the un-notified-retry gap as a side effect. shared-spaces cannot use that test at all,
because five of its seven verbs emit no failure message and the guard would restore their silence —
it reproduces the verb's FIFO dedup token instead. Full reasoning: `decisions.md`.

## What the fresh-context review changed

The review ran the suite, `ruff`, `tofu validate`, and four mutation experiments. It confirmed no
uncatchable `States.Runtime` was introduced, the dedup tokens match character-for-character,
recipient trust holds in all three verbs, and the "no deploy-role expansion" claim is true across
all three policies. It found three things worth fixing, all in the suppression logic and its guards:

- **The suppression heuristic was wrong in the dangerous direction.** It originally inferred "a verb
  already notified" from the *absence of a dot* in Lambda's `Error` name. `cpcommon.config` calls
  `_require` at module scope and raises a bare `RuntimeError` — this fleet's own recorded outage
  (PR #196, quoted verbatim in `lambda.tf`) — which the heuristic would have **silenced**, on
  precisely the class SPEC-152 exists to report. Replaced with the single name `TerminalError`,
  accepting a duplicate on the unexpected-exception path exactly as FR-002 directs.
- **A seeded error wore a verb's name.** `DiffMissingSeed` manufactured `Error: "TerminalError"` for
  a path where `diff-schema` *returned successfully* without a `$.diff` — no exception, no
  decorator, nobody told. It now seeds `DiffMissing`; the user-facing text is unchanged.
- **The cold-start probe over-claimed.** Its docstring said it would catch a layer that fails to
  publish what the code imports; it would not, because it puts source trees on `sys.path`. The gap
  was live and specific to `shared-space-common`, the one layer built from an explicit module list —
  deleting `messages` from that list left the whole suite green. A second test now joins the
  workflow's list against the directory, and the docstring says what it does not cover.

Two cosmetic findings were also taken: the `create` phrasing now matches what `create_space` already
emits (no "the", inconsistent with `delete` — deliberately, because users cannot tell which code
sent the message), and the delete dedup's dependence on `delete` being owner-only is now asserted
rather than left in a comment.

## What changed

| Area | Change |
|---|---|
| `infra/modules/{table-builder,table-share,shared-spaces}/` | `NotifyFailure` state; new function in `locals.tf` + `stepfunction.tf` |
| `infra/modules/shared-spaces/` | `ResultPath` on 7 verb catches; `RecordFailure`, `ValidateFailureSeed`, `UnknownActionSeed` |
| `infra/modules/table-builder/` | `$.mode` on `RecordFailure`, seeded in `ValidateFailureSeed` |
| `lambdas/{table-builder,table-share,shared-space}-notify-failure/` | new verb + tests |
| `lambdas/shared-space-common/messages.py` | new `failure_message` resolver |
| `lambdas/control-plane-common/` | fleet `NotifyFailure` + raw-error assertions; cold-start probe |
| `.github/workflows/deploy-lambdas.yml` | 3 matrix rows; `messages` added to the shared-space layer copy list |
| `lambdas/test_deploy_matrix.py` | `messages` added to `LAYER_PACKAGES` |

**One superseded rule.** `test_record_failure_is_unchanged_and_reads_no_mode` forbade `mode.$` on
table-builder's `RecordFailure`. Its stated *reason* was that `ValidateFailureSeed` did not seed it
and a Pass state hard-fails on an absent key — so the ban was never the invariant, the seeding was.
`mode` is now seeded, and the replacement test asserts the general form: `RecordFailure` may read
nothing `ValidateFailureSeed` does not seed. Without `$.mode`, a failed **refresh** tells the user
their **create** failed.

**No component-inventory rows.** That inventory covers `apps/portal/src/` only and has no Lambda
area; SPEC-151, also Python-only, added none either. Inventing an area for three single-purpose,
non-reusable verbs would be worse than the omission.

**No help sweep.** Nothing a user *does* changed. They receive a notification in cases that
previously produced silence, which is what SPEC-074's existing notifications guide already promises;
documenting the absence of a bug is not a guide.

## Verification

`1935 passed, 3 skipped`, lambdas coverage **96%** against the 95% floor, `ruff check lambdas/`
clean, `tofu validate` successful. All three new verbs at **100%** statement coverage.

The cold-start probe was confirmed non-vacuous by hand: running `ss_notify_failure` with only
`cpcommon` on `PYTHONPATH` fails with `ModuleNotFoundError: No module named 'messages'`.

### Owed live

**One run per plane**, and the shape is the same each time: force a failure that no verb code can
catch, and confirm the notification arrives. The cheapest trigger is the one SPEC-137 supplied for
free — deploy a verb whose layer attachment is missing, so it raises at import — but on a deployed
fleet the honest version is a **state timeout**: temporarily lower one verb's Step Functions task
timeout, submit a request that exceeds it, and confirm the inbox message names that plane's
operation and carries no engine text. Fold in a **shared-spaces `add_members`** failure specifically:
it is one of the five verbs that notified *nothing* before this spec, so it is the case where a
missing message is the loudest.

Nothing here is corroborated-not-demonstrated in the SPEC-149 sense: the ASL wiring is asserted
against the deployed templates and the decode is exercised per shape. What is untested is the
**delivery** end of the chain — the same thing every notification path in this repo owes.
