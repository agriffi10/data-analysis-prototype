---
type: Decision
title: "The queue reads `main`'s build from its push runs, and nothing else that records its sha (2026-09-10)"
description: "`main`'s build is only the runs a push to `main` triggers, filtered by the API's `--event push`; the queue and `watch_ci.py` ignore Dependabot, dispatch and scheduled runs on that sha, so a head with only non-push runs waits for a human override."
---

**What happened.** After a merge, Dependabot's security-update job ran against `main`'s head, and
failed: the update was not possible, because another package pinned the vulnerable version. Every
deploy of that head was green. The queue's `main-green` counted every Actions run on the head sha,
so it answered `main IS RED` to every session — and the only thing that moves the head is a merge,
which the queue refuses while `main` is red. No re-run could succeed while the conflict stood. The
next PR had to be pushed past the hook with `--no-verify` to break it.

**The rule.** `main`'s build is the runs a push to `main` triggers. A Dependabot job (event
`dynamic`), a manual `workflow_dispatch` and a scheduled scan record the same sha and are not it.
The filter is the API's `--event push`, not the `--jq`: filtered client-side, `--limit 30` counts
the Dependabot jobs too, and a burst of them after a merge pushes the head's own runs out of the
window, which reads as "not built yet" for ever. A head with only non-push runs still waits — even
a manual dispatch that recovers a push event GitHub dropped, which is the rule's cost: that head
waits until a human installs a temporary `main-green` override (`PROTOCOL.md` says how).

**The watcher follows the same rule (2026-09-13).** `watch_ci.py` counted every run on the sha, so
a lock holder confirming `main` after a merge read the same failed Dependabot job as RED. It now
asks GitHub's compare endpoint whether the commit is on `main` — for `--branch main`, `--sha` and
local HEAD alike, since a local `origin/main` can be stale — and judges a commit on `main` by its
push runs only, the filter again the API's. `--pr` keeps every run on the head: Dependabot and the
scheduler run on the default branch alone, so filtering a pull request would only drop a dispatch
someone ran against its branch. A comparison that fails, or answers in neither allowlist, is no
verdict. `test_watch_ci.py` drives `main` through a fake GitHub that filters before it pages and
runs the real `--jq`, and plants each check that decides which runs count into a copy of the
script. The `gh run list` reads of `main` that the session start and the live checks instruct
gained `--event push` for the same reason.

**What generalises.** A gate that blocks until X is a deadlock when X can only be reached through
the gate, so a verdict the gate itself makes permanent has to be ruled out, not waited out. And a
check keyed on a commit sha inherits every bot that records a run against that sha — the
population (the [hook entry's](the-hook-refuses-a-stale-base-and-the-doc-gate-a-spec-without-the.md) fence) is defined by the trigger, never by the sha. `pre_push_test.py`
carries the incident as a case beside one where a failed push run still reads RED, drives the
check through a fake `gh` that runs the queue's real `--jq`, and plants each of its checks.

## History

### 2026-09-13

- **Changed:** `watch_ci.py` adopted the same push-runs rule for any commit on `main`, which it establishes through GitHub's compare endpoint.

### 2026-09-10

- **Settled:** entered the register.
