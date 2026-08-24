# Spec: The Notifications `create` Boundary

**ID:** SPEC-206
**Status:** Draft
**Last Updated:** 2026-08-23
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
- [ ] **Both refusals emit a structured `observability.error`** into `logs/service=notifications/`,
      with the reason code and without echoing the body. That log is the signal, and it has to be,
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
- [ ] **A test reads the writer's `lambda.tf` and fails if the variable is absent or wired to
      anything but that attribute** — the precedent is the existing assertion that pins the
      event-source mapping's `batch_size = 1`.
- [ ] **With the variable unset the writer still starts, still serves both user actions, and refuses
      every `create` — and this is a RUNTIME fail-closed, said plainly.** The deploy test above does
      not make it unreachable; it makes it unreachable *on `main`*, which is a different claim
      (FR-003 is what covers the window in between).
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
- [ ] The four sites that become wrong are corrected: the writer's module docstring; its
      `MAX_PAYLOAD_BYTES` rationale (which rests on the unconditioned grant — still true of IAM, no
      longer true of what reaches `apply_create`); `notifications.service.ts`'s comment above
      `ID_SHAPE`, which cites the live hole as its reason; and `notifications/outputs.tf`'s
      "(future) trusted-producer scope" note.
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

### FR-006: The note into Arc B

#### Description:

SPEC-201 rewrites `_resolve_username` — the exact function this spec changes — and its sketch shows
the `create` arm with no sender check. SPEC-200 removes the browser's `sqs:SendMessage` altogether.

#### Acceptance Criteria:

- [ ] SPEC-201 gains a line requiring this check to survive its rewrite, in the same way SPEC-200
      already carries one for `USER_ACTIONS`.
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
def _msg(body, sender="AROASERVICE:producer"):   # explicit, and every existing create test passes one
    return {"Records": [{"body": json.dumps(body), "attributes": {"SenderId": sender}}]}
```

- [ ] Nine existing `create` tests plus the redelivery tripwire go through this helper and currently
      send **no `attributes` at all**. They must be updated to pass a service sender explicitly —
      **not** by giving `_msg` a silent default that becomes the thing under test.
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
apps/portal/src/features/notifications/notifications.service.ts   # the ID_SHAPE comment
docs/security-baseline.md                          # the disposition, closed
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
- Delivery doc, INDEX row, and a `decisions.md` entry for **the deny of one principal rather than an
  allow of eight, and why IAM cannot express this at all**.
- **`CLAUDE.md` pruning is in scope here, not optional.** It sits at 51,975 bytes against a 52,000
  ratchet, so any Key Decisions line breaks `validate_docs.py` — and the rule is prune, never raise
  the cap. The prune to make: the four file-operations lines (187–189, 191) fold into one
  consolidated entry, which frees roughly 2 KB.
