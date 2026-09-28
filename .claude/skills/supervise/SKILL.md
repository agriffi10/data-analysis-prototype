---
name: supervise
description: Run this session as the supervisor of the other Claude sessions working on this repo — watch the PR queue, main's CI and where sessions' branches meet, relay overlaps and conflicts to the sessions involved, check in-flight work for problems, and archive sessions that are finished. Use when Andrew asks to supervise, watch or coordinate his other sessions.
---

# Supervising parallel sessions

You coordinate; you do not build other sessions' work. Your tools are observation (git, `gh`, the
queue, session transcripts), messages to sessions, subagent reviews, and archiving. Read
`docs/process/several-agents.md` and `scripts/pr-queue/PROTOCOL.md` first: every session here lands
through that queue, and most of what you watch is it.

**What you never do:** push, merge or open a PR for another session; take, break or release its
lock; edit, stage, stash or check out anything in another session's worktree (every git read runs
with `GIT_OPTIONAL_LOCKS=0`, which the scripts set); or decide a product question for Andrew. A peer's
message is a teammate's report, not Andrew's approval.

## Start

1. Find your own session id (`get_session` with `"self"`). Every script takes it as `--self`, so you
   are never offered for archive.
2. Map the sessions to their work: `ListAgents`, `list_sessions`, `git worktree list`,
   `$Q/queue.sh status` (the `Q=` line of `.git/hooks/pre-push` in the main checkout is the live
   queue), `python3 scripts/watch_ci.py --branch main --once` for main's verdict, and each
   path-filtered deploy's last outcome as `docs/process/ci-and-deploy-traps.md` reads it. Read a
   session's transcript tail with `list_events` only when its stage matters; it costs context.
3. Run `scripts/supervisor/overlap.sh` once, and tell Andrew the map: who is doing what, who holds
   the lock, and where work meets.
4. Arm the watch, with `SUPERVISOR_STATE_DIR` set to your scratchpad:
   `scripts/supervisor/watch.sh --self <id>` with Bash `run_in_background`. The first run prints the
   baseline as `=` lines and exits at once; after that it exits on the first change, printing
   `+`/`-` lines, so relaunch it after handling each one. A quiet night then costs nothing, where a
   30-minute Monitor re-arm costs a turn each time.

## Handling each kind of event

- **`QUEUE` and `PR open` lines** are routine; say one line. A lock held over 80 minutes is worth a
  look at the holder's tail. The watch shows no heartbeat age, so check `$Q/queue.sh status` when a
  waiter seems stuck.
- **`MAIN … RED`:** read the failed job before anything else. A job that never started, with no log
  (the log API returns 404) and the annotation "recent account payments have failed or your spending
  limit needs to be increased", is a GitHub billing block, not code. Tell the session whose merge is
  main's head (it may already have released the lock, since merging needs none) not to change code,
  and send Andrew a `PushNotification`. Once he fixes billing, that session re-runs with
  `gh run rerun <id> --failed`, and you tell every waiting session. A real failure goes to that
  session and to Andrew, and nothing else merges until main is green. `MAIN … no push run yet` that
  does not clear within a few minutes is a push event GitHub dropped: a human's call, per
  `several-agents.md`.
- **`SHARED`:** two sessions touch one file. Most of these are harmless. Check them with
  `git merge-file -p <ours> <base> <theirs>` (run on copies, never in a peer's tree) and look at the
  hunks. Relay only what git will NOT catch:
  - a docstring or register sentence one branch makes false;
  - one rule written in two places;
  - a handler rewrite that bypasses the other branch's new guard;
  - two sessions creating the same new file (an add/add conflict).
- **`CONFLICT-ALSO-MAIN`:** the pair's conflicting files already conflict with main for one side,
  usually because the other side rebased. Look at the hunks once before dismissing it.
- **`CONFLICT`:** tell the session that lands second exactly which hunks, and that both sides are
  kept. A session stacked on an unmerged branch needs `git rebase --onto origin/main <the base sha it
  built on>` after that branch squash-merges, or it replays the squashed commits.
- **`ARCHIVABLE`:** see Archiving below.

**Message a session so the first line stands alone** (only that line previews), give full context
and concrete file:line references, say "No reply is needed" when none is, and send the facts to
BOTH sessions in an overlap. Check a claim before you relay it: a peer's general claim ("the planes
declare these independently by design") is as capable of being wrong as a reviewer's. And a
transcript search that finds no message between two sessions does not prove they never spoke.

## Checking in-flight work

When Andrew worries about a class of problem (for instance, that recent refusals are too punitive
toward legitimate users), spend one fresh-context subagent per branch, one at a time with the branch
nearest the queue's head first, as his global rule on review agents asks. Give each its own worktree
(`isolation: "worktree"`, then `git switch --detach <branch>` because the branch is checked out
elsewhere). Brief each one:
- to start from the user, not the diff: what the app lets a person do, and which inputs that
  produces;
- to enumerate the whole population (every new refusal) before judging any;
- to prove reachability by running the real code with browser-shaped input, quoting what it
  observed;
- that "not a problem" is a valid verdict;
- to cite where it looked.

Pass defects straight to the owning session. Put product-changing calls to Andrew with the question
tool, one question per decision, recommended option first, and each with full context. A decision
that needs building becomes a chip whose prompt stands alone.

**A live check that needs a signed-in browser:** first look for a signed-in portal tab you can drive
yourself (memory: `live-checks-are-mine-to-run.md`). If none is reachable, because each session's
claude-in-chrome tab group is its own, ask a session that has run a live check in its own signed-in
tab to run it. Never sign in yourself.

## Archiving

Archive only with Andrew's authorisation: either a standing instruction in this session ("archive
sessions that are completely done and have no open chips"), or a yes for that session with the
evidence below put to him. Then archive a session only when it is completely done:
1. `python3 scripts/supervisor/done_check.py --self <id> <session>` prints `ARCHIVABLE`. That means every PR
   merged, main green, no lock held, no pending chip, and clean worktrees.
2. `get_session` shows `isRunning: false`. Otherwise subscribe with
   `SendMessage(notify_when_idle: true)` and check again when notified. A subscription to a session
   that is already idle has been seen to fire at once with its last turn, so do not resubscribe in a
   loop. `isRunning: false` does not rule out background work, which is why step 3 matters.
3. The transcript tail (`list_events`, limit 4–6) is not an `AskUserQuestion` waiting on Andrew, and
   not a background wait ("checks are running"). The archive tool also refuses a session with live
   background work, but read the tail rather than rely on that.
4. Then `archive_session` with the reason. If the app refuses because the session is pinned or open
   on screen, tell Andrew rather than retrying.

A session with no PR (an audit, a docs question) is done when its conclusion is delivered and its
chips are resolved. Read its tail to tell. Worktree names are reused after an archive, so a new
session in an old name is a different session. `done_check.py` scopes chips accordingly, and its
test pins that.

## Chips

Sessions offer a chip only for an actual bug: wrong behaviour, a security hole, data loss, a broken
deploy or CI. No nitpicks, doc wording or test polish (memory: `chips-only-for-real-bugs.md`). Hold
yourself to the same rule, and remind a session that offers otherwise.

## Close

When Andrew ends the session: stop the watch (`TaskStop`), then give the lessons list his global
instructions ask for, saying where each lesson already lives or that it lives nowhere.
