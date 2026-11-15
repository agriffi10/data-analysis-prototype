---
type: Decision
title: "A change-detection gate answers three ways, and one of them is not an answer (2026-09-04)"
description: "**Every way a change-detection gate goes wrong answers \"nothing changed\", the cheap direction, behind a green check.** Read paths RAW with `-z`, because `git diff --name-only` C-quotes a path out of every anchored pattern; prove the pattern list with a POSITIVE CONTROL, a path it must always select, because `grep` answers three ways and some broken lists exit an ordinary 1; hold `pipefail`, because a pipeline's status is `tr`'s; and print the change set a skip decided over. **A script a test EXECUTES must keep its scratch files private.** A workflow step naming a fixed path under `/tmp` is one file per *job* on a runner, and one file per *machine* under the suite — which runs those scripts verbatim, on a checkout several sessions work at once. Two runs truncate and rewrite it: the loud half is a `jq` parse error on spliced bytes, the quiet half is a clean read of the OTHER run's fixture, which answered a wrong verdict with no error and passed as a flake on a different test each time. Create the file with `mktemp`; `$RUNNER_TEMP` is for one that must cross steps. **No silent caps.** If a check bounds coverage, say what was dropped — silent truncation reads as \"covered everything\"."
---

Two workflows skip expensive steps when a change set touches nothing they read: `ci.yml`'s scope
step, which gates the install, the build and the checks on its output on a pull request, and
`deploy-spa-image.yml`'s, which gates the image build. Both decide by matching `git`'s path list
against an anchored pattern list. Every way that decision can go wrong answers "nothing changed"
— the **cheap** direction, behind a green check, with the same reassuring annotation an honest
skip prints. `ci.yml` had two such ways and has been fixed; `deploy-spa-image.yml` was written
with both guards already in it and never had either, so this entry is about the class rather than
about a defect the two shared.

**Read paths RAW.** `git diff --name-only` (and `ls-files`, and `ls-tree --name-only`) C-quotes any
path that is not plain ASCII: `apps/portal/src/café.tsx` comes back as
`"apps/portal/src/caf\303\251.tsx"`, wrapped in double quotes with the bytes escaped, which matches
`^apps/portal/` and every other anchored pattern. **`core.quotePath=false` is not the fix** — it
covers bytes >= 0x80 alone and leaves `"`, `\` and control characters still quoted, so it closes one
member of the class. `-z` plus `tr '\0' '\n'` closes the class. The residual is a newline inside a
filename, which splits one path into two: for a prefix anchor both halves are tested and it
over-selects, in the expensive direction; for a `$`-anchored pattern with a wildcard segment —
`^infra/modules/[^/]+/policies/[^/]+\.json\.tftpl$` is the only one — neither half matches and the
path is lost in the cheap one. Measured and accepted: closing it means abandoning line-oriented
matching for a filename nobody writes. The same defect was found and fixed in two IAM guards
reading `ls-files` and `ls-tree`, where it dropped a template out of a guarded population.

**Guard a broken pattern list with a POSITIVE CONTROL, not an enumeration of failure modes.**
This was learned by getting it wrong. `grep` answers three ways and only two are answers — 0
matched, 1 did not, anything above is grep failing to perform the test at all — so a bare `if`
collapses the third into the second and an unusable list reads as "nothing changed". It is
**self-concealing** in `ci.yml`, because the workflow is in its own pattern list: the pull request
that breaks it skips its own build, merges green, and every later one skips too.

Reading the status and hard-erroring above 1 was the first fix, and it covers **one** shape.
Measured on GNU grep 3.11, the runner's engine: an unbalanced bracket exits 2, but a non-capturing
group, a lookaround and a stray `\d` all exit **1** — an ordinary "no match" — and two of the three
are not diagnosed at all. An empty list is a fourth. So the step now runs a path the list must
always select through the same invocation and refuses anything but a match. That covers empty,
uncompilable, silently reinterpreted, and edited-until-it-no-longer-selects-the-app, including
shapes nobody has enumerated. The status check stays as the narrower diagnostic — with the canary
matched, a failure above 1 is grep failing on the *change set*, which wants a different message.

Do **not** reach for the static sanity tests instead: they run only in a session's local pytest.
And note which way that asymmetry runs, because the intuitive version of it is backwards — Python's
`re` **rejects** the unbalanced bracket the step now catches on its own, and **accepts** the `(?:`
and `(?=` it does not.

**The step's own claim to fail expensively is now load-bearing on `pipefail`.** As a simple
assignment, a failing `git diff` killed the job under `set -e` alone. As a pipeline, the status is
`tr`'s, and `tr` succeeds over nothing — so without `pipefail` every pull request answers
`app=false`, silently. Asserted both ways: the flag is read out of the step, and a diff that cannot
be computed is exercised.

**A skip prints the change set it decided over.** A verdict with no evidence under it makes a wrong
`app=false` undiagnosable from the log — the notice alone cannot distinguish an honest skip from a
pattern list that has stopped covering an input.

**What the guards over this owe, beyond the verdicts.** `lambdas/test_ci_scope.py` runs both steps'
real scripts, taken from the workflow rather than restated, against throwaway repositories. Two
controls make the rest worth anything. On the **answer** side: a harness that answered `app=true`
unconditionally would satisfy every quoted-path case while proving nothing, and the step takes
exactly that branch by design when the base is unreachable — so a documentation-only commit must
still skip and neither verdict may reach that escape. On the **input** side: for any fixture path
that is not plain ASCII, the un-`-z`'d diff must still be shown to quote it, or the fixture has
stopped provoking the hazard and the guard over it is vacuous. That one is reachable without a code
edit — a developer with `core.quotePath=false` in their own git config — which is why the harnesses
scrub git's configuration out of the environment. Pointing `GIT_CONFIG_GLOBAL` and
`GIT_CONFIG_SYSTEM` at `/dev/null` is **not** sufficient on its own: `GIT_CONFIG_COUNT` with its
numbered key/value pairs, and `GIT_CONFIG_PARAMETERS`, set the same option with no file involved,
so all of them go. `GIT_DIR` goes with them for a different and worse reason — inheriting it does
not merely break hermeticity, the fixture commits land in **that** repository. Measured before the scrub: a decoy
repo came back with its `HEAD` moved onto a fixture commit and its original orphaned, while the
suite passed green.

`TMPDIR` joins that list, and it is the costliest entry on it. These scripts do not only read the
environment, they CREATE files — and a name fixed in the script is one file shared by every run of
the suite on the machine, which several sessions of this project run at once as their pre-push
gate. Two runs truncate and rewrite it. The loud half is a `jq` parse error on spliced bytes; the
quiet half is a clean read of the other run's fixture, which took the no-baseline branch and
answered *build and deploy* — a wrong verdict, reached with no error, by the step whose only job is
that decision. Reproduced in three concurrent runs of the file; it had been failing about one full
suite in six, on a different test name each time. The loud half has NO fixed signature, which is
the trap for anyone tempted to assert on it: whichever run writes second owns the front of the
file, so a longer write over a shorter one leaves a head (`Invalid numeric literal at line 2,
column 12`) and a shorter over a longer leaves a tail (`Unmatched ']' at line 2, column 1`). Both
were observed, on two machines. A guard here asserts that the step FAILED, never what it said. So the workflow creates its scratch files with
`mktemp`, the harnesses point `TMPDIR` at the throwaway directory they already clean up, a sweep
refuses a fixed path under a shared temp root in everything the suite executes, and a concurrency
case asserts what the sweep cannot spell — two fixtures whose verdicts contradict, so a collision
cannot be absorbed as a coincidence. Left deliberately: `spa-image-matrix.sh` keeps a dozen fixed
`/tmp/matrix-*` names, which are the same defect on the HOST and would corrupt two concurrent runs
of it. No test executes that script, so it cannot flake this gate; fixing it is its own change.

A workflow step naming a fixed path under `/tmp` is one file per job on a runner and one file per machine under the suite. Create a scratch file with `mktemp`; `$RUNNER_TEMP` is for one that must cross steps.

No silent caps. If a check bounds coverage, say what was dropped: silent truncation reads as "covered everything".

## History

### 2026-09-04

- **Settled:** entered the register.
