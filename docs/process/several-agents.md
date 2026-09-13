# Several agents on one repo


The default is one spec in flight (`spec-lifecycle.md`). When several sessions run against this
repo at once — they routinely do here — each in its own worktree, their *trees* never collide but
the **remote still does**: two PRs open at once means each is tested against a `main` the other is
about to move, and a merge race turns a green PR red for a reason neither session caused.
Serialising the remote while parallelising the work is the whole idea, and the invariant is **one
PR open at a time, taken in the order agents asked, with `main` settled and green before the next**.

- **The queue lives outside every worktree and outside the repo.** A lock inside a worktree is
  invisible to peers; a lock inside the repo is a file that itself conflicts. `scripts/pr-queue/`
  holds the implementation; `install.sh` copies it to a shared directory under `$HOME` and points a
  `pre-push` wrapper in the checkout's hooks at it. **Do not hand-roll the shell** — these checks
  are easy to get subtly wrong in a way that fails *open*, which is the one failure mode that
  matters.
- **The live queue here is NOT at the installer's default path, and a bare `install.sh` builds a
  second one.** The installer derives its default from the origin slug, which is
  `data-analysis-prototype`; the queue every session on this checkout actually uses lives under
  `~/.claude/projects/` at a path derived from the checkout's *directory* name. The one authority
  for where it is: the `Q=` line of `.git/hooks/pre-push` in the main checkout, which the
  installer's wrapper writes. Run bare, `install.sh` stands up an empty queue at the slug path that
  neither side can see and repoints that shared hook at it — every linked worktree pushes through
  the same hook. Re-install only while the queue is idle, and only as
  `PR_QUEUE_DIR=<the live queue> sh scripts/pr-queue/install.sh '.'` — the directory named AND the
  pattern passed, because an existing pattern is kept rather than updated and the installer's
  summary says which of the two happened. It refuses outright while a lock is held.
- **Four commands, and the polling one is `turn`:** `ticket` gets in line, `turn` exits 0 when it is
  your turn *and* the remote is clear, `acquire` takes the lock, `release` drops it — on **every**
  exit path, including failure. Poll `turn`, never `acquire`; each `turn` call is also the heartbeat
  that keeps your place. A holder that stops is this design's one real failure.
- **The lock covers the whole PR lifecycle** — fetch, rebase, re-run your gates, push, open, watch
  to green with `scripts/watch_ci.py --pr <n>`, merge, confirm `main` with `--branch main` — not
  just the push. The fetch is inside the lock because the wait is when peers merge. One ticket per
  PR, released between them, so a multi-PR spec does not hold the line for its whole duration. If
  that confirmation says the push triggered nothing, GitHub dropped the push event and `main` was
  never deployed: a human's call, not a wait — a manual dispatch recovers the deploy, but neither
  the watcher nor `turn` counts it, and `PROTOCOL.md` says how the line moves on.
- **The queue is not a review.** It is the last thing between an already-reviewed branch and the
  remote. The local gates and both diff reviews still come first, in that order.
- **Every remote check fails closed; enforcement fails open on CONSENT and closed on EVIDENCE.**
  The lock only orders the agents that take it, so `turn` asks the remote directly too — and a `gh`
  that *errors* returns empty output, which reads as "no PRs open" unless you check the exit status.
  Consent is the opposite case: linked worktrees share `.git/hooks` through the common git dir, so
  the hook fires for sessions that never agreed to the queue, and blocking those would be worse than
  the problem it solves — a branch outside the pattern pushes freely. But for a branch the hook does
  police, a remote it could not read is never read as "your base is current". **`turn` and
  `watch_ci.py` judge `main` by the runs its own pushes trigger** — a Dependabot job, a manual
  dispatch or a scheduled scan records the same head sha, and counting a failed one once deadlocked
  the queue, because only a merge moves the head.
- **The hook checks your base, not just your lock.** It refuses a push whose commits do not contain
  the remote's current `main`, because the queue *guarantees* a wait during which peers merge. Prose
  told sessions to rebase for a long time and nothing checked. It also refuses a non-holder deleting
  a participating branch — that closes the PR the lock protects — and a deletion of the trunk
  outright. Two corpora keep the hook honest and both run before a push that touches it:
  `scripts/pr-queue/pre_push_test.py`, which CI runs, and `scripts/pr-queue-test.sh`, which drives
  real pushes on this machine; `scripts/pr-queue/install-test.sh` is the installer's.
- **Brief each session explicitly** from `docs/templates/multi-agent-briefing.md`: its own worktree
  off freshly fetched `origin/main`, who else is running and on what, the files two agents will both
  edit, and that a rebase conflict is never resolved by discarding a peer's work. An unbriefed
  session does the reasonable thing for a session working alone, which is exactly what breaks a
  parallel run.

Full protocol, configuration and the stale-entry rules: `scripts/pr-queue/PROTOCOL.md`.
