# The Reviewer Contract

**Pulled when you are about to spend a reviewer** — at a spec's gate, a plan's gate, or before a
branch reaches the remote. It is the long form of `docs/process.md` §3's gate: which artifacts are
reviewed, how many reviewers each gets and where they run, how to brief one, how to rotate the
frame, and how to know when to stop. `docs/process.md` carries the rule; this file carries the
method behind it.

---

**The reviewer contract — three artifacts, one gate**

Nothing reaches the next stage on its author's own judgement. A **spec**, an **implementation plan**
and a **diff** each go to a reviewer in a **fresh context** — a subagent or a new session, never the
context that produced the artifact. An author reviewing their own work assumes its output was
intended and rubber-stamps it; that is as true of a plan as of code, and a wrong plan is the more
expensive one to leave *undetected*, because the code that follows will faithfully implement it.

**How many reviewers, and where.** **One** on the spec when it is written, **one** on the
implementation plan when the build actually starts, and **two** on the diff before it is pushed —
plus the narrow pass on the PR grouping, which `docs/process.md` §3 places before the first push. The diff gets two because it is the **widest**
artifact and the last one before the branch goes public: a spec or a plan is one document a single
reader can hold whole, while a diff spans code, infrastructure and tests *and* the criteria they
are supposed to satisfy, and the method's measured history (*Rotating the frame*, below — measured
on a sibling repo, not here) is that the first differently-framed pass over a change finds a class
the previous frames could not see: after eight rounds spread across the spec, its revisions and
the code, the first rotation found ~25 further defects. That evidence argues for a **different
frame**, not for the number two; two is the floor because one frame is demonstrably not enough
and a floor has to be a number.

The two are **two frames, not two rounds** — the same frame run twice buys wording — and they are
not free picks. One starts from the **change** and reads it against what it is supposed to
satisfy; the other starts from **something other than the change**, which is the same requirement
as "at least one pass must start from the feature, not the diff" below. On a code diff those are:
the spec's acceptance criteria plus the `best-practices/` rules for the domains it touches, and a
pass that **builds** the thing and runs the suites rather than reading it. On a diff with no code
in it — a spec, a plan, a docs change — they are: the artifact against its own sources, and the
artifact against every *other* place the same rule is stated. Both land **before** the push; a
review that only happens once the branch is public does not count toward the two.

Every count here is a **floor**, not a cap, but the two floors work differently and should not be
read across. **On a diff**, two is a minimum before a push: a clean first review does not close
the gate, because "the reviewer found nothing" means nothing within the frame it was given, and
the exit rules below decide when to stop *above* two. **On a spec or a plan**, one review closes
the gate — a clean review there is an answer. What makes that count a floor is **re-entry**: a
revised artifact is a new artifact and goes back through the gate as one, which is why a phase
that rewrites the plan sends the new plan through again.

- **The gate is blocking, and what it asks for is an answer, not a filing.** A spec is not
  Draft-ready, a plan does not start code, and a branch does not reach the remote, until every
  finding has been either **fixed** or **flagged** — said out loud, so the call is visible and can be
  argued with. A finding silently dropped is a finding that was not reviewed; a finding rejected in
  one sentence is a finding that was. **Write a rejection down only when it carries a lesson worth
  keeping** — then it belongs in the register or the spec, as reasoning, not as a paper trail.
- **The reviewer gets the artifact and its sources, never the author's reasoning.** For a spec: the
  spec file, its arc entry in `ARCS.md`, the `decisions/` entries it claims to follow, and the specs
  it depends on. For a plan: the plan, the spec, and the
  `apps/portal/info/component-inventory/<area>.md` files the spec touches. For a diff: the diff, the
  spec's acceptance criteria, and the `best-practices/` rules for the domains it touches (route via
  their INDEX). Handing over the authoring rationale tells the reviewer what to conclude.
- **What each review is for.** A **spec** review asks: is every FR testable and binary; does any
  acceptance criterion pass vacuously; is anything in Out of Scope actually required by an FR; does
  it contradict a settled `decisions/` entry or silently supersede one without saying so; are there
  Open Questions wearing declarative clothes. A **plan** review asks: does every FR and acceptance
  criterion have a phase that delivers it; is existing reuse used rather than re-built; has
  out-of-scope work crept in; is a phase resting on a premise nobody has checked. A **diff** review
  checks the change against the acceptance criteria and the rulebooks — not "does it look fine."
- **A reviewer finding is not an instruction.** The author decides. Rejecting one is ordinary and
  costs a sentence; the thing to avoid is deciding silently, because then nobody can tell a
  considered rejection from a finding that was never read. A fixed finding that was wrong is a
  silent regression, which is the same failure in the other direction.

**Rotating the frame, and knowing when to stop**

Review rounds converge on the frame they are given, not on correctness. Measured on a sibling repo
(`log-forge`, 2026-08-07): **eight** rounds of independent review — two on the spec, three on its
revisions, three on the code — after which the merged result still carried two defects, one of which
was a regression of a guarantee an earlier spec had shipped. Rounds 1–3 found design defects; rounds
4–8 increasingly found wording. The *first* differently-framed pass afterwards found ~25 defects,
several of them years old.

- **Cap same-frame review at two rounds, then switch frame rather than iterate.** For a spec: a
  reviewer briefed only on the *dependencies* it claims, or one asked to build the thing from the
  spec alone and report what it could not determine. For a plan: one asked to find the phase that
  will be discovered impossible. For code: adversarial *execution*, whole-feature fresh eyes, a11y,
  security, or concurrency.
- **The exit rules govern the ceiling, never the floor.** "Never exit on a round count" is about when
  to *stop*; it does not license stopping below the counts in *The reviewer contract*. A diff still
  gets its two frames even when the first one comes back clean.
- **At least one pass must start from the feature, not the diff.** Every diff-scoped review is
  structurally blind to a defect that predates the diff — and to the states the diff is never
  exercised in: SPEC-140's CSP was reviewed and verified *signed in*, and the `connect-src` host it
  omitted broke **fresh sign-in** for a day.
- **A review SAMPLES; when the risk is ABSENCE, enumerate instead.** Review is the right instrument
  for "is this new code correct" and a weak one for "what did we stop checking" — a reviewer reads
  what is there, and a deletion leaves nothing to read. Measured on the 2026-08-28 suite reduction:
  three fresh frames returned **4, then 7, then 17** findings, diverging rather than converging,
  because each sampled a population of hundreds. The mechanical sweep that answered it completely —
  reason codes raised vs reason codes asserted — ran in seconds. **Before reviewing a change whose
  risk is what it removed, write the sweep that lists the whole population.**
- **Spot-check a negative claim before acting on it, and again before writing it down.** "Only
  documented on page X", "no test covers this", "nothing imports this file", "there is no scrubber"
  — each is a claim about an absence, and an absence is what a search proves badly. Verify it
  yourself whether a reviewer said it or you did. The asymmetry that makes this worth a rule: a
  wrong claim entering **code** has tests to catch it later, while one entering a spec, a register
  entry, a docstring or a commit message has nothing, and the next session reads it as settled. Two
  in this repo shipped as source comments and were believed for weeks — a "registry guard" the
  router advertised and did not have, and a credential "scrub" a config module named as the thing
  keeping tokens out of logs. Both were found by writing the test that assumed them.
- **A verification method has a frame, exactly as a review does.** Several sweeps that all ask the
  same question are one check run however many times, however exhaustive each is — proving that moved
  content survived says nothing about content that was newly written. Before trusting a verification,
  ask what question it asks, and whether anything asks a different one. Its stopping rule is the
  sweep's: stop when a fresh question would not change what you conclude.
- **Never carry an evidence sentence from another repo's docs or commit messages — re-measure it
  here, or drop it.** It does not feel like guessing: the sentence was written by someone with that
  repo open, it reads as measured, and it survives being repeated. But a claim about another codebase
  is unverifiable in this one, and a reader who checks it finds nothing. **Anchor both ends of any
  measurement to a commit** a reader can re-derive it from — anchoring only the end leaves "from"
  as whichever commit the writer had in mind. If both ends cannot be cited, state the principle and
  drop the number. `scripts/validate_docs.py`'s budget history is the shape to copy: every figure in
  it is tied to the cut that produced it.
- **A mechanical sweep REPORTS before it applies.** Print what it would change, read the list, then
  re-run with `--apply`, and check the result by diffing **test names** rather than a pass count. A
  classifier that looks right is routinely wrong at its edges: a sweep for unused module-level
  helpers classified pytest's `Test*` classes as dead and would have deleted every test inside
  them — caught only because it printed first. A regex over source is the same hazard one level
  down; parse instead where a parser exists. **Collect the names from the RUNNER, on both refs,
  each in a worktree with its own install** — `vitest list` from `apps/portal` prints one line per
  test without running a body (its `--json` takes an output PATH, and placed before a file filter
  it overwrites that file); pytest's is `--collect-only -q --no-cov` from the repo root, diffing
  the node ids only, since the summary line carries a timing and without `--no-cov` this repo's
  `addopts` appends a coverage table that differs per ref — never from a grep of `it(`. A
  parameterised name exists only at collection time: a registry-driven `it.each` walk turns one
  row into N tests, so removing the row drops N names while the source diff shows one deleted line
  and no `it(` at all. Deleting a gated surface on 2026-09-04 (`1aed93f5`), a source-grep diff said
  six removed where the runner said eight — the two the gating walk generated — and it reached a
  commit message. Check the exit status on both sides: a collection failure on one ref (a spec
  reading `node_modules` by a literal path, in a worktree with no install) empties that side's
  listing entirely, so the diff reads as every test removed — or as no change, if the script
  ignored the exit.
- **A finding should carry a reproducing mutation, and the fix is verified by re-planting it.**
  Then fix-verification is mechanical and needs no second reviewer — which is what stops a review
  round spawning a review of its fixes. A frame only finds what its mutations probe, so a fix that
  satisfies a weak mutation can still be wrong: the same reduction had a `watch_ci` guard restored
  against one frame's probe and broken under the next frame's.
- **A gate is not tested by running it on the thing it guards.** Running a checker over this
  repo's own docs proves the docs pass; it proves nothing about whether any check still fires, and a
  gate whose checks have gone quiet is indistinguishable from a healthy repo. A gate owes a **fixture
  corpus**: one case per construct, asserting the specific **failure text** rather than the exit code,
  because a check that fails for the wrong reason gets "fixed" by changing the wrong thing. Include
  cases that assert **silence** — a corpus of only-failures cannot see a false positive. Prove the
  corpus bites by defeating each check in turn and watching it redden.
  Measured here: `scripts/validate_docs.py` is the gate this repo's doc discipline rests on —
  fifteen checks in `main()`, run unconditionally on every pull request — and until
  `scripts/validate_docs_test.py` it had **no test of any kind**, so nothing showed that any of the
  fifteen still fired. The corpus builds a fixture repository and copies the validator into it, so
  the script's own `ROOT` resolves there and the gate needs no environment override to be testable —
  a budget a caller can redirect is a budget CI can be told to ignore. Each case asserts a specific
  failure message; disabling any one of the fifteen reddens it, and it restores clean.
- **One fixture per guard is not enough when the guard has more than one exit.** A check with two
  terminating conditions is satisfied by a fixture exercising either, so the mutant that breaks the
  other survives with the suite green. Count the ways a check can stop, and write that many cases.
- **Reasoning finds wording; execution finds defects.** Require a reproduction, not an argument — a
  run in the browser or against real AWS. SPEC-137's instrumented code passed review, unit tests and
  `update-function-code`, then raised `ModuleNotFoundError` at every cold start and broke sign-up for
  nine days; every gate was blind because none of them ran the deployed artifact.
- **A spec touching lifecycle, IAM or concurrency gets an execution harness, not a review.** An
  import-time `_require` in a shared layer fails at **cold start** only, and a concurrent-refresh
  race is a property of two overlapping executions — neither is findable by reading.
- **Exit on the trajectory of the findings, not on a round count and not on an empty round.** A fresh
  frame rarely finds literally nothing; it finds something smaller. The honest signal is the **class**
  changing round over round: on SPEC-205, blockers → machinery introduced by the fixes → sequencing
  and contradictions → coin-flips no test would catch. Stop when a new frame's worst finding is one
  that would not change the built result, **and say which finding that was.** "The reviewer found
  nothing" only ever means "nothing within the frame I gave it."
  **This governs the ceiling, never the floor.** It says when to stop *above* the counts in *The
  reviewer contract*, not that a count can be skipped: a diff still gets its two frames when the
  first comes back with nothing that would change the built result.

**When a review changes a rule, re-audit the rule — not the line**

A review finding is usually reported as an instance ("this call site uses the wrong predicate").
Fixing the cited line and moving on is how the same defect survives repeated review: on `log-forge`'s
SPEC-033, three separate reviewers reported the same rule against three *different* call sites, each
was fixed, and a fourth site shipped broken.

- When a finding is an instance of a **rule**, the fix is a test or lint rule that enumerates
  **every** site of that rule and asserts each one — the discipline SPEC-152's fleet test (every
  state machine carries `NotifyFailure`), SPEC-155's `components/`-may-not-import-`features/` ESLint
  rule and `lambdas/test_image_layout.py`'s directory partition already use, and for the same
  reason: a hand-maintained list rots and a derived one does not.
- **Scope added mid-review restarts the clock.** Widening a spec in response to a finding is often
  right, but the widening arrives late, gets the least scrutiny, and inherits confidence it has not
  earned.

**Briefing the reviewer — four lines that change what comes back**

Measured over four rounds on one spec (SPEC-205, 2026-08-18: two adversarial-audit rounds, then two
implementer rounds). The frame decides the *class* of finding; the briefing decides whether the
answer is honest.

- **Say that "this is sound" is a valid verdict.** A reviewer that infers it is expected to produce
  findings will produce them. The round that returned the most useful report was the one told
  explicitly that a short "implementable as written, here is what I built" was a valuable outcome —
  and it still returned real defects, so the line costs nothing.
- **Require it to cite where it looked** before declaring something missing — the spec line it read
  before concluding the spec is silent. That separates a genuine gap from a miss, and it is the
  cheapest way to keep a long report's false-positive rate down.
- **Tell round N+1 what round N fixed, and forbid re-auditing it.** Otherwise the second pass
  re-derives the first pass's findings and never reaches the new work.
- **Withhold the history from a frame that is testing self-sufficiency.** The opposite of the line
  above, and both are right: a pass asking *"is this spec buildable by someone who wasn't here"* must
  be given it cold.

**A rewrite under review pressure is the highest-risk artifact in the loop**

Adjacent to *scope added mid-review restarts the clock*, and stronger. When a finding causes a
substantial **replacement** rather than a widening, the replacement is written quickly, confidently,
and with nobody having reviewed it. On SPEC-205 the second round found **four blockers, all of them
inside machinery the first round's fixes introduced** — two of which independently broke a path the
spec had a requirement to preserve. Budget a round for the fix, aimed at the fix.

And **when the same area is wrong twice, the signal is about the area, not the draft.** Both SPEC-205
drafts were wrong about the same thing — what protects a space from teardown. A repeat in one place
is where to spend the next frame, ahead of anything the reviewer ranked higher.

**The implementer frame must actually build, and every frame must run the gates**

*The build-it-from-the-spec rotation named above, made concrete — it earns its own block because it
yields a different class of finding than any reading-based frame.*

- **Have it write real code, off-repo, and run the suites.** What it found by running that no reader
  found: nine existing tests that invert (a list the spec claimed was four, including one in a
  *different* suite from the one the spec's list implied), fixtures across two validator suites that
  silently become the new failure case, a hard-coded verb count in an unrelated plane's coverage
  test, and a fake whose signature diverges from the real client.
- **Its output class is contradictions, unspecified shapes and sequencing** — two requirements that
  cannot both hold; a return type nobody named; a phase boundary that leaves `main` exposed. An
  adversarial reader finds defects and does not find these; the implementer finds these and is worse
  at defects. Run both, not one twice.
- **Every reviewer runs the repo's gates against the branch.** Four rounds reviewed SPEC-205 and
  none ran `scripts/validate_docs.py`; the branch was red on it throughout, for a reason unrelated to
  the spec, and it took an agent that *built* the change to notice. A review of a change touching
  gated files runs the gates.
