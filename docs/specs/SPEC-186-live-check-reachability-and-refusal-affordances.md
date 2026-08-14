# Spec: Live-Check Reachability, Refusal Affordances & Observability Fields

**ID:** SPEC-186
**Status:** Completed
**Last Updated:** 2026-08-14
**Depends On:** SPEC-144, SPEC-145, SPEC-157, SPEC-158, SPEC-170, SPEC-172, SPEC-173

## Overview

A live-check session against the deployed portal on 2026-08-14 discharged several long-owed checks
and, in doing so, found that a number of *other* owed checks cannot be performed at all — not
because the behaviour is broken, but because the assertion they name is unreachable from any
principal or surface a human actually has. A check nobody can run is indistinguishable from a check
that passes, which is the same failure class as SPEC-138's "did not run is never clean" and
SPEC-137's blind gates. This spec makes those checks reachable (or restates them honestly), closes
two places where a refusal is not announced through the fleet-wide affordance, fixes one clipped
listbox, and fills two log fields that ship empty.

It also carries one ordinary user-visible defect, found by eye rather than by script and traced to a
single line: **nine dialogs render at full viewport width** because `Modal`'s `max-w-md` default is
guarded by `??`, which does not fall back on the empty string `cx()` hands it. That one is FR-007,
it is the cheapest thing here, and it should land first because FR-003's measurements were taken
inside one of the oversized dialogs.

Everything else is about whether we can *prove* the behaviour, and whether a user is told *why*
something is refused.

## Scope

### In Scope

- Restating the three owed live checks that are unrunnable as written (SPEC-173's marker, SPEC-157's
  concurrency, SPEC-170's negative retrieval assertion), and making each one reachable by some
  principal
- Two `Button.disabledReason` gaps where a refusal is silent until after the user commits
- The Add-members suggestion listbox overhanging its dialog
- Nine dialogs rendering at full viewport width, from one empty-string sentinel in `Modal`/`cx`
- `env` and `version` shipping empty/`0.0.0` on every structured log record
- A roster that shows `Pending` for a member the same page shows `Active`
- Consolidating three copied recipient-chip lists that have already drifted, and bounding chip width
- A UI reuse sweep: five repeated patterns, including a shared `Badge` that is bypassed and drifting
- Correcting the live-check scripts whose wording invites a false bug report

### Out of Scope

- Any change to the refusal *behaviour* itself — `saved_queries` must stay undeletable, the archive
  guard must stay absolute, the removals opt-in must stay unchecked. This spec changes how refusals
  are *announced* and *verified*, never whether they fire
- Widening IAM merely to make testing convenient. FR-004 deliberately offers a read-only,
  audit-shaped option rather than a grant on the data path
- The Data Explorer arc's own live checks — those are SPEC-185's
- SPEC-149's `Description`/column-comment preservation check, which is blocked by the same Lake
  Formation gap FR-004 addresses but needs its own fixture work

---

## Functional Requirements

### FR-001: The saved-queries marker check must be performable

#### Description:

SPEC-173's sole owed live check reads: *delete `{username}/saved_queries/DO_NOT_DELETE.txt` through
the portal and confirm `AccessDenied`, then repeat in a shared space.* This cannot be done. The
marker is hidden **by basename**, so it can never be selected; and selecting the *folder* and
pressing Delete is refused **client-side** by `UNDELETABLE_ROOT_FOLDERS` before any S3 request is
issued. A network trace of both the personal and shared attempts shows **zero** `DeleteObject`
requests against the marker. The bucket-policy Deny on `*/DO_NOT_DELETE.txt` — the second layer of
defence, and the layer the check exists to prove — is therefore unverified in production.

The client-side layer *is* verified and works in both spaces, with the wording
`saved_queries — Saved queries live in this folder, so it can't be deleted.` and a control
(an ordinary empty folder) deleting cleanly beside it.

Split the check in two so each layer has its own assertion, and give the bucket-policy layer a
runnable procedure that does not depend on the app's own guard.

#### Acceptance Criteria:

- [ ] `docs/testing/` carries a saved-queries script with two separately-numbered checks: the
      client-side refusal (portal, personal and shared) and the bucket-policy Deny
- [ ] The bucket-policy check names a concrete procedure that issues a real `DeleteObject` at
      `{root}saved_queries/DO_NOT_DELETE.txt` without going through `useFileBrowser`'s guard, and
      states the expected `AccessDenied`
- [ ] The client-side check names the exact expected wording and requires the ordinary-folder
      control beside it, so a generic failure cannot be mistaken for the guard
- [ ] Neither check claims the other's assertion; the script says in one line why the portal cannot
      exercise the bucket policy

### FR-002: A refusal is announced before the user commits, not after

#### Description:

SPEC-172 established `Button.disabledReason` — `aria-disabled` rather than `disabled`, so the reason
is reachable in the tab order — as the fleet-wide way to say "unavailable, and here is why". Two
surfaces diverge:

1. **The file toolbar.** With `saved_queries` selected, Delete and Move render fully enabled: no
   `disabled`, no `aria-disabled`, no reason. The user opens a confirm that says
   *"Delete the folder "saved_queries" and everything inside it? … This can't be undone."*, presses
   Delete, and only then is told it was never possible. The most alarming confirm in the app is
   shown for an action that cannot happen.
2. **The refresh dialog reached from a `columns_removed` notification link.** Submit is natively
   `disabled` with no `title` and no reason, until the removals box is ticked. The banner above
   explains the situation, so this is the milder of the two — but it is still a refusal with no
   programmatically-associated reason.

#### Acceptance Criteria:

- [ ] Selecting a folder in `UNDELETABLE_ROOT_FOLDERS` renders Delete (and Move/rename where they
      are equally impossible) through `Button.disabledReason`, carrying the same sentence the
      post-confirm banner uses today
- [ ] That path issues no confirm dialog at all — the refusal is stated before the destructive
      confirm, never after it
- [ ] The reason is `aria-disabled` and reachable in the tab order, and is **not** the button's
      accessible name (SPEC-172's registry rule)
- [ ] The refresh dialog's submit carries a `disabledReason` naming the opt-in it is waiting on
- [ ] A test selects an undeletable folder and asserts no confirm is reachable; deleting the guard
      reddens it

### FR-003: The suggestion listbox fits inside its dialog

#### Description:

In **Add members**, typing one character returns 8 matches. The listbox renders `position: absolute`
at `z-index: 20` spanning y 472→682 while the dialog ends at y 585 — a **97px overhang**, clipped by
the dialog's `overflow: auto`. Only **3 of 8** options are fully visible. The options remain
*reachable* (the listbox scrolls internally, 259px of content in a 208px box), so this is a
usability defect rather than unreachable content — but it is exactly what SPEC-158's owed pass means
by "the list positions inside the panel", and it fails. Measured at 1400×900.

#### Acceptance Criteria:

- [ ] With 8 or more matches, the listbox's bounding box lies entirely within the dialog's, at
      desktop and at 400px
- [ ] All matches are reachable by keyboard, and the option under the active descendant is scrolled
      into view within the *visible* region, not merely within the listbox's own scroll box
- [ ] A test asserts the containment relationship numerically (listbox `bottom` ≤ dialog `bottom`),
      not by snapshot
- [ ] The same assertion covers the Share-table dialog's suggestion list under both share kinds

### FR-004: A verification principal exists for the archive vault and the catalog

#### Description:

Two owed assertions cannot be made by anyone today:

1. **SPEC-170's negative assertion** — that a `destination_occupied` refusal did **not** already
   initiate retrieval — requires `head-object` on `dat-prod-archive` to show `StorageClass: GLACIER`
   and **no** `Restore` header. That bucket explicit-denies the laptop IAM user, its execution role
   trusts `lambda.amazonaws.com` only, the deploy role is GitHub-OIDC-only, and **no CloudTrail
   trails exist**, so there is no independent record of whether `RestoreObject` was called. The
   script itself states a refusal that had already started retrieval "looks identical from the UI",
   so there is no UI proxy — and the cost of being wrong is 3–5 billed, uncancellable hours.
2. **Read-backs against Glue** — SPEC-149's preservation check and SPEC-153's owed foreign
   projection fixture — fail with `Insufficient Lake Formation permission(s): Required Describe`.

Provide a way to make these assertions that does not widen the data path. CloudTrail S3 data events
on the archive bucket are the preferred shape for (1): they are read-only, they are the audit record
the plane arguably should have anyway, and they answer "was `RestoreObject` ever called for this
run" directly rather than by inference.

#### Acceptance Criteria:

- [ ] `RestoreObject` against the archive bucket is recorded somewhere a human with read-only access
      can query, keyed so a single archive run's calls can be isolated
- [ ] SPEC-170's script asserts the negative from that record, and states explicitly that a UI
      observation does not substitute
- [ ] A named principal can `GetTable` / `GetTableVersions` in the catalog for verification, with no
      write capability and no grant on any data bucket
- [ ] Neither grant appears in `portal-role-permissions`, and the plan-scan accept list is unchanged
      or gains an entry with a written disposition (SPEC-139's rule)

### FR-005: `env` and `version` carry real values

#### Description:

Every structured log record written today carries `"version": "0.0.0"` and `"env": ""`. Confirmed on
`logs/service=auth/` and `logs/service=shared-space/`. The fields exist precisely so records can be
filtered by environment and correlated to a deploy, and both are inert. This is invisible with one
environment and actively misleading with two.

#### Acceptance Criteria:

- [ ] `env` resolves to the deployed environment name on every record, from the same source of truth
      the feature-flag document uses
- [ ] `version` resolves to something that identifies the deployed artefact (commit sha or release
      tag), not `0.0.0`
- [ ] Neither value is supplied per call site — both come from `cpcommon.observability`, the only
      door (SPEC-127)
- [ ] A test asserts both are non-empty and that `version` is not the placeholder

### FR-006: Live-check scripts stop inviting false bug reports

#### Description:

Two scripts describe procedures that cannot produce the outcome they claim, and a careful tester
following them will file a defect against working code:

1. **The refresh arc's FR-010 sequence** says *"add a file with a new column, refresh and confirm it
   appears."* Schema inference probes exactly **one** sample object — the first key in listing order
   (`sample_by_format.setdefault(fmt, key)` in `inspect-source`). A column added in a file that
   sorts *later* is invisible **by design**, and the refresh correctly reports
   `already up to date`. This was hit live and read as a defect until the code was checked.
2. **SPEC-157's concurrency check** says *"submit two refreshes in quick succession from the UI."*
   Two submits **2 seconds apart** — the floor achievable with two pre-armed browser tabs — both
   returned independently with no `refresh_already_running`, because a small table's refresh
   completes inside that window. The lock is never contended, so the check cannot pass or fail from
   the UI at all.

#### Acceptance Criteria:

- [ ] The refresh script states that inference samples one object, that the sample is the first key
      in listing order, and that the added column must be in a file that **sorts first**
- [ ] The refresh script's fixture list names a file whose name guarantees that ordering
- [ ] SPEC-157's check names a method that forces genuine contention, and states the observed fact
      that two UI submits 2s apart do not
- [ ] Any procedure requiring a raw ID token says so up front, and says where it is read from and
      that it must not be pasted into shell history

### FR-007: `Modal`'s width default cannot be defeated by an empty class string

#### Description:

**Nine dialogs render at full viewport width.** `New folder` and `New shared connection` were both
measured at **1372px in a 1400px viewport with `max-width: none`**, against `Create table`'s correct
**448px / `max-w-lg`**. This is one root cause with nine surfaces, and it is a language-level trap:

- `cx()` returns **`''`** when no argument is truthy — its return type is `string`, never `undefined`
- `FormDialog` passes `cx(scrollBody && 'flex max-h-[85vh] flex-col', className)` down to `Modal`
- `Modal` applies its default as `className ?? 'max-w-md'`, and **`??` does not fall back on an
  empty string**

So a `FormDialog` whose own tag passes neither `className` nor `scrollBody` hands `Modal` an empty
string, the `max-w-md` default never applies, and the panel's `w-full` takes the whole viewport.
`Modal`'s doc comment already warns "no tailwind-merge, so don't expect a passed `max-w-*` to layer
on top of a default" — the hazard is that *not* passing one is silently worse than passing a wrong
one.

Affected (no `className`, no `scrollBody` on the `<FormDialog>` tag): `CreateFolderDialog`,
`CreateSharedConnectionDialog`, `AddMembersDialog`, `RenameDialog`, `CreateViewDialog`,
`SaveQueryDialog` (two call sites), `FilterValueDialog`, `RestoreArchiveDialog`. Two are measured;
the rest share the identical static signature.

Fix the sentinel, not the nine call sites — patching each one leaves the next dialog to fall in.

#### Acceptance Criteria:

- [ ] A `FormDialog` that passes neither `className` nor `scrollBody` renders at the standard
      bounded width, with a computed `max-width` that is not `none`
- [ ] The fix is in the shared layer — either `cx` returns `undefined` when it has nothing to join,
      or `Modal` treats an empty string as absent — and **not** by adding a width class to each
      affected dialog
- [ ] If `cx`'s return type changes, every call site still type-checks under `npm run build`
- [ ] All nine dialogs above are confirmed bounded, at desktop and at 400px
- [ ] A test renders a `Modal` with `className=""` and asserts the default still applies; reverting
      the sentinel reddens it
- [ ] `AddMembersDialog` is re-measured for FR-003 **after** this lands — its listbox overhang was
      measured inside a full-width dialog, so the containment numbers may change

### FR-008: The roster does not contradict the connections list

#### Description:

For one membership, at one moment, the app states two different things:

- **Connections row:** `livecheck_0814a | Member | Active | owner: agriffith_three`
- **Members roster (same page, one click away):** `agriffith | Pending`, under the explanatory line
  *"A Pending member has been invited but hasn't signed in yet; they become Active once they do."*

The reader of that sentence **is** the member, and they **have** signed in — that is what flipped
their own row to Active. **Refresh does not reconcile it**: the drawer's own Refresh control was
pressed and the roster still read Pending.

This follows from the composition of two settled decisions rather than from a bug in either.
SPEC-073's `acknowledge-membership` flips pending→active as display/bookkeeping; SPEC-075's
`cache.write_roster_to_all` fans out **on add/remove/leave** — a list that does not include
acknowledge. Confirmed in `logs/service=shared-space/`, which shows `roster fanned out` under
`add-members` and nothing equivalent afterwards. So every roster copy keeps the status frozen at
add time until somebody is added or removed, and the roster is the **only** member-facing view of
who is in a space.

Deciding *how* to close it is in scope for the build: fanning out on acknowledge is the obvious
move but adds a write to a hot path; deriving the chip from the reader's own membership where it is
known, or softening the sentence so it cannot be false, may be cheaper. **What is not acceptable is
the app asserting both.**

#### Acceptance Criteria:

- [ ] A member who has signed in is never shown as `Pending` in a roster while the same session's
      connections list shows them `Active`
- [ ] The explanatory sentence is never rendered to a reader for whom it is false
- [ ] Whatever mechanism is chosen, a test drives add → acknowledge → read roster and asserts the
      two surfaces agree; reverting the mechanism reddens it
- [ ] If the fix is a fan-out, `logs/service=shared-space/` records it the way `add-members` does,
      and the roster's failure to update does not fail the acknowledge

### FR-009: One recipient-chip component, consistent and bounded

#### Description:

Reported as chips "listing on top of each other rather than left to right", then refined to: if they
already flow and wrap, just make sure it is **consistent**.

**Validated: the wrapping is consistent and correct.** All three lists use
`flex flex-wrap gap-1.5`, all three `<li>` class strings are byte-identical, and Share table was
measured live wrapping 6 chips over 3 rows. Nothing needs changing there.

**But they are three copies, not one component, and they have already drifted** — which is the
SPEC-155 reuse smell, caught here before it produced a user-visible difference:

| | `UsernameChipsField` | `TableShareDialog` | `SendFilesDialog` |
|---|---|---|---|
| `<ul>` | `mt-2 flex flex-wrap gap-1.5` | `mb-2 …` | `mb-2 …` |
| `<li>` | identical | identical | identical |
| Remove button | **`h-6 w-6`** (24px) | **`h-5 w-5`** (20px) | **`h-5 w-5`** (20px) |

Two live divergences: the chip block's margin sits on opposite sides, and **the remove target is
20×20 in two of the three against 24×24 in the first**. 24×24 CSS px is WCAG 2.2 SC 2.5.8's
minimum, so `UsernameChipsField` meets it and the other two do not. Consistency here is currently
coincidence — nothing enforces it, and the copies have already begun to diverge.

**Width is unbounded in all three.** No chip carries `max-w-*`, `truncate` or `min-w-0`, and the
name renders full-length in `font-mono`. Measured in Share table's 413px list: `mrag` 103px,
`malathi` 126px, `denapolia` 142px, `adamparker` 150px, `tencalade27` 158px — roughly **62px of
chrome + ~8.7px per character** (derived, not measured directly). At a 400px viewport the list is
~333px, so a name of about **12 characters or more is one chip per row**; and since usernames are
`^[a-z][a-z0-9_]{2,62}$`, a **63-character name extrapolates to a ~610px chip, wider than the 448px
dialog containing it**. That is the original symptom's real cause, and it is worth fixing while the
three are being consolidated.

#### Acceptance Criteria:

- [ ] One chip component renders all three lists; the duplicated `<li>` markup is gone from
      `UsernameChipsField`, `TableShareDialog` and `SendFilesDialog`
- [ ] The remove target is **at least 24×24 CSS px** in every list
- [ ] Wrap behaviour is unchanged — chips flow left-to-right and wrap at the container width
- [ ] A chip never exceeds its list container's width, at desktop and 400px, for a username at the
      **63-character maximum**; an over-long name truncates visually with the full value available
      on hover/focus, and the remove button stays visible and clickable at any name length
- [ ] The remove button's **accessible name is unchanged** and still carries the full username —
      SPEC-163's registry queries buttons by accessible name, and SPEC-172 forbids the reason
      becoming the name
- [ ] Callers keep their own outer spacing (the `mt-2`/`mb-2` difference is positional, not drift to
      normalise away) — the component owns the chip, not the block's margin
- [ ] A test renders a maximal-length username and asserts the chip's width does not exceed its
      container's; a second asserts the three lists render the same chip markup

### FR-010: Adopt the shared primitives that already exist, before adding more

#### Description:

A sweep of `apps/portal/src` for repeated markup found that the most common problem is **not missing
components — it is existing components being bypassed and then drifting**. `components/Badge.tsx`
ships a neutral pill and is imported by **two** files, while three others hand-roll the same thing,
each differing from `Badge` by one or two tokens. This is SPEC-155's finding recurring in a
different layer, and FR-009's three-copied-chips is one instance of it.

Five patterns, each measured:

| # | Pattern | Sites | State |
|---|---|---|---|
| A | **Status pill with a dot** — `inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold` + `h-[7px] w-[7px] rounded-full bg-current`, tone and pulse interpolated | 6 | No component exists; `Badge` cannot express tone/dot/pulse |
| B | **Neutral tag** | 3 + `Badge` | `Badge` exists, used by 2 files; the 3 hand-rolled copies each drift (`bg-surface` vs `bg-surface-2`, `px-2.5` vs `px-2`, `font-semibold` vs `font-medium`, border present/absent) |
| C | **Dialog body chrome** — `flex max-w-lg flex-col px-5 pb-4 pt-5` + `text-md font-semibold text-text` heading + a hand-built footer | 4 | These use `<Modal>` directly and re-implement what `FormDialog` provides; 3 of the 4 reference `FormDialog` zero times |
| D | **Field label + hint** — `mb-1.5 block text-sm font-medium text-text` and `mt-1.5 text-xs text-text-3` | 5 / 5 | `components/Input.tsx` owns both strings; five features re-implement them rather than using `Input` |
| E | **Section caption** — three competing strings for one idea: `…font-semibold uppercase tracking-wide text-text-3`, `…font-medium uppercase tracking-wide text-text-2`, `…font-semibold uppercase tracking-[.04em] text-text-3` | 11 | Already three-way drifted; no owner |

A: sites are `MembersList`, `ConnectionsPage`, `DataQualityRunRow`, `QueryHistoryRow`, `UploadList`,
`DataQualityReportPage`. B: `MembersList`, `ConnectionsPage`, `DataQualityRunRow`.
C: `StartQualityCheckDialog`, `MoveDialog`, `CopyDialog`, `SaveResultsDialog`.

**Note the direction of C.** The four dialogs that hand-roll their chrome all pass an explicit
`max-w-lg` and are therefore *unaffected* by FR-007, while the nine that correctly use `FormDialog`
are the broken ones. Bypassing the abstraction accidentally dodged the abstraction's bug — which is
an argument for fixing the shared layer, not for copying more.

#### Acceptance Criteria:

- [ ] A status-pill component owns pattern A — tone plus optional dot and pulse — and all six sites
      use it; no `h-[7px] w-[7px] rounded-full` literal remains outside it
- [ ] The three hand-rolled neutral tags use `Badge`; where a site genuinely needs different
      styling, that variant is a prop on `Badge`, not a copy
- [ ] The four `<Modal>`-direct dialogs either move to `FormDialog` or state in a comment why they
      cannot (Enter-to-submit semantics differ — SPEC-155 and SPEC-172 both turn on this, so
      "cannot" is a legitimate answer that must be written down)
- [ ] The five re-implemented field labels/hints use `Input`
- [ ] Pattern E resolves to **one** caption style with one owner
- [ ] Behaviour is unchanged everywhere — this is consolidation, and any visual difference is called
      out deliberately the way SPEC-155 FR-007 called out its byte-formatter change
- [ ] A guard fails if a second copy of the status-pill or chip markup appears, on the precedent of
      SPEC-165's one-builder AST sweep

> **Scope judgement for the human.** SPEC-155 was an entire spec for one reuse-and-structure pass,
> and this is a second one. Landing it inside SPEC-186 — whose theme is live-check reachability and
> refusal affordances — widens that spec considerably. If FR-009 and FR-010 are built together they
> may deserve their own spec, with SPEC-186 keeping only the verification and refusal work.
>
> **RESOLVED (2026-08-14, user decision): all ten FRs are built here.** No SPEC-187 split. The
> sweep found more than the spec enumerated — a seventh status-pill site the list of six missed,
> and 22 files carrying a section caption where the spec counted 11 — which is the argument for
> having done it in one pass with one guard rather than against a list.

---

## Data Model

No new persisted shapes. FR-002 reuses the existing prop:

```ts
// apps/portal/src/components/Button.tsx (existing)

type ButtonProps = {
  /** Renders aria-disabled with an associated reason, reachable in the tab order.
   *  Never becomes the accessible NAME — registry rows query buttons by name. */
  disabledReason?: string;
};
```

FR-005 changes only the value of two fields already on every record:

```jsonc
{ "service": "auth", "version": "<commit-sha>", "env": "prod" }
```

---

## File & Folder Structure

```
docs/
├── specs/
│   └── SPEC-186-live-check-reachability-and-refusal-affordances.md
└── testing/
    ├── saved-queries-e2e.md          # new — FR-001's two-layer script
    ├── archive-restore-e2e.md        # amended — FR-004 negative assertion
    └── table-builder-e2e.md          # amended — FR-006 sampling + contention

apps/portal/src/
├── components/
│   ├── Modal.tsx                     # FR-007 — the empty-string fallback
│   ├── FormDialog.tsx                # FR-007 — what it hands Modal
│   └── Button.tsx                    # FR-002 — disabledReason (existing prop)
├── lib/cx.ts                         # FR-007 — returns '' where callers expect undefined
└── features/
    ├── file-browser/                 # FR-002 toolbar refusal; FR-007 CreateFolder/Rename
    ├── shared-spaces/                # FR-003 listbox; FR-007 AddMembers/CreateSharedConnection
    ├── saved-queries/                # FR-007 SaveQueryDialog (two call sites)
    ├── data-explorer/                # FR-007 FilterValueDialog
    ├── archive/                      # FR-007 RestoreArchiveDialog
    └── query/                        # FR-002 refresh dialog submit; FR-007 CreateViewDialog

lambdas/common/cpcommon/observability.py   # FR-005
infra/                                     # FR-004 trail + verification principal
```

## Implementation Phases

### Phase 1: Dialog width sentinel (FR-007)

- Fix the empty-string fallback in the shared layer, once
- Confirm all nine dialogs are bounded at desktop and 400px
- Land this **before** FR-003 — the listbox containment numbers were measured inside a full-width
  dialog and will move

### Phase 2: Refusal affordances (FR-002, FR-003)

- Route the undeletable-folder refusal through `Button.disabledReason` and remove the confirm on
  that path
- Give the refresh dialog's submit a reason naming the opt-in
- Re-measure, then constrain the suggestion listbox within its dialog; add the numeric containment
  assertion
- Cover both dialogs (Add members, Share table) under both share kinds

### Phase 3: Chip and primitive consolidation (FR-009, FR-010)

- One chip component; remove target to 24x24; bound chip width
- Adopt `Badge` for the neutral tags and reconcile the drift
- A status-pill component for the six dot-pill sites
- Resolve the caption style to one owner; move the re-implemented labels onto `Input`
- Decide the four `<Modal>`-direct dialogs: adopt `FormDialog` or record why not
- Add the copy guard

### Phase 4: Observability fields (FR-005)

- Resolve `env` and `version` inside `cpcommon.observability`
- Assert non-placeholder values

### Phase 5: Verification access (FR-004)

- CloudTrail S3 data events on the archive bucket, scoped and dispositioned
- A read-only catalog verification principal
- Expand the deploy role as in-scope work (CLAUDE.md infra rule); re-run the plan scan and record
  the disposition

### Phase 6: Script corrections (FR-001, FR-006)

- Split the saved-queries check into its two layers
- Correct the sampling and contention wording
- Amend the archive script's negative assertion to read from the new record
