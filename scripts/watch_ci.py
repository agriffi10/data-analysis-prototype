"""Watch this repo's workflow runs for ONE commit, and exit on what they actually say.

Written because hand-rolled watch loops have twice reported a green that was not there:
``gh pr checks --watch`` can exit clean against the PREVIOUS commit's checks, and a
hand-written shell condition (``! grep -qv completed``) inverted and printed "settled"
while two deploys were still running. Both failures share a shape — the thing that
decides "done" is written fresh each time and is never itself tested.

So the two guards here are structural rather than careful:

**Every query is keyed to an explicit commit sha, which is resolved once and printed.**
``actions/runs?head_sha=`` cannot answer about a different commit, so "reported against a
stale sha" is not a state this can reach. If the ref moves while watching, that is detected
and reported rather than silently followed.

**``is_settled`` and ``verdict`` are pure functions over a list of runs, and they are
unit-tested** — including against the exact inversion that caused the second failure. A
condition that lives in a tested function is a condition that stays correct.

**A commit on the trunk is judged by the runs a push triggered, and nothing else that records
its sha.** Dependabot's own jobs, a manual dispatch and a scheduled scan all record the trunk's
head too, and a Dependabot job that failed beside four green deploys read as a red trunk. So
``--branch main``, and a ``--sha`` or local HEAD that GitHub's comparison places on the trunk,
count push runs only; ``--pr`` keeps every run on the head, because Dependabot and the scheduler
run on the default branch alone, and filtering a pull request would only lose a dispatch someone
ran against its branch.

Usage::

    python3 scripts/watch_ci.py                 # local HEAD
    python3 scripts/watch_ci.py --pr 538        # a pull request's head
    python3 scripts/watch_ci.py --branch main   # a remote branch's tip
    python3 scripts/watch_ci.py --once          # one poll, no waiting

Exit status is 0 only when every run that counts for that sha has finished AND none of them
failed, so it composes: ``python3 scripts/watch_ci.py --pr 538 && gh pr merge 538 --squash``.

Attributes:
  GOOD_CONCLUSIONS: Conclusions that are not a failure. These are WORKFLOW-RUN conclusions,
    not job ones — a run whose ``apply`` job skips still concludes ``success``, so the job
    level is the wrong place to reason from. A run concludes ``skipped`` when every job in it
    does, which a path filter or an ``if:`` on the whole workflow produces, and calling that
    red would fail a commit for work that correctly did not run.
  FINISHED_STATUSES: The statuses that mean the answer is in — an ALLOWLIST, which is what
    makes an unrecognised status keep waiting instead of being declared a result. Written
    as the unfinished set first, and a test caught that: GitHub adds statuses, and a
    denylist silently calls each new one "done".
  DEFAULT_INTERVAL: Seconds between polls.
  DEFAULT_TIMEOUT: Seconds before giving up. Longer than this repo's slowest workflow by a
    wide margin; giving up is reported as a timeout and a non-zero exit, never as a pass.
  GH: The resolved ``gh`` executable, or None when it is not installed. Absolute because
    ruff's bandit rules refuse a partial executable path, and so the lookup happens once —
    NOT as shadow resistance, since ``shutil.which`` resolves through PATH and would return
    the shadowing binary like any other caller.
  GIT: The resolved ``git`` executable, for reading local HEAD.
  STARTUP_GRACE: How long a sha may have NO runs at all before that is called an answer.
    Zero runs is the shape a stale-sha report takes when the sha is real but nothing was
    triggered for it, so it is never treated as success — the wait covers the gap between
    a push and the first run appearing.
  TRUNK: The branch whose commits are built by a push.
  TRUNK_EVENT: The event whose runs are a trunk commit's build.
  ON_TRUNK: The comparison statuses that place a commit on the trunk — its tip, or behind it.
  OFF_TRUNK: The statuses that place a commit off it. Both sets are allowlists, so a status
    GitHub adds is no verdict rather than a guess at which runs count.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from typing import Any

GH = shutil.which("gh")
GIT = shutil.which("git") or "/usr/bin/git"

GOOD_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
FINISHED_STATUSES = frozenset({"completed"})
DEFAULT_INTERVAL = 20
DEFAULT_TIMEOUT = 2400
STARTUP_GRACE = 120
TRUNK = "main"
TRUNK_EVENT = "push"
ON_TRUNK = frozenset({"identical", "behind"})
OFF_TRUNK = frozenset({"ahead", "diverged"})


class WatchError(Exception):
    """The watch could not be carried out, as distinct from CI having failed."""


def _gh(*args: str) -> str:
    """Run a ``gh`` command and return its stdout.

    Args:
      *args: The arguments to pass to ``gh``.

    Returns:
      The command's stdout, stripped.

    Raises:
      WatchError: If ``gh`` is not on PATH, or exits non-zero.
    """
    if GH is None:
        raise WatchError("gh is not on PATH — this helper drives the GitHub CLI")
    done = subprocess.run(  # noqa: S603
        [GH, *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise WatchError(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def is_settled(runs: list[dict[str, Any]]) -> bool:
    """Report whether every run has finished.

    An empty list is NOT settled. Zero runs for a sha means either that nothing has been
    triggered yet or that nothing ever will be, and both are questions rather than answers —
    reporting "settled, nothing failed" for an empty list is how a watch reports a green
    that does not exist.

    A status this does not recognise is treated as unfinished, so the set is an allowlist of
    what counts as done rather than a list of what counts as running.

    Args:
      runs: Workflow-run records, each carrying at least ``status``.

    Returns:
      True when the list is non-empty and no run is still going.

    Raises:
      None.
    """
    if not runs:
        return False
    return all(run.get("status") in FINISHED_STATUSES for run in runs)


def verdict(runs: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Judge settled runs, and name the ones that are not good.

    Only ever called on a settled list. A finished run whose conclusion is unrecognised —
    including ``None`` — counts against, because an unknown outcome is not a pass.

    Args:
      runs: Workflow-run records, each carrying at least ``name`` and ``conclusion``.

    Returns:
      A pair of (everything passed, the names-with-conclusions that did not).

    Raises:
      None.
    """
    bad = [
        f"{run.get('name', '?')} ({run.get('conclusion') or 'no conclusion'})"
        for run in runs
        if run.get("conclusion") not in GOOD_CONCLUSIONS
    ]
    return not bad, bad


def resolve_sha(pr: int | None, branch: str | None) -> str:
    """Resolve exactly one commit sha to watch, from at most one selector.

    Args:
      pr: A pull-request number, whose head commit is watched.
      branch: A branch name, whose remote tip is watched.

    Returns:
      The full 40-character commit sha.

    Raises:
      WatchError: If both selectors are given, or the sha cannot be resolved.
    """
    if pr is not None and branch is not None:
        raise WatchError("--pr and --branch name different commits; pass one")
    if pr is not None:
        return _gh("pr", "view", str(pr), "--json", "headRefOid", "--jq", ".headRefOid")
    if branch is not None:
        return _gh("api", f"repos/{{owner}}/{{repo}}/commits/{branch}", "--jq", ".sha")
    head = subprocess.run(  # noqa: S603
        [GIT, "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    if head.returncode != 0:
        raise WatchError("could not resolve local HEAD")
    return head.stdout.strip()


def build_event(sha: str, pr: int | None) -> str | None:
    """Choose which runs are one commit's build: its push runs on the trunk, every run elsewhere.

    A pull request is judged by every run on its head without asking where the head sits, so a
    PR watch neither depends on the comparison nor changes population if its head reaches the
    trunk. Anything else asks GitHub, because a local ``origin/main`` can be stale enough to
    call a merged commit off the trunk, and a status outside both allowlists raises rather than
    guessing — either guess can turn a failure into a green.

    Args:
      sha: The commit being watched.
      pr: The pull-request selector this watch was started from, if any.

    Returns:
      ``TRUNK_EVENT`` when the commit is on the trunk, otherwise None, meaning every run.

    Raises:
      WatchError: If the comparison fails, or answers with a status in neither allowlist.
    """
    if pr is not None:
        return None
    status = _gh("api", f"repos/{{owner}}/{{repo}}/compare/{TRUNK}...{sha}", "--jq", ".status")
    if status in ON_TRUNK:
        return TRUNK_EVENT
    if status in OFF_TRUNK:
        return None
    raise WatchError(f"could not tell whether {sha} is on {TRUNK}: the comparison said {status!r}")


def fetch_runs(sha: str, event: str | None = None) -> list[dict[str, Any]]:
    """Fetch the workflow runs GitHub associates with one commit, from one event or all.

    The endpoint takes the sha as a filter, which is what makes a stale-sha report
    impossible here rather than merely unlikely.

    One page is read, and ``total_count`` is checked against what came back rather than
    discarded — a watch that silently judged the first hundred of more would report a green
    for a subset, which is this file's own failure mode wearing a different hat. That is why
    the event is the API's filter and not the ``--jq``'s: filtered after the page, the total
    still counts every Dependabot job on the sha, so the check would refuse any page with one
    beside the push runs — and a check loosened to allow that would pass a page that a burst
    of those jobs had crowded the push runs out of.

    Args:
      sha: The full commit sha.
      event: The one event whose runs count, or None for every run.

    Returns:
      One record per workflow run, with ``name``, ``status``, ``conclusion`` and ``url``.

    Raises:
      WatchError: If the API call fails or returns something unparseable.
    """
    only = f"&event={event}" if event else ""
    raw = _gh(
        "api",
        f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}&per_page=100{only}",
        "--jq",
        "{total: .total_count, runs: [.workflow_runs[] | {name, status, conclusion, url: .html_url}]}",
    )
    try:
        page: dict[str, Any] = json.loads(raw) if raw else {"total": 0, "runs": []}
    except json.JSONDecodeError as exc:
        raise WatchError(f"could not parse the run list: {raw[:200]}") from exc
    runs: list[dict[str, Any]] = page["runs"]
    total = int(page["total"])
    if total > len(runs):
        raise WatchError(
            f"{total} runs exist for {sha} but only {len(runs)} fit one page — "
            "this watch would judge a subset and call it the whole"
        )
    return runs


def _report(sha: str, runs: list[dict[str, Any]], settled: bool) -> None:
    """Print one line per run, and a verdict only when there is one to give.

    ``verdict`` counts a null conclusion against, which is right for a finished run and
    wrong for one still going — so calling it on an unsettled list labels healthy in-flight
    jobs as failures. That is what ``--once`` did during ordinary CI: two running jobs
    printed as ``RED … failed: CI (no conclusion)``. An unsettled list gets its statuses and
    an explicit no-verdict line instead.

    Args:
      sha: The commit being reported on, printed so the reader can check it themselves.
      runs: The run records.
      settled: Whether every run has finished, which is what makes a verdict meaningful.

    Returns:
      None.

    Raises:
      None.
    """
    width = max((len(str(run.get("name", ""))) for run in runs), default=0)
    for run in sorted(runs, key=lambda r: str(r.get("name", ""))):
        name = str(run.get("name", "?")).ljust(width)
        print(f"  {name}  {run.get('conclusion') or run.get('status')}")
    if not settled:
        running = sum(1 for run in runs if run.get("status") not in FINISHED_STATUSES)
        print(f"\nno verdict on {sha} — {running} of {len(runs)} still going")
        return
    ok, bad = verdict(runs)
    print(f"\n{'green' if ok else 'RED'} on {sha}")
    if bad:
        print("  failed: " + ", ".join(bad))


def moved(sha: str, pr: int | None, branch: str | None) -> str | None:
    """Report the new sha if the watched ref has moved, else None.

    Watching a fixed sha is what makes the report honest, and it is also what makes it
    possible to sit watching a commit that is no longer the head — someone pushes, and a
    green verdict arrives about work that has been superseded. That is a weaker version of
    the bug this file exists to prevent, so it is detected rather than tolerated. A bare
    ``--sha`` has no ref to move and is skipped.

    Args:
      sha: The commit being watched.
      pr: The pull-request selector this watch was started from, if any.
      branch: The branch selector this watch was started from, if any.

    Returns:
      The ref's current sha when it differs from the watched one, otherwise None.

    Raises:
      None.
    """
    if pr is None and branch is None:
        return None
    try:
        current = resolve_sha(pr, branch)
    except WatchError:
        return None
    return current if current != sha else None


def watch(
    sha: str,
    interval: int,
    timeout: int,
    once: bool,
    pr: int | None = None,
    branch: str | None = None,
    event: str | None = None,
) -> int:
    """Poll one commit's runs until they settle, then report.

    The first line names which runs are judged, since a filter that goes unsaid reads as
    "every run was green" when the runs it dropped were never looked at.

    Args:
      sha: The commit to watch.
      interval: Seconds between polls.
      timeout: Seconds before giving up.
      once: Poll a single time and report whatever is there, without waiting.
      pr: The pull-request selector, kept so a moved head can be detected.
      branch: The branch selector, kept for the same reason.
      event: The one event whose runs count, or None for every run.

    Returns:
      A process exit status: 0 only when the runs settled and none failed.

    Raises:
      WatchError: If the API cannot be reached.
    """
    scope = f"on {TRUNK}, so its {event} runs only" if event else "every run on it"
    what = f"{event} runs" if event else "workflow runs"
    print(f"watching {sha} — {scope}")
    deadline = time.monotonic() + timeout
    first_seen = time.monotonic()
    while True:
        runs = fetch_runs(sha, event)
        ahead = moved(sha, pr, branch)
        if ahead is not None:
            print(f"the ref moved to {ahead} while watching {sha} — re-run against the new head")
            return 2
        if is_settled(runs):
            _report(sha, runs, settled=True)
            return 0 if verdict(runs)[0] else 1
        if once:
            if not runs:
                print(f"  no {what} for this commit yet")
                return 2
            _report(sha, runs, settled=False)
            return 2
        if not runs and time.monotonic() - first_seen > STARTUP_GRACE:
            print(f"no {what} exist for {sha} after {STARTUP_GRACE}s — nothing was triggered")
            return 2
        if time.monotonic() > deadline:
            print(f"gave up after {timeout}s with runs still going — this is NOT a pass")
            _report(sha, runs, settled=False)
            return 2
        time.sleep(interval)


def main() -> int:
    """Parse arguments and run the watch.

    Args:
      None.

    Returns:
      A process exit status.

    Raises:
      None.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--pr", type=int, help="watch this pull request's head commit")
    parser.add_argument("--branch", help="watch this branch's remote tip")
    parser.add_argument("--sha", help="watch this commit explicitly")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--once", action="store_true", help="one poll, no waiting")
    args = parser.parse_args()
    try:
        if args.sha and (args.pr is not None or args.branch is not None):
            raise WatchError("--sha pins a commit; --pr and --branch resolve one. Pass one of the three")
        sha = args.sha or resolve_sha(args.pr, args.branch)
        event = build_event(sha, args.pr)
        return watch(sha, args.interval, args.timeout, args.once, args.pr, args.branch, event)
    except WatchError as exc:
        print(f"watch failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted — no verdict", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"the watch itself broke: {exc!r}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
