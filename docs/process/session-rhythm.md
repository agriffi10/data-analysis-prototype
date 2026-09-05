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
3. Confirm CI is green: `gh run list --branch main --limit 5`. Investigate failures before building.
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
first push. The user
confirmed the work when they set the spec going; a per-phase check-in re-asks a question already
answered, and on a twelve-phase spec it asks it twelve times.

**During the build — one spec, in phases**
- Every file-changing task is done on its **own branch** and opened as a **PR** — automatically, without
  waiting to be asked. Never commit to `main` directly.
- **An acceptance criterion that cannot settle before the push does not pass the pre-push review —
  it is recorded as owed on the PR.** A criterion that closes "against a green CI run" is
  undecidable while the branch is still local, and the failure mode is a reviewer ticking it
  vacuously. Name it in the PR body's **Owed** list, settle it on the green run, and do not merge
  until it is settled. This is a different ledger from `docs/testing/owed.md`, which holds live
  checks that cannot be run from a signed-in session at all; a criterion that merely needs CI to
  go green belongs on the PR and is discharged there.
- **The diff reviews run BEFORE the push, not before the merge — and there are two of them.** Commit
  locally, run the gates, send the diff to **two** fresh-context reviewers in **different frames**
  (*The reviewer contract*, below), fix or explicitly reject every finding — *then* push and open
  the PR. Pushing first and reviewing after inverts the gate: the branch is already public, the fixes
  arrive as follow-up commits, and the review reads as commentary on something that has already
  happened rather than as the thing that decides whether it should. Rotating the frame
  (`docs/reviewer-contract.md`) happens in the same window. A push is the point of no return for the review, the same way the merge is the
  point of no return for CI.
- Before pushing, run the **formatter, both linters, both suites, mypy and `npm run build`**
  locally, green by **exit code**. **CI runs the build and the validators, nothing else**, so this
  is the ONLY place the rest run: skip one and it reaches `main` behind a green PR. Traps: `ci-and-deploy-traps.md`.
- Work the **reviewed** plan's phases in order, **straight through to completion**. Summarize a phase
  in passing where it is worth saying, but do not end the turn on it — a summary that ends the turn
  *is* a request for approval, whatever its wording says. Re-review the plan only if the phase
  changed it — a phase that revises the plan has produced a new artifact, and it goes through the
  gate as one.
- **Stop only for a question that genuinely needs an answer:** a product-changing or ambiguous call,
  a finding that changes scope, a phase discovering the plan was wrong. Reporting is not the same act
  as asking, and doing the first while intending the second is how the build stalls.
- Before writing code in a domain that has a rulebook (React, accessibility, Lambda shape, Python),
  route through `docs/best-practices/INDEX.md` — which names the tree each rulebook lives in — and
  load only the relevant section(s). Apply the rules as you write;
  flag (don't silently break) any that conflict with existing code.
- **When a finding is an instance of a RULE, re-audit the rule — not the line.** Fixing the one
  reported site leaves every other instance shipped, so enumerate the whole population first: that
  is the difference between a registry with a walking test and a hand-maintained checklist, and a
  hand-maintained list rots. Long form: `docs/reviewer-contract.md`.
- **Spot-check a negative claim before acting on it, and again before writing it down.** "No test
  covers this", "nothing imports this file", "it is only documented on page X" — each asserts an
  absence, which is what a search proves worst. Verify it yourself whether a reviewer said it or
  you did. A wrong claim entering **code** has tests to catch it later; one entering a spec, a
  register entry, a docstring or a commit message has nothing, and the next session reads it as
  settled. Long form, with the two that shipped as source comments and were believed for weeks:
  `docs/reviewer-contract.md`.
- **A mechanical sweep REPORTS before it applies.** Print what it would change, read the list, then
  re-run with `--apply`, and check the result by diffing **test names collected from the runner**
  — never a pass count, and never a source grep, which cannot see an `it.each` row. Parse rather
  than regex where a parser exists. Long form: `docs/reviewer-contract.md`.
- Specs ship with **no Open Questions** — they're resolved during authoring (`authoring-a-spec.md`). An issue that emerges
  mid-build is triaged by *kind*, not parked:
  - **Reversible / technical** (naming, file layout, which helper to reuse, an obvious bug fix): just
    decide in-session and keep moving. If it changes scope or contradicts the spec, **update the spec**
    rather than leaving the divergence implicit.
  - **Product-changing / ambiguous** (anything that alters behavior the user would notice, or a call
    with no clearly-right answer): **stop and escalate to the human.** Don't silently pick — surface the
    options with a recommendation. Auto-deciding these is how an autonomous run drifts away from what
    was actually wanted.

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

**An Open Question can wear a declarative sentence**

`CLAUDE.md` forbids a spec carrying Open Questions, and the check is easy to pass while failing.
SPEC-205 shipped the sentence *"either the exception moves to a shared location or `save_members`
returns a refusal the caller raises. The spec states which"* — and then did not. A sentence that
**promises a decision** is an Open Question with a declarative shape; so is an acceptance criterion
demanding a **computed** bound while supplying none of its inputs. Both were caught by an implementer
who had to pick, and neither by a reader.

**Landing the spec — watch PRs and watch `main`**
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
