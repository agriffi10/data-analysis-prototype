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

**A supervisor session** watches the queue, main and where sessions' work meets, relays what git
will not catch, and archives finished sessions — `/supervise` (`.claude/skills/supervise/SKILL.md`),
driven by `scripts/supervisor/`.

**Running an arc through — one build session per spec**

A session told to build an arc **orchestrates** it and builds none of the specs itself: it starts a
new build session per spec, and the instruction to build the arc is the instruction to build each of
its specs (`spec-lifecycle.md`), so it does not ask again between them. An arc run is a multi-agent
run from its first session. Confirm the live queue is installed (the `Q=` line of
`.git/hooks/pre-push` in the main checkout, above) and never re-install it bare; then brief every
session from `docs/templates/multi-agent-briefing.md`, queue section included.

- **Start every ready spec, without asking — at the outset and again each time a spec lands.** A spec
  is ready when it is `Draft` on `origin/main` (the status a spec takes once reviewed,
  `spec-lifecycle.md`), `python3 scripts/validate_docs.py` run on that tree reports no failure naming
  it, and every earlier spec in `arc_order` that it is not independent of has landed. With no independent specs this is one session at a time, in
  `arc_order`. Start every ready spec before stopping to ask about one that is not.
- **Two specs are independent** when neither needs the other's result, whether through `depends_on`
  or through something the earlier one builds, and they touch different source files. The files every
  completion ritual edits (the generated indexes, `CLAUDE.md`'s `## Specs`, the component inventory)
  do not count; name them in each briefing's *Files you and a peer will both touch*. Arcs can carry
  dependencies the frontmatter does not name, so when independence is not clear, chain them.
- **Landed is checked, never taken from a report.** After `git fetch origin`: the spec reads
  `Completed` on `origin/main` (`git show origin/main:<spec path>`), every PR its session named is
  merged, `main` is green at a head that contains them, and the spec holds neither the queue lock nor
  a ticket. A spec already `Completed`, `Cancelled` or `Superseded` when the orchestrator starts counts
  as landed (for a Superseded one, its successor is what gets built). A turn-end note that reports
  progress (a plan drafted, a review running) is not a finish, so nothing starts on one.
- **Check for a landing whenever a session it started ends a turn.** Where the harness does not
  report that, poll `origin/main` for the spec's status rather than end the orchestrator's own turn:
  an orchestrator that goes quiet with sessions running is the stall this rule exists to prevent.
- **Archive each finished session in the step that verifies its landing,** wherever the harness can
  archive sessions. That covers every session the orchestrator started, a fix or a review session as
  much as a build. This is the orchestrator's own authority, from Andrew asking for the arc, not the
  supervisor's; it borrows only the supervise skill's *Archiving* checklist to tell finished
  (`.claude/skills/supervise/SKILL.md`): `done_check.py` prints `ARCHIVABLE`, or for a session with
  no PR its tail shows its conclusion delivered and its chips resolved; the session is not running;
  and its transcript tail is neither a question waiting on Andrew nor a background wait. A session the
  checklist says to keep after its spec has landed (a pending chip, a dirty worktree) is left
  unarchived and named in the arc report; it does not hold up the next spec.
- **Stop the chain and ask Andrew** when:
  - a session ends blocked, or ends with its spec not landed by the check above;
  - a session is waiting on Andrew's answer: relay its question verbatim;
  - `main` is red: start nothing until it is green again, and ask before the chain resumes. The
    session whose merge turned it red fixes it (`CLAUDE.md`); start a fix session only if that one
    has ended;
  - the next spec is `In Progress` from a session this orchestrator did not start (name its branch,
    its PR and any queue lock it holds), is none of `Draft`, `Completed`, `Cancelled` or `Superseded`, fails `validate_docs.py`, or
    depends on a spec outside the arc that is not `Completed`.
- **When the arc's last spec lands,** archive its session and report the arc done to Andrew,
  with the lessons its sessions reported.

## Every agent runs on the model that started the task

Every subagent, and every session started to do part of a task, runs on the model of the session
that started the task. Until this repo has `.claude/agents/` roles, a subagent here is a built-in
one, and each way off the parent's model is fenced:

- **Delegate only to an agent type that takes the parent's model — `general-purpose`, `claude`,
  `Plan` or a fork.** `claude-code-guide` and `statusline-setup` run on fixed models, Haiku and
  Sonnet, and `Explore` under a Fable session runs on Opus on subscription and Console accounts; a
  type named nowhere here is used only once its model is confirmed to be the parent's. A sweep or a
  delivery-doc read goes to `general-purpose`. A personal agent in `~/.claude/agents/` that shares a built-in's name replaces
  it and keeps its own `model`, so yours may take one only if it declares `model: inherit`.
- **Pass no `model` on an Agent tool call**, and install no mod whose `agent.spawn` hook sets one.
  Either overrides an agent file's `model`, `inherit` included.
- **Never set `CLAUDE_CODE_SUBAGENT_MODEL` or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`**, in settings or
  in the environment. The first puts `general-purpose` on the model it names; with both set, every
  subagent runs there and the `model` of an agent file and of a call are both ignored.
- **A role added under any `.claude/agents/` declares `model: inherit`, and a skill declares
  `inherit` or no model.** An omitted `model` on a role falls back to `CLAUDE_CODE_SUBAGENT_MODEL`
  when someone's shell sets it; a skill's named model runs the skill on it.
- **A reviewer or peer started as a new session, not a subagent, is started on the model of the
  session that asked for it**, never a cheaper one. Nothing inherits across sessions: the model is
  chosen when the session starts.
- `validate_docs.py` fails a `.claude/settings.json` whose `env` names either variable, a file under
  any `.claude/agents/` in the tree, at any depth, whose frontmatter `model` is anything but
  `inherit`, and a `SKILL.md` naming another model or one it cannot read. It does not follow a
  symlink, and it reads no settings file but that one: the environment, `settings.local.json` and
  `~/.claude/`, the Agent call, a mod, and a new session's model are held by this page alone.
