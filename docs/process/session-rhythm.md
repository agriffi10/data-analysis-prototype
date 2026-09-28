# The session rhythm


This is the operating loop, start to finish. CLAUDE.md's *Session Workflow* carries the entry
sequence and the gates whose specifics live nowhere else, and **points here for the rest rather
than restating it** — the second hand-synced copy is how the two drifted before (#595).
**If they ever disagree, CLAUDE.md wins** — fix the drift here in the same session you notice it.

**Start of session**
1. Read CLAUDE.md, then the **current** spec in full. Don't infer scope from a prior conversation —
   read the spec file as it exists now.
2. For reuse, read the `apps/portal/info/component-inventory/<area>.md` file(s) the spec touches, and
   the `lambdas/info/planes/<plane>.md` page for any plane it changes; pull only the
   `architecture.md` section you need, the `## Fences` of each `docs/decisions/` area the spec
   touches, and then only the `decisions/` entry / dependency delivery-doc you actually need.
3. **Confirm `main` is green, verdict first:** `python3 scripts/watch_ci.py --branch main --once`.
   Then each path-filtered deploy's last outcome, read as `ci-and-deploy-traps.md` says.
   Investigate failures before building.
4. **Branch from fresh `main`:** `git fetch && git switch -c <branch> origin/main`.
5. **Generate and validate a plan before writing code.** Turn the spec's Implementation Phases into a
   concrete implementation plan, then validate it against the spec (every FR + acceptance criterion is
   covered, reuse from the component inventory is used, no out-of-scope work crept in). The plan —
   not per-phase checkpoints baked into the spec — is what gates the work.
6. **Put the plan through the reviewer gate before the first line of code** (*The reviewer contract*,
   below). A plan is reviewed for the same reason a PR is: the author cannot see what they assumed.
7. **Put the PR grouping through the same gate**, before the first push. Group consecutive phases
   into as few PRs as the dependencies allow — a phase is a unit of work, not a unit of PR, and the
   useful boundaries are inert-vs-live, either side of a switchover, a deletion following its last
   caller, and infra that must apply before a live check.

**These two reviews are the only ones that gate the START of the build.** Once the plan and the
grouping have each been reviewed, the build runs to completion without checking in. This does
**not** retire the diff reviews — those gate the push, at the other end, and they are blocking
too. Four reviews stand between a spec going In Progress and its PR merging: one on the plan
before the first line of code, one on the PR grouping, and two on the diff — all four before the
first push. The user confirmed the work when they set the spec going; a per-phase check-in re-asks
a question already answered.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- **An acceptance criterion that cannot settle before the push does not pass the pre-push review —
  it is recorded as owed on the PR.** A criterion that closes "against a green CI run" is
  undecidable while the branch is still local, and the failure mode is a reviewer ticking it
  vacuously. Name it in the PR body's **Owed** list, settle it on the green run, and do not merge
  until it is settled. `docs/testing/owed.md` is a different ledger — live checks no signed-in
  session can run at all.
- **The diff reviews run BEFORE the push, not before the merge — and there are two of them.** Commit
  locally, run the gates, send the diff to **two** fresh-context reviewers in **different frames**
  (*The reviewer contract*, below), fix or explicitly reject every finding — *then* push and open
  the PR. Pushing first inverts the gate: the branch is public, the fixes arrive as follow-up
  commits, and the review becomes commentary on what already happened. Rotating the frame
  (`docs/reviewer-contract.md`) happens in the same window. A push is the point of no return for
  the review, the same way the merge is for CI.
- Before pushing, run the **formatter, both linters, both suites, mypy and `npm run build`**
  locally, green by **exit code**. **CI runs the build and the validators, nothing else**, so this
  is the ONLY place the rest run: skip one and it reaches `main` behind a green PR. **That list is a
  floor, not the set: also run whatever `ci.yml` runs on the branch** — the contract, doc, flag and
  path validators and the hook corpus — including after a rebase, when a job can newly go red on
  work that was green before `main` moved. A gate that itself changed runs its corpus too
  (`validate_docs_test.py`; `pre_push_test.py`, `pr-queue-test.sh`, `install-test.sh`). Traps:
  `ci-and-deploy-traps.md`.
- Work the **reviewed** plan's phases in order, **straight through to completion**. Summarize a phase
  in passing where it is worth saying, but do not end the turn on it — a summary that ends the turn
  *is* a request for approval, whatever its wording says, and so is a list of options written out in
  prose: when a decision genuinely needs the human, ask it (the triage below says how). Re-review
  the plan only if the phase changed it — a phase that revises the plan has produced a new artifact,
  and it goes through the gate as one. A spec revised mid-build does this from the other side: if a
  phase now delivers a requirement the spec no longer carries, that plan is a new artifact too.
- **Stop only for a question that genuinely needs an answer:** a product-changing or ambiguous call,
  a finding that changes scope, a phase discovering the plan was wrong. Reporting is not the same act
  as asking, and doing the first while intending the second is how the build stalls.
- Before writing code in a domain that has a rulebook (React, accessibility, Lambda shape, Python),
  route through `docs/best-practices/INDEX.md` and load only the relevant section(s). Apply the
  rules as you write; flag (don't silently break) any that conflict with existing code.
- **Three disciplines whose long form and evidence are `docs/reviewer-contract.md`:** when a
  finding is an instance of a RULE, re-audit the rule, not the line — enumerate the population
  first; spot-check a negative claim ("no test covers this") before acting on it and again before
  writing it down, whoever made it; a mechanical sweep REPORTS before it applies, and its result is
  checked by diffing test names collected from the runner, never a pass count or a source grep.
- Specs ship with **no Open Questions** — they're resolved during authoring (`authoring-a-spec.md`). An issue that emerges
  mid-build is triaged by *kind*, not parked — and the test for the kind is **what the wrong choice
  would cost**: a revert or a follow-up commit, decide; a product outcome the user would have to live
  with, ask:
  - **Reversible / technical** (naming, file layout, which helper to reuse, an obvious bug fix): just
    decide in-session and keep moving. If it changes scope or contradicts the spec, **update the spec**
    rather than leaving the divergence implicit.
  - **Product-changing / ambiguous** (anything that alters behavior the user would notice, or a call
    with no clearly-right answer): **stop and escalate to the human.** Don't silently pick — ask with
    the **question tool** (`AskUserQuestion`), the options as selections and the recommended one
    first, and go on with the answer; options written out in prose that end the turn are the same
    stop by another name. Auto-deciding these is how an autonomous run drifts away from what was
    actually wanted.
  - **The spec contradicting itself** (two FRs that cannot both hold): a spec defect, not a
    preference call, and the tie-break is evidence — implement **each** reading, run the suites, and
    record the verdict in the spec. One reading run to red settles nothing. `docs/reviewer-contract.md`
    (*Adjudicating two FRs that cannot both hold*) carries the method, and the three outcomes that
    escalate instead of settling.

**The reviewer contract — three artifacts, one gate**

A **spec**, an implementation **plan** and a **diff** each go to a reviewer in a **fresh context** —
a new session or a subagent, never the context that produced them. A spec is not Draft-ready, a plan
does not start code, and **a branch does not reach the remote**, until every finding is either
**fixed** or **flagged**. The spec and the plan get one reviewer each; the diff gets two, in
different frames. A rejection costs a sentence out loud, and only goes in writing when it carries a
lesson worth keeping.

Cap same-frame rounds at two, then rotate. Exit on the **trajectory** of the findings — stop when a
fresh frame's worst finding is one that would not change the built result, and say which finding
that was — never on a round count, and never by waiting for an empty round.

**The method is `docs/reviewer-contract.md`** — how many reviewers and where they run, briefing one
(the four lines that change what comes back), rotating the frame, when a review changes a *rule*
rather than a line, and the worked evidence behind each. Read it when you are about to spend a
reviewer; it is not session-start material, which is why it is not in this file.

**Landing the spec — watch PRs and watch `main`**
- **The instruction to build the spec is the authorization for everything in this section.** Pushing
  the reviewed branch, opening the PR, watching it and merging it on green are the last steps of the
  build, not new decisions: do not stop to ask for them, and do not stop after announcing them — a
  session whose turn ends at "I'll open the PR" has not built the spec. What still stops the session
  is a product-changing call or a permission the harness refuses; say which, and ask with the
  question tool. The repo's `.claude/settings.json` allows the gates and the landing commands; a
  refusal means that file is not in effect here.
- **A branch reaches the remote already reviewed.** The gate above is the precondition for the push,
  so a PR opens carrying work whose findings are already fixed or answered. If a review
  round happens after a push anyway — a late finding, a rotated frame, a reviewer that ran long — its
  fixes are committed and reviewed locally before the next push, rather than each one going up as it
  lands.
- **Every PR is watched to completion and merged as soon as CI is green** — don't open a PR and walk
  away. A spec's PR merges only on green.
- **`main` is always watched.** After any merge, confirm `main`'s build went green. If `main` fails,
  **diagnose immediately and fix it with a new PR** — a red `main` is the top priority and blocks
  starting the next spec.
- **Re-verify `main` is green** before starting the next spec (land before starting the next).
- Then run the completion ritual (`completion-ritual.md`).
