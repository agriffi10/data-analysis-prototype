# Completed Spec — SPEC-206: The Notifications `create` Boundary

## What was completed?

The notifications plane has said since SPEC-058 that `create` is trusted-producer-only. The IAM
policy never implemented it: the portal role's `sqs:SendMessage` was unconditioned, so any signed-in
user could enqueue a `create` naming anybody and saying anything, including a clickable in-app link.
That sentence is now true of the running system.

- `notifications_writer.sender_id(record)` reads the `SenderId` SQS stamps on every message — a
  message *system* attribute a `SendMessage` cannot set — and `_create_sender_refusal` compares its
  **role-id half** against the portal role's IAM unique ID, which Terraform sets on the function as
  `NOTIFICATIONS_UNTRUSTED_SENDER_ID`.
- `process(req, sender)` (was `process(req)`) refuses above the username resolution; `handler` logs
  one `observability.error` and returns, so the message is treated as handled.
- `module.data` gained a `portal_role_unique_id` output, wired through the root to the notifications
  module and onto the writer's environment.
- No user sees anything change. The only browser edit is one comment, corrected because it cited
  the live hole as its reason.

**Shipped as two PRs on purpose.** The wiring merged and applied first (#493), then the check (#494).
The two deploy workflows trigger on `push` to `main` with no ordering between them, and in the other
order there is a multi-minute window where new code runs against a function whose variable is unset —
where the writer fails closed and refuses **every `create` in the product**.

### Deliberate deviations

- **Three reason codes, not the spec's two.** `untrusted-sender`, `sender-id-absent` and
  `sender-check-unconfigured`. An unset variable is a third operationally distinct state — the deploy
  is broken, not the record and not an attacker — and one code for two opposite conditions is one log
  line that cannot tell them apart. Two guards keep the order honest: the empty role-id half is
  refused **before** the comparison (so an absent sender never compares equal to an unset variable and
  is logged as a forgery), and the config is tested **first** (so an unset variable reports itself even
  when the sender is absent, instead of blaming the message for a broken deploy). The spec was amended
  before code rather than only the delivery doc, so the diff was reviewed against a contract that
  agreed with it.
- **`_msg(body, sender)` takes no default**, where the spec's snippet showed one. The rule beside that
  snippet — a default must not become the thing under test — is not enforceable by a default. The plan
  review also found the spec's "nine existing `create` tests" was really twelve, so "update them all"
  was already a counting exercise that had gone wrong once. Required makes it structural.
- **Eight stale-comment sites, not four.** A sweep found the root `infra/outputs.tf` and the
  oversize-payload test carrying near-duplicates — reworded, not copied, which is why a literal sweep
  missed them — plus `ARCS.md` and SPEC-191's delivery doc pointing at the now-closed disposition.
- **A `validation` block on the Terraform variable**, not in the spec. The test protects `main`; the
  validation protects every later plan against a wrong wire (the role's ARN and its name are in the
  same module as the right value, and either validates clean then never matches).

### What this does NOT close

`_parse_record` still raises on a non-JSON body and on an unknown action, both before the guard runs,
so a signed-in user can still dead-letter this queue at will with `{"action":"delete"}`. This spec
decides *who may send a `create`*, not who may reach the queue. Recorded here rather than left for a
reader to infer that the channel is now protected.

## What changed from earlier specs?

- `process`'s signature changed; `_resolve_username` is untouched, and SPEC-201 gained a line
  requiring the guard to survive its rewrite **and** fixing its own acceptance criteria, which this
  spec falsifies (its `create` fixtures must now supply a service `SenderId`).
- `docs/security-baseline.md`'s design finding is **closed** — it read *accepted for now … tracked
  separately*. The second fix shape it proposed, a separate queue, is rejected with reasons in
  `decisions/` rather than merely not chosen.
- SPEC-191's "pre-existing gap, not fixed here" entry and `ARCS.md`'s "not a safe model to copy" note
  carry superseded markers.
- `CLAUDE.md`: the three file-operations digest lines folded into one (1,789 → 842 chars), which is
  what made room for this spec's line under the 52,000-byte ratchet.

## Verification

`ruff`, `mypy`, `pytest lambdas/`, portal `format:check`/`lint`/`test`/`build`, `tofu validate`,
`tofu fmt -check`, `scripts/validate_docs.py` — all green. The applied wiring was confirmed against
the deployed function (`get-function-configuration` returns the role's real `AROA…` unique ID), and
PR 1's plan was `0 to add, 1 to change, 0 to destroy`.

Deferred to a live check (`docs/testing/owed.md` §2.1): every offline test supplies the `SenderId` it
wants, so what is owed is that **real portal-role credentials** produce the value the writer refuses —
with `markRead` beside it as the positive control, since a refusal alone cannot tell "the boundary
works" from "the browser lost the queue".

**Still owed after this merges:** FR-003's post-deploy control — one ordinary plane operation whose
notification arrives. It is inherently post-deploy, so it cannot be discharged in this diff; the
blast radius it guards against is "notifications stop for seven planes", and every other check of
that is offline against a fixture the test author wrote. Its row goes into `docs/testing/sessions.md`
once run.
