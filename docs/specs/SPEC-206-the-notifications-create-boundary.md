# Spec: The Notifications `create` Boundary

**ID:** SPEC-206
**Status:** Completed
**Last Updated:** 2026-08-24
**Depends On:** SPEC-058→061 (the notifications plane, its single-writer FIFO model and its stated anti-spoofing rule), SPEC-126 (the DLQ drain, and why this queue's DLQ is undrained), SPEC-166 (an expected refusal is a return value, not a raise), SPEC-138 (findings and dispositions live in `security-baseline.md`), SPEC-191 (which re-found this while building the file-ops producer)

## Overview

The notifications plane has always said that `create` is trusted-producer-only. Its writer takes the
target username straight from the message body on that action — correctly, because a plane notifying
a *recipient* holds no token for the person it is telling. The design is sound and the documentation
is right about it.

**The IAM policy does not implement it.** The shared portal role holds an unconditioned
`sqs:SendMessage` on the notifications request queue, so a signed-in user can enqueue a `create`
naming anybody and saying anything — including a clickable in-app link. This spec makes the
enforcement real, so the sentence the architecture has asserted since SPEC-058 becomes true of the
running system.

It is the **interim** fix and says so: Arc B removes the grant it constrains (SPEC-200), at which
point the principal denied here becomes a service principal rather than a user-reachable one. The
check stays regardless — that removal is eleven specs out and reversible, and a runtime refusal costs
nothing once the grant is gone.

It is not a new capability and no user sees anything change. The finding is already recorded in
`docs/security-baseline.md` as **accepted, low-severity, tracked separately**, and that entry names
the fix shape this spec builds: an infrastructure-set marker a body cannot smuggle.

**Where it sits in the build order:** it belongs to no arc and blocks nothing. Build it whenever
there is room — before SPEC-190 if the appetite is small, after if not. See FR-006 for its
relationship to Arc B, which eventually removes the grant this spec constrains.

## Scope

### In Scope

- Refusing a `create` that came from the browser's credentials, at the writer, using the sender
  identity **SQS itself stamps** on the message.
- The Terraform wiring that gives the writer the one identity it must refuse, its deploy ordering,
  and a test that stops a deploy which forgets it.
- Correcting every site that asserts this hole is closed, and the register that records it as open.
- One live check, because nothing offline can send a message as the portal role.
- A note into SPEC-201, which rewrites the very function this spec changes.

### Out of Scope

- **Changing the queue topology.** A second queue for user actions is the obvious fix and is
  rejected in FR-001, with reasons, so it is not re-derived.
- **Changing how a `create` names its target.** The body's `username` stays authoritative for
  `create`. A plane telling Bob that Alice sent him files holds no token for Bob, and inventing one
  would be a far larger change to seven planes than this gap warrants.
- **The queue's undrained DLQ.** It stays undrained; FR-001 is deliberately designed not to add to
  it.
- Any change to the seven control planes, their execution roles, or their notify paths.
- Rate-limiting or content rules on `create`. This spec decides *who may send one*, not what one may
  say.

---

## Functional Requirements

### FR-001: The writer refuses a `create` from the browser's credentials

#### Description:

SQS stamps `SenderId` on every message: for an IAM role it is the **role's unique ID** followed by a
session name (`AROAEXAMPLE123:some-session`), and the Lambda event-source mapping delivers it in
`Records[0].attributes.SenderId` for FIFO queues with no configuration. It is a message *system*
attribute — set by the service, unsettable by `SendMessage` — so it is the one attributable fact a
message carries.

Nine principals hold a grant on this queue today: the seven control-plane execution roles, the DLQ
drain, and the portal role. **Exactly one of them is reachable by a user**, which is what makes a
single-principal refusal complete rather than partial. (Any account principal with a matching
identity policy could also send; the deploy role can grant itself. That is an administrative action,
not a user-reachable one.)

#### Acceptance Criteria:

- [ ] A `create` whose `SenderId` names the portal role is **refused**, and no inbox is written.
- [ ] **The comparison is against the ROLE-ID HALF: the substring before the first `:`.** Not
      equality against the whole value, and not `startswith`. This is the criterion most likely to be
      implemented wrong in a way nothing catches — equality never matches, and a control that never
      matches reads exactly like a control that works. Three tests: a realistic
      `{UNIQUE_ID}:some-session` refuses; a bare `{UNIQUE_ID}` with no colon refuses; a different
      role's `AROAOTHER:session` passes.
- [ ] **The session-name half is never examined**, and a test asserts a refusal holds across two
      different session names. Cognito's enhanced flow does not document what it sets there, and
      pinning a literal would couple this control to an undocumented value.
- [ ] `markRead` and `markAllRead` from the portal role are **unaffected** — they are the browser's
      two legitimate actions and already derive their target from a verified token.
- [ ] A `create` from a service principal is unaffected, asserted with at least one explicit test
      rather than assumed.
- [ ] **A refusal LOGS AND DROPS; it does not raise.** The message is treated as handled so the
      event-source mapping deletes it. Raising would cost three invocations and one permanent
      dead-letter message *per forged request*, on the queue whose DLQ is deliberately undrained and
      is the only operator-facing signal this plane has — handing every signed-in user a way to
      drown it. It is also the settled rule: an expected refusal is a return value, and a `Catch` is
      for unpredicted faults (SPEC-166). This refusal is the most expected thing in the module.
- [ ] **A `create` carrying NO `SenderId` is refused too, and under a DIFFERENT reason code.** A
      security check that cannot run must not report a pass (SPEC-138). The two cases are
      operationally opposite — one is somebody trying it on, the other is the control having broken —
      and a single reason code would make them the same log line.
- [ ] **There are THREE reason codes, not two, and the third is the unset variable** (`untrusted-sender`,
      `sender-id-absent`, `sender-check-unconfigured`). Raised during the plan review and folded in
      here so the diff is checked against a contract that agrees with it. An unset
      `NOTIFICATIONS_UNTRUSTED_SENDER_ID` is a third operationally distinct state — the deploy is
      broken, not the record and not an attacker — and folding it into `sender-id-absent` would make
      FR-003's window read as a forgery attempt in the one log line an operator sees. It is also
      **load-bearing for correctness**: the config must be tested FIRST, because with the variable
      unset an absent sender's empty role-id half compares equal to the empty config and every verdict
      inverts — service creates pass, absent-sender creates are refused as forgeries.
- [ ] **The guard sits ABOVE `_resolve_username`, not inside the `create` branch.** `process` resolves
      the username before it branches, so a guard placed in the branch lets a portal-role `create` with
      no `username` reach `ValidationError("create requires a username")` and **raise** — three
      invocations and a permanent message on the undrained DLQ, which is the exact vector the
      log-and-drop criterion above exists to close, reachable by omitting one field. A test drives it.
- [ ] **What this does NOT close is stated, not implied:** `_parse_record` still raises on a non-JSON
      body and on an unknown action, both before `process`. A signed-in user can therefore still
      dead-letter this queue at will with `{"action":"delete"}`. That is pre-existing and out of scope
      here — this spec decides who may send a `create` — but the delivery doc says so rather than
      leaving a reader to infer the channel is now protected.
- [ ] **Every refusal emits a structured `observability.error`** into `logs/service=notifications/`,
      with the reason code, the SQS `messageId` and without echoing the body. The `messageId` is a
      service-stamped field like `SenderId`, so it does not breach the rule — and without it FR-005's
      observation cannot tie one refusal event to one attempt. A test asserts the body's `message`,
      `username`, `link` and `payload` appear in no emitted field. That log is the signal, and it has to be,
      precisely because dropping means nothing accumulates in the DLQ to notice.
- [ ] **A second queue is rejected, and the reason is stated so it is not re-proposed.** Moving the
      browser's two actions to their own queue would let IAM enforce this with no runtime check — but
      the single-writer guarantee is *one FIFO queue, one message group per user, batch size 1*.
      FIFO ordering is per `(queue, group)`, so two queues means two event-source mappings and two
      concurrent invocations read-modify-writing one user's `notifications.json`: a mark-read and an
      arriving notification can lose each other. It trades a spoofing bug for a data-loss bug, and
      closing that would mean putting the inbox write under ETag CAS first.
- [ ] **A queue resource policy is not an alternative either, and this is the stronger argument.** No
      SQS condition key can reach a field inside a message body, so a policy could only deny the
      portal role `sqs:SendMessage` outright — the same principal on the same action that `markRead`
      needs. IAM cannot express this rule at all; that is *why* it is a runtime check.
- [ ] **The rule is a DENY of one principal, not an ALLOW of eight.** An allow-list would be a
      hand-maintained list of role IDs that fails closed on the day a plane is added: that plane's
      notifications would stop, drop or dead-letter unnoticed, and nobody would connect the two. One
      env var beats eight, and the deny direction fails open only toward principals that require an
      explicit IAM change.

### FR-002: The writer learns the identity it must refuse

#### Description:

The portal role's unique ID is a Terraform attribute (`aws_iam_role.portal.unique_id`). The `data`
module does not currently output it, and the `notifications` module takes only the role's *name*.

#### Acceptance Criteria:

- [ ] The `data` module outputs the portal role's unique ID; the root passes it to the
      `notifications` module; the module sets it as an environment variable on the writer.
- [ ] **The value is the role's UNIQUE ID, never its name or ARN.** `SenderId` carries neither, and a
      comparison against the wrong one silently never matches.
- [ ] **A test pins the WHOLE CHAIN, not just `lambda.tf`** — the precedent is the existing assertion
      that pins the event-source mapping's `batch_size = 1`, but one file is not enough here.
      `lambda.tf` alone cannot see the hop where the silent failure lives: a *missing* root wiring
      fails `tofu validate` (the variable has no default), while a *wrong* one — `module.data.iam_role_arn`,
      a plausible typo naming the same role from the same module — validates clean and produces exactly
      the "compares against the wrong one, silently never matches" outcome. So the test reads
      `notifications/lambda.tf`, `infra/main.tf` and `data/outputs.tf`, and fails if any hop is absent
      or wired to anything but `aws_iam_role.portal.unique_id`.
- [ ] **The variable also carries a `validation` block** matching `^AROA[A-Z0-9]+$`, which is the
      structural half of the same guard: the test protects `main`, the validation protects every later
      plan, and neither makes the other redundant. OpenTofu defers validation while a value is unknown,
      so it guards a re-wire rather than the first create.
- [ ] **With the variable unset the writer still starts, still serves both user actions, and refuses
      every `create` — under `sender-check-unconfigured`, and this is a RUNTIME fail-closed, said
      plainly.** The deploy test above does not make it unreachable; it makes it unreachable *on
      `main`*, which is a different claim (FR-003 is what covers the window in between).
- [ ] **The Terraform variable itself carries NO default**, so a root that forgets to wire it fails at
      `plan` rather than deploying a writer that silently refuses every notification in the product.
      The runtime fail-closed above is the second belt, for the FR-003 window where the code is new and
      the function's environment is not yet updated — not a substitute for the first.
- [ ] `infra/modules/notifications/variables.tf`'s header — which claims every cross-module value is
      a name or id and the module plans standalone — is corrected: this is the module's first
      resource-attribute dependency on another module. It is safe (an unknown-at-plan value in a
      Lambda `environment` is not the unknown-ARN-in-a-list trap), and the header should say so, so a
      later reader does not undo it.

### FR-003: The wiring ships BEFORE the code, in its own PR

#### Description:

`deploy-infra.yml` and `deploy-lambdas.yml` both trigger on `push` to `main` behind path filters,
**with no ordering between them**. One PR touching `infra/**` and `lambdas/**` starts both at once,
and `update-function-code` finishes long before a `tofu apply`.

#### Acceptance Criteria:

- [ ] **The Terraform wiring (FR-002) merges in an earlier, separate PR from the writer change
      (FR-001).** In that order the window is harmless: old code ignores an env var it never reads.
      In the other order — or in one combined PR — there is a multi-minute window where new code runs
      against a function whose variable is unset, and FR-002's fail-closed refuses **every `create`
      in the product**, dropped or dead-lettered, unrecoverably.
- [ ] The implementation phases are ordered to match, and the spec says which PR is which.
- [ ] **PR 1 touches `infra/**` ONLY — no file under `lambdas/**`, the deploy pin included.** Found in
      the plan review, and it is a second, sharper reason for the split than the one above.
      `plan_deploy.py` selects a function when **any** file under `lambdas/{name}/` changes, tests
      included, and `deploy-lambda.sh` then issues `update-function-configuration --layers` — while
      PR 1's own `tofu apply` issues `UpdateFunctionConfiguration` for the new `environment` entry
      (`ignore_changes` covers `filename`, `source_code_hash` and `layers`, **not** `environment`).
      Two concurrent configuration updates on one function is `ResourceConflictException`, so a test
      file in PR 1 makes the one PR designed to be inert the one that reddens `main` intermittently.
      The pin therefore ships in PR 2, whose CI runs it against a `main` where the wiring is already
      applied — which is the moment it has something to assert.
- [ ] **After the second PR, one ordinary plane operation is run and its notification confirmed to
      arrive.** The blast radius this spec must not cause is "notifications stop for seven planes",
      and every other check of that is offline against a fixture the test author wrote.

### FR-004: Every site that asserts this hole is closed, and the register that records it open

#### Description:

`infra/modules/notifications/iam.tf` says, directly above the grant: *"cannot enqueue a `create` for
another user … `create` is reserved for trusted producers granted SendMessage separately."* True of
the design, false of the policy — the dangerous combination, because a reader checking the IaC is
told the question has been answered. Four other sites say the opposite and become wrong once this
ships.

#### Acceptance Criteria:

- [ ] `iam.tf`'s comment states what the policy actually does — an unconditioned grant — names the
      writer's check as the thing that enforces the boundary, and says **why IAM cannot do it**
      (no condition key reaches a message body).
- [ ] **A test asserts the false sentence is gone from `iam.tf`.** In a spec whose entire premise is
      that a false comment is more dangerous than no comment, the correction gets a binary check like
      anything else. Reading source in a test is established here.
- [ ] The sites that become wrong are corrected. The spec said four; a sweep for
      `trusted.producer` / `unconditioned` found **eight**, and two of them are near-duplicates of
      sentences in the original list — reworded, not copied, which is what makes a literal-string sweep
      miss them. This spec's own thesis arriving as a defect. All eight:
      the writer's module docstring; its `MAX_PAYLOAD_BYTES` rationale (which rests on the
      unconditioned grant — still true of IAM, no longer true of what reaches `apply_create`);
      **the same rationale repeated as a comment in `test_an_OVERSIZE_payload_is_refused_rather_than_truncated`**;
      `notifications.service.ts`'s comment above `ID_SHAPE`, which cites the live hole as its reason;
      `notifications/outputs.tf`'s "(future) trusted-producer scope" note; **the root
      `infra/outputs.tf` output carrying that identical note**; `ARCS.md`'s "the shipped notifications
      pipeline is *not* a safe model to copy" note, which points at the disposition this spec closes;
      and SPEC-191's delivery doc, whose "a pre-existing gap was found and NOT fixed here" paragraph
      gains a one-line pointer rather than a rewrite (a delivery doc is historical).
- [ ] **The binary check sweeps ALL THREE Terraform files in one pass** — `notifications/iam.tf`,
      `notifications/outputs.tf` and the root `infra/outputs.tf` — not `iam.tf` alone. A test that
      proves one copy gone while its near-duplicate stands is the failure mode in miniature.
- [ ] **`docs/security-baseline.md`'s disposition is closed** — it currently reads *accepted for now
      … tracked separately* and names this exact fix shape. Leaving it open would have the security
      register asserting a live acceptance for a hole that no longer exists.
- [ ] `docs/decisions.md`'s Notifications entry gains what enforces trusted-producer-only, since it
      is the sentence this spec makes true.
- [ ] The two repo comment rules hold in everything touched: no spec or PR numbers in `.tf`/`.py`,
      and `observability` messages are literals.

### FR-005: The check nothing offline can run

#### Description:

Every offline test fakes the SQS event, so the `SenderId` a test supplies is the one it wants. What
is owed is that the value **real portal-role credentials** produce is the one the writer refuses.

#### Acceptance Criteria:

- [ ] It is a row in **`docs/testing/owed.md`**, not a step in `e2e.md`. `e2e.md` is the signed-in
      *browser* guide, and this cannot be driven from one: `owed.md` already records, measured, that
      the production bundle's console cannot `import()` a bare specifier, which is what driving the
      SQS client from a signed-in console would require.
- [ ] It reuses **`owed.md` §2.1's existing credential recipe**, which obtains portal-role
      credentials in a shell through the same Cognito enhanced flow the browser uses — therefore the
      same role, therefore the same `SenderId`. The recipe's own rule about never pasting the token
      into a shell command carries over.
- [ ] The observation is: **no row appears in the target's inbox**, and
      `logs/service=notifications/` carries the refusal's reason code. Not "it reaches the DLQ" —
      FR-001 drops it precisely so it does not.
- [ ] **The target is the tester's own username**, stated, because the portal role can only read its
      own `user_settings/` — a tester aiming at a second account cannot observe the pass condition.
- [ ] **The positive control runs beside it**: the same credentials' `markRead` still succeeds. A
      refusal with no control cannot tell "the boundary works" from "the browser can no longer reach
      the queue at all".
- [ ] **The block is written as the exact commands, because three details will otherwise stop a
      tester dead.** The queue is FIFO, so `send-message` needs `--message-group-id` (the username)
      **and** `--message-deduplication-id` — content-based dedup is off. The structured log is
      **swept every 10 minutes and never long-polled**, so a reader who checks immediately sees an
      empty prefix and records a pass as a failure; the block says to wait a sweep. And it names where
      the queue URL comes from (the root `notifications_queue_url` output) and that the log objects
      live in the **admin** bucket, which the portal role can read.

### FR-006: The note into Arc B

#### Description:

SPEC-201 rewrites `_resolve_username` — the exact function this spec changes — and its sketch shows
the `create` arm with no sender check. SPEC-200 removes the browser's `sqs:SendMessage` altogether.

#### Acceptance Criteria:

- [ ] SPEC-201 gains a line requiring this check to survive its rewrite, in the same way SPEC-200
      already carries one for `USER_ACTIONS`.
- [ ] **The note also fixes SPEC-201's own acceptance criteria, which this spec falsifies.** SPEC-201
      asserts that "a `create` with a `username` and no `identity` block writes the inbox and
      succeeds" — true only if its fixture carries a **service** `SenderId`, since a record with no
      `attributes` is now a refusal. A bare survival line does not stop that spec's author writing a
      fixture that is refused and then "fixing" it by deleting the guard. The note says both: every
      `create` fixture supplies a service `SenderId`, and the guard sits **above** `_resolve_username`
      — which matters because that function is SPEC-201's entire subject.
- [ ] The forward consequence is recorded: after SPEC-196 the API Lambda assumes the portal role, so
      the principal this spec denies becomes a **service** principal. Harmless — `create` is still
      emitted by execution roles — but it should be read, not discovered.
- [ ] This spec states that it is the **interim** fix, and that Arc B removes the grant it
      constrains; the check stays regardless, because the grant's removal is eleven specs out and
      reversible.

---

## Data Model

No stored shape changes. The only new value is configuration:

```
NOTIFICATIONS_UNTRUSTED_SENDER_ID = "AROAEXAMPLE123"   # aws_iam_role.portal.unique_id
```

The message the writer already receives carries what it needs:

```jsonc
// Records[0] — the FIFO record the event-source mapping delivers, unchanged
{
  "body": "{\"action\":\"create\",\"username\":\"bob\",\"message\":\"…\"}",
  "attributes": {
    // Service-stamped. The half before the ':' is the role's unique ID and is what is compared;
    // the session name is illustrative only — Cognito's enhanced flow does not document it.
    "SenderId": "AROAEXAMPLE123:some-session",
    "MessageGroupId": "bob",
    "SequenceNumber": "…"
  }
}
```

## API / Interface Contract

The sender has to reach the decision, and today nothing carries it there: `_parse_record` returns
only the parsed body and `process` never sees the record. **The signature that changes is
`process`**, and the handler extracts the sender:

```python
def sender_id(record: dict) -> str: ...        # new; "" when the attribute is absent
def process(req: dict, sender: str) -> dict:   # was process(req)
```

The test helper changes with it, and how it changes is load-bearing:

```python
def _msg(body, sender):   # REQUIRED — no default; see below
    return {"Records": [{"body": json.dumps(body), "attributes": {"SenderId": sender}}]}
```

- [ ] **`sender` is a REQUIRED parameter, with no default**, which is a correction to this spec's own
      earlier snippet. The rule below is what matters, and a default cannot enforce it: the plan review
      counted **twelve** `create` tests reaching this helper, not the nine stated here, so "update them
      all" was already a counting exercise that had gone wrong once. Required makes it structural —
      Python refuses the call site that forgets.
- [ ] Every existing `create` test plus the redelivery tripwire currently sends **no `attributes` at
      all**. They must pass a service sender explicitly — **not** by inheriting a default that becomes
      the thing under test.
- [ ] At least one test calls the writer with a record carrying no `attributes` key whatsoever, which
      is the missing-`SenderId` path.

## Environment Variables

On the notifications writer Lambda (Terraform-set; no `VITE_*` var, nothing in the browser changes):

```
NOTIFICATIONS_UNTRUSTED_SENDER_ID=the portal role's IAM unique ID (AROA…)
```

## File & Folder Structure

```
# PR 1 — the wiring (FR-002), merged and applied first
infra/modules/data/outputs.tf                     # + the portal role's unique_id
infra/main.tf                                     # + pass it to the notifications module
infra/modules/notifications/variables.tf          # + the variable, and the corrected header
infra/modules/notifications/lambda.tf             # + the env var

# PR 2 — the check and the record
lambdas/notifications-writer/notifications_writer.py       # sender_id, process, the refusal
lambdas/notifications-writer/test_notifications_writer.py  # its tests + the lambda.tf pin
infra/modules/notifications/iam.tf                         # the corrected comment (FR-004)
infra/modules/notifications/outputs.tf                     # the stale "(future)" note
infra/outputs.tf                                           # the root output's near-duplicate of it
apps/portal/src/features/notifications/notifications.service.ts   # the ID_SHAPE comment
docs/security-baseline.md                          # the disposition, closed
docs/specs/ARCS.md                                 # its pointer at that disposition
docs/spec-delivery/SPEC-191-file-ops-notifications-and-live-checks.md  # a one-line pointer
docs/decisions.md                                  # what enforces trusted-producer-only
docs/specs/SPEC-201-the-lambda-trust-boundary.md   # FR-006's line
docs/testing/owed.md                               # FR-005's row, beside §2.1
```

No new resource type, so none of the deploy-role IAM traps apply: an output, a variable, an env var,
a comment.

## Implementation Phases

### Phase 1: The wiring — its own PR, merged and applied before Phase 2

- The output, the variable, the env var, the corrected `variables.tf` header, and the `lambda.tf`
  assertion. Old code ignores the variable, so this is inert until Phase 2 ships.

### Phase 2: The refusal and its tests

- `sender_id`, the `process` signature, the role-id-half comparison, log-and-drop with two distinct
  reason codes, and the structured error events.
- The test-helper change, the nine existing `create` tests, and the three comparison cases.

### Phase 3: The comments and the registers

- FR-004's five sites, its test, the `security-baseline.md` disposition and the `decisions.md` line.
- FR-006's note into SPEC-201.

### Phase 4: The live check, the post-deploy control, and the ritual

- FR-005's `owed.md` row beside §2.1; FR-003's post-deploy positive control.
- Delivery doc, INDEX row, and a `decisions.md` entry carrying **three** fences, not one: the deny of
  one principal rather than an allow of eight; why IAM cannot express this at all (no condition key
  reaches a message body); and **why a second queue is rejected** — the FIFO single-writer argument
  from FR-001. `decisions.md` is where this repo's "do NOT build" fences live, and a rejection that
  exists only inside a closed spec is a rejection that gets re-proposed.
- **`CLAUDE.md` pruning is in scope here, not optional.** It sits at 51,845 bytes against a 52,000
  ratchet, so any Key Decisions line breaks `validate_docs.py` — and the rule is prune, never raise
  the cap. The prune to make: the file-operations lines fold into one consolidated entry. **There are
  three of them, not four** — 187→189, 191 and 189, totalling 1,799 bytes; the fourth line a reader
  will reach for is SPEC-190's, which is a *browser* decision, not a plane decision, and stays. And
  the saving is **net, not gross**: a `DIGEST_MAX_CHARS` line replaces them, so the fold frees ~900
  bytes, not ~2 KB. That is enough for this spec's line with headroom to spare, but a future spec
  reading "2 KB" would be planning against a number that was never there.
