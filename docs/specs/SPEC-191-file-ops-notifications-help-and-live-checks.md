# Spec: File Operations — Notifications, Help & the Arc's Live Checks

**ID:** SPEC-191
**Status:** Draft
**Last Updated:** 2026-08-17
**Depends On:** SPEC-189 (the terminals and their per-item outcome list), SPEC-190 (the browser's async model and its conflict view), SPEC-058/059/061 (the notifications plane, whose wire shape this spec extends), SPEC-114 (the notification-is-the-completion-channel rule), SPEC-106 (user-facing wording), SPEC-074 (Help & guides), SPEC-167/172 (producer precedents)

## Overview

The plane works and the browser drives it, but the user is still told nothing. This spec closes the
arc: one producer turns each terminal into a message, the notification learns to carry enough for the
user to *act* on it, the guides describe what actually changed, and the checks nothing offline can
prove are written down as a runnable script.

The notification is not a courtesy here — it is **the completion channel**. SPEC-190 deliberately
acknowledges *acceptance* rather than completion, so without this spec a user has no way to learn
that a folder move finished, or that three of their five items were refused.

## Scope

### In Scope

- **Extending the notification wire shape** (FR-001) — an escalation, because the notifications plane
  is shared by six other planes.
- **One producer** at the end of the machine, turning the per-item outcome list into messages.
- The **link**, and its feature gating.
- Wording for every outcome, through `focommon.messages`.
- **Help & guides** updates.
- The arc's **live-check script**.

### Out of Scope

- A second producer. Most outcomes are already reason codes the failure decorator emits; a second
  producer would duplicate SPEC-114's (SPEC-172's recorded rule).
- Real-time progress notifications. One message per terminal, not a stream.
- Email or any channel outside the in-app inbox.
- Changing the notifications **queue, the single-writer model or the read-modify-write** — all
  untouched. `apply_create` does gain one optional field (FR-001); that is the escalation, not an
  exception to this line.

---

## Functional Requirements

### FR-001: Extending the notification wire shape

#### Description:

An **escalation**, stated first because SPEC-190's conflict view depends on it and because the
notifications plane serves six other features.

Today a `Notification` is five fields — `id`, `message`, `read`, `timestamp`, `link?` — and
`normalize` rebuilds it field by field, discarding anything not named **by design**. There is also no
affordance anywhere to act on a notification's subject: `NotificationRow` takes
`{notification, onMarkRead}` and the page offers filter, refresh and mark-all-read.

So a conflict today could only be actionable in the submitting tab, until reload — unreachable in
exactly the scenario the arc exists for.

#### Acceptance Criteria:

- [ ] **BOTH ends of the pipeline change, or the field never exists.** The writer builds each row
      field-by-field too — `apply_create` composes `{id, message, read, timestamp}` plus `link`
      conditionally — so a producer sending a structured field has it dropped **before it reaches
      S3**, and a reader validating it would be validating something nothing writes. `apply_create`
      gains an optional payload written only when present (the `link` handling is the exact shape to
      copy, and its docstring already explains why that keeps existing producers byte-identical), plus
      the matching line in `process`. `isValidRow` and `normalize` are extended to match.
- [ ] **A row lacking the field is unchanged and valid, asserted on BOTH sides.** Reader: an existing
      row normalises byte-identically — sufficient by construction, since `normalize` is a field-by-
      field rebuild. Writer: `apply_create` with no payload produces a dict with exactly the existing
      keys. Six other planes write rows and none is modified.
- [ ] **`requestId` is on EVERY row this producer writes, including a wholly successful run.**
      SPEC-190 FR-003 settles an in-flight entry by matching it, and a clean run has nothing to
      re-submit — so scoping the whole field to "what a re-submit needs" would leave successful
      operations unsettled and the per-space gate wedged until the machine's ceiling.
- [ ] **Beyond `requestId`, the field carries what a RE-SUBMIT needs** — the `operation`, **both the
      source and destination spaces (kind + name)**, the destination prefix, and the **bounded
      conflicted items**, each with `itemKey`, `kind`, `targetName` where it had one, and its colliding
      sample. The source space is **not** derivable from an absolute key, and `kind` and `targetName`
      are required by SPEC-187's contract. SPEC-190 FR-005 rebuilds
      a request from this: without `operation`, the destination and `targetName`, a user who closed the
      tab still cannot re-submit — which is the exact gap this FR exists to close. `FileOpItemResult`
      alone does not carry them.
- [ ] **The bound is `NOTIFICATIONS_MAX × the worst-case ESCAPED row`, not one row.** The inbox is
      capped at 200 rows and read **whole** on every poll, and S3 keys are 1,024-byte arbitrary UTF-8
      where JSON escaping expands a control character to six bytes (SPEC-164 FR-004's rule, already
      applied to this list by SPEC-188 FR-006). Measuring one row against nothing is the
      wrong-quantity trap SPEC-161 records four times; expect the answer to force a small conflicted-
      item set rather than every item's entry.
- [ ] `NotificationRow` renders the action as a **sibling of the message anchor, never inside it**. The
      row deliberately makes the whole message the link to keep it a single target, so an interactive
      control nested in it is `nested-interactive` — an axe failure this repo has shipped twice
      (a button inside `role="tab"`, an anchor inside a gridcell). The existing mark-read control is
      the placement precedent.
- [ ] **The conflict view belongs to `features/file-browser`, and the row only links to it.** A row
      rendering the view would make `features/notifications` import `features/file-browser` — a new
      layering inversion (SPEC-155). The row carries a `Link` into `/files?…` with the `requestId`,
      which is the direction that already exists.
- [ ] An older reader meeting the field ignores it rather than refusing the row — true **by
      construction**, because `normalize` rebuilds field-by-field and `isValidRow` requires only the
      four core fields. (Not by versioning: the document is a bare array with no version.)

### FR-002: One producer, at the end

#### Acceptance Criteria:

- [ ] A single verb at the end of the machine turns the terminal's outcome list into notifications —
      the guard, the collector and the deletion emit **nothing** (SPEC-167's rule, and why those verbs
      return refusals as records rather than raising).
- [ ] The whole-request verbs still notify from their `@notifies_on_failure` decorators; this producer
      covers only the terminal.
- [ ] The producer **cannot fail the run**: `ResultPath: null`, a `Catch` leading onward, and no
      `@notifies_on_failure` — by the time it runs, a `move` has already deleted sources (SPEC-172).
- [ ] **One message per run**, and therefore **one dedup token per request**. (SPEC-114's "one token
      per outcome" applies to planes that emit one message per outcome; this one does not, and saying
      "per outcome" here would contradict FR-003.)

### FR-003: What the user is told

#### Acceptance Criteria:

- [ ] A run whose items **all** succeeded produces one success message naming the operation and the
      item count.
- [ ] A run with **mixed** outcomes produces **one** message naming the counts and a **bounded sample**
      of the refused items — bounded because SPEC-187 FR-008 AC6 and SPEC-188 FR-006 both cap it, and
      because a message per item would flood the inbox for a large selection.
- [ ] Every outcome has wording — the **successes** `moved` / `copied` / `deleted` as well as
      `conflict`, `noop`, `source_missing`, `source_empty`, `protected` (with its distinct `reason`),
      `copy_failed` and `duplicate` (with `source_changed` / `source_delete_failed` as its reasons). A
      mixed run must name what succeeded, not only what did not.
- [ ] **`duplicate` says the user now has the data in two places**, which is the one outcome they
      cannot infer and must act on.
- [ ] A `noop` says plainly that nothing changed and why — a rename to the same name is the ordinary
      way to reach it and reads as a failure otherwise.
- [ ] Wording renders through `focommon.messages` on the `cpcommon` `Resolver` — the **whole
      sentence**, never a fragment (SPEC-156), and never raw AWS text (SPEC-106).
- [ ] The `overwrite`-is-unrecoverable statement reaches the user in the conflict message.

### FR-004: The link

#### Acceptance Criteria:

- [ ] A successful `copy` or `move` links to the **destination** folder; a refused item's message links
      to the **source**.
- [ ] **A `delete` links to the longest common prefix of the request's item keys, falling back to the
      space root.** "The parent of what was deleted" is not derivable — a delete carries no
      `destination` and a multi-item delete can span folders, so the rule must be stated or the
      producer invents one.
- [ ] The link is `/files?prefix={…}` plus `?space=` where shared, built from the **space root** — a
      root-relative prefix is silently discarded by the route and lands the user at their space root
      (SPEC-167's recorded defect).
- [ ] **The flag→match gating is VERIFIED AND CITED, not built.** `NotificationRow` already carries the
      map and already covers `/files` and `?space=`, and `gatedSurfaces.ts` records the deliberate
      decision that a plane's notification link gets **no registry row of its own** — a row per
      producer would grow one row per future plane.
- [ ] Tests read the route's own `startsWith` gate, `rootPrefix`'s definition **and**
      `isSafeInAppPath` out of the TypeScript — the link is minted in Python and honoured by a
      TypeScript route rule, and nothing offline connects the two.

### FR-005: Help & guides

#### Acceptance Criteria:

- [ ] **There is exactly one guide covering these operations** — `rename-move-copy-delete` — not four.
      It is updated to say that folder and multi-item operations now run in the background and report
      by notification.
- [ ] Its warning callout ("Deleting is forever…") is the line that most needs changing, because a
      delete now succeeds **partially**. `send-files` and `archive-files` carry good wording precedents
      in the same file.
- [ ] A guide covers the conflict round trip: what a refusal means, and that re-submitting with
      overwrite is unrecoverable.
- [ ] Guides document only what is **shipped and wired end to end** (SPEC-074 FR-005).
- [ ] **A guide row costs THREE edits or the suite fails**: the `GATED_SURFACES` row, a `RECIPES` entry
      keyed by the exact accessible name, and a line in the transcribed contract table. Noted because
      the count is not obvious from the registry alone.
- [ ] SPEC-185's guide-recipe trap does **not** bite here — the guide lands in `files`, which is the
      section the Help page opens on. Recorded so nobody re-derives it.

### FR-006: The arc's live checks

#### Description:

A runnable script under `docs/testing/`, because a prose summary reads as vague to whoever has to act
on it.

#### Acceptance Criteria:

- [ ] `docs/testing/e2e.md` exists, with fixtures, exact labels, expected numbers and a
      section per spec, and is added to `e2e.md`'s sequence.
- [ ] **An approval gate.** These checks delete real files with versioning off and no trash;
      `e2e.md` maintains an explicit ask-before-running list and this belongs on it.
- [ ] **An identity note first, naming the ONE usable path.** A laptop IAM user cannot read or write
      `dat-prod-user-space`, and the verification role is deliberately not created — so fixtures are
      built and checks driven **through the portal UI**, not "an assumed role".
- [ ] **The >1,000-object fixture has a creation procedure**, through the portal upload queue, with its
      expected duration — otherwise the pagination check is unrunnable.
- [ ] **The lock check states its pass condition, and it is NOT SPEC-157's.** That plane's loser is
      refused; SPEC-187 FR-009 deliberately makes this one **wait**. So the observation is: execution B
      shows at least one `Wait` → re-acquire cycle and then succeeds, with two lock claims and **no**
      steal warning in `logs/service=file-ops/`. Pair the `send-message-batch` with a
      **several-hundred-object** source so the winner demonstrably still holds — a small folder
      finishes before the second execution starts, which is exactly how SPEC-157's own check failed.
- [ ] **The two-lock cross-space path is checked**: a copy from a personal space into a shared one
      takes both locks in digest-sorted order, and a request that acquires the first and loses the
      second **releases the first**. Deadlock-freedom on two locks is the class nothing offline proves.
- [ ] **The precondition-mismatch check names the right window.** "Between the copy and the deletion"
      is seconds. The reachable staging is a **long Map run over a large folder**, with a portal upload
      overwriting an object that was copied **early** while the Map still runs — the unlocked
      single-file path SPEC-187 Premise 3 names. Written the naive way, the tester modifies an object
      before it is copied, the new bytes copy, the ETags match, and the check passes vacuously.
- [ ] **A probe for the batch path's mismatch `Code` string**, which AWS does not document and a
      builder cannot get from the docs (SPEC-189 FR-006).
- [ ] The **per-item partial outcome** is checked in one request: one item refused while another
      completes.
- [ ] `visibilityState` is overridden before any check that waits for a notification — the inbox poll
      is paused while the tab is hidden, so a healthy run looks hung.
- [ ] Each check states its pass condition as an **observation** — a call count, an exact string, a
      trail record, an object that is absent — never "it looks right".

---

## File & Folder Structure

```
lambdas/file-ops-notify/          # the producer — needs locals.tf sizing and a
                                  # lambdas/test_deploy_matrix.py row like every other verb
lambdas/file-ops-common/focommon/messages.py   # + every outcome's wording
```

The execution role already holds `sqs:SendMessage` on the notifications queue (SPEC-187 FR-013), so
this spec needs no new grant. The producer is the arc's last function and the deploy matrix is the
gate SPEC-137 exists for.

## Implementation Phases

### Phase 1: The wire-shape escalation

- The optional structured field, `isValidRow`/`normalize`, the bound, the byte-identity test for
  existing rows, and `NotificationRow`'s conditional action.

### Phase 2: The producer and its wording

- The verb and its cannot-fail wiring; the one-message-per-run token; `focommon.messages` for every
  outcome and reason; the `duplicate` and `noop` sentences.

### Phase 3: The link

- The destination / source / common-prefix rules; the space-root build; the verify-and-cite gating
  tests reading the TypeScript route rule.

### Phase 4: Help

- The single guide's update, the conflict guide, and the three edits each new row costs.

### Phase 5: The live-check script and the run

- Write `docs/testing/e2e.md`; register it in `e2e.md` including the approval gate;
  then **run it**. Record what was discharged and what was only corroborated — settling a premise is
  not the same as running the check.

### Phase 6: Completion ritual — for the SPEC and for the ARC

- This spec's own ritual, plus the arc's: prune CLAUDE.md's Current work of everything the arc made
  stale, update the `ARCS.md` narrative with what the build actually found, and add the
  `architecture.md` *Control Planes* section for the finished plane — **owned here, as the arc closer,
  and struck from SPEC-189** — with the plane count corrected from six to seven.
