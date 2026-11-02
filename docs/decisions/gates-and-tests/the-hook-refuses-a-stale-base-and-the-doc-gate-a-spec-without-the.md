---
type: Decision
title: "The hook refuses a stale base, and the doc gate a spec without the template's shape (2026-09-08)"
description: "**A rule that prose asks every session to remember is a rule nothing enforces.** The queue told sessions to rebase after the wait for as long as it existed, and the hook checked only the lock; it now refuses a push whose commits do not contain the remote's trunk. When a document says \"always X before pushing\", ask what refuses the push without X — and if the answer is a paragraph, write the check. **A gate's POPULATION is a claim, and an EXEMPTION is a hole shaped like one.** Two wildcard rules read 2 of 17 IAM documents and passed on the 2 they read. Counting the population against the directory it came from catches an ADDITION and nothing else — both sides shrink together on a deletion, so only a comparison against an **independent** source sees that. And an exemption carved for a real case must name the ITEM it excuses, never the container: \"a conditioned wildcard is narrowed\" admitted an account-wide `iam:PassRole` behind `aws:RequestedRegion`, where \"this ACTION is narrowed by this measured key\" costs nothing and admits none. All three were found by planting, not by reading."
---

**What changed.** `scripts/pr-queue/` is the spec-driven template's copy, taken whole: the template
had absorbed this repo's hardening — the origin-scoped exemption, the tag and trunk exemptions, the
fail-closed pattern — and added a FRESHNESS refusal. A push whose commits do not contain the
remote's current `main` is refused with the remedy, because the queue *guarantees* a wait during
which peers merge, and the rebase had lived in prose alone. One policy moved with it: a deletion is
exempt from freshness (there is no commit to measure) but NOT from the lock, since a non-holder
deleting the branch under review closes the PR the lock protects; a deletion of the trunk is refused
outright, as the limit case of a trunk pushed backwards. `validate_docs.py` gained
`check_spec_shape` — the template's four sections, no `Open Questions` or `Checkpoint` heading, and
two WARNINGS the validator now has a channel for: unfilled placeholders, and FRs without acceptance
criteria.

**The exemption, and why it fails closed.** The Completed specs written from the earlier template
carry the retired headings, and a Cancelled spec is a tombstone — sixty closed files at the commit
that introduced the check. Rewriting them to satisfy a rule that governs specs still being built
would be churn with no reader, so the check skips a spec whose `spec_status` is Completed or
Cancelled and judges everything else in full: no status, Draft, In Progress, Superseded, a
misspelling. The hole is shaped like the item it excuses (this decision's fence): two named statuses, not
"anything not being built", and the corpus carries a case for each direction — an exempt spec left
alone, a Superseded and a status-less one judged — so both the exemption vanishing and the
exemption widening redden it.

**What the corpora prove, and the one they caught.** `pre_push_test.py` now builds a real bare
origin whose trunk each case moves — stale, unfetched, rebased, absent, misnamed, decoyed, split
between fetch and push url — and plants each check; the template's `pr-queue-test.sh` drives the
same hook through real `git push` invocations, and `install-test.sh` the installer. All three run
in CI. Planting the unanchored-date mutation reddened nothing, because an `_ok` case looked only for
"problem(s)" and a warning prints "warning(s)": the harness now reads either as broken silence.

When a document says "always X before pushing", ask what refuses the push without X, and if the answer is a paragraph, write the check.

A gate's population is a claim, and an exemption is a hole shaped like one. Two wildcard rules read 2 of 17 IAM documents and passed on the 2 they read. Counting the population against the directory it came from catches an addition and nothing else: both sides shrink together on a deletion, so only a comparison against an independent source sees that. An exemption carved for a real case must name the item it excuses, never the container: "a conditioned wildcard is narrowed" admitted an account-wide `iam:PassRole` behind `aws:RequestedRegion`, where "this action is narrowed by this measured key" costs nothing and admits none. All three were found by planting, not by reading.

## History

### 2026-11-02

- **Changed:** the frontmatter migration moved the exemption onto `spec_status` and retired the `YYYY-MM-DD` placeholder with the *Last Updated* line it read.

### 2026-09-08

- **Settled:** entered the register.
