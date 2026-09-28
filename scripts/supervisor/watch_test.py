"""The fixture corpus for ``watch.sh``'s verdict on main, the line that wakes the supervisor.

GitHub's list endpoint intermittently serves a page of runs weeks stale in place of the newest, and
a watch that read main's head off that page printed ``no push run yet`` while main was green — the
verdict the supervisor's guide treats, when it persists, as a push event GitHub dropped and a
human's call. Each case here runs the real ``watch.sh`` once against a throwaway checkout and bare
origin, with a fake ``gh`` first on PATH, and asserts the exact ``MAIN`` or ``ALERT`` line it
prints about main, including the case the fault produced and the verdict it faked.

The fake's model of the runs endpoint is the queue corpus's ``fake_gh``, imported rather than
copied, so both readers of main are measured against one model of the stale page: it serves that
page to any read not filtered by ``head_sha``. This module answers ``gh pr list`` itself, with no
PR open, and stubs the two scripts ``watch.sh`` calls beside it.

Usage: ``python3 scripts/supervisor/watch_test.py`` — no arguments, standard library only, needs
``git`` and ``bash``, and exits non-zero if any case does not behave as declared. ``--fake-gh`` is
how the corpus runs itself as ``gh``, never an option for a person.

Attributes:
  HERE: This file's directory, which holds the ``watch.sh`` under test.
  CASES: Every case, each run against its own fixture.
"""

import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pr-queue"))

from pre_push_test import (
    HEAD,
    OLDER,
    RUNS_ENDPOINT,
    dependabot,
    fake_gh,
    pushed,
)


class Case(NamedTuple):
    """One state of main's Actions runs, and the line ``watch.sh`` must print about main.

    Attributes:
      name: Identifies the case in the report.
      runs: Every run the endpoint holds, newest first, their shas still sentinels.
      want: The one line about main, with ``{sha}`` for the head's first eight characters.
      stale: The list endpoint serves its stale page to any read not filtered by ``head_sha``.
      gh_fails: The fake ``gh`` exits non-zero, as a network or authentication failure does.
    """

    name: str
    runs: tuple[dict[str, str], ...]
    want: str
    stale: bool = False
    gh_fails: bool = False


CASES: tuple[Case, ...] = (
    Case("a_stale_list_page_cannot_hide_a_green_head",
         (pushed(workflow="Deploy SPA image"), pushed(workflow="Deploy Lambda image"),
          pushed(sha=OLDER)),
         "MAIN {sha} green", stale=True),
    Case("a_failed_push_run_on_the_head_is_red",
         (dependabot("success"), pushed("failure", "Deploy Lambdas"), pushed()),
         "MAIN {sha} RED: Deploy Lambdas"),
    Case("a_head_with_only_a_dependabot_job_has_no_push_run_yet",
         (dependabot(), pushed(sha=OLDER)),
         "MAIN {sha} no push run yet"),
    Case("more_push_runs_than_one_page_holds_is_unreadable",
         (*(pushed() for _ in range(100)), pushed("failure", "Deploy Lambdas")),
         "MAIN {sha} unreadable: 101 push runs, one page holds 100"),
    Case("a_gh_that_fails_is_an_alert_not_a_verdict",
         (pushed(),),
         "ALERT gh api actions/runs failed", gh_fails=True),
)


def _git(cwd: pathlib.Path, *args: str) -> str:
    """Runs one git command in a fixture and returns its output.

    Args:
      cwd: The repository to run it in.
      *args: The git arguments.

    Returns:
      The command's stdout, stripped.

    Raises:
      subprocess.CalledProcessError: If git fails, since a fixture that did not build measures
        nothing.
    """
    return subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",  # noqa: S607
         *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _fixture(root: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Builds a checkout with a bare origin, the ``watch.sh`` under test and stubs beside it.

    ``watch.sh`` finds its checkout from its own location and its queue from the ``Q=`` line of
    that checkout's pre-push hook, so the script is copied in and the hook names an empty queue.

    Args:
      root: An empty directory.

    Returns:
      The copied ``watch.sh`` and main's head sha.

    Raises:
      subprocess.CalledProcessError: If a git step fails.
    """
    origin, repo, queue = root / "origin.git", root / "repo", root / "queue"
    for d in (origin, repo, queue):
        d.mkdir()
    _git(origin, "init", "-q", "--bare")
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    (repo / ".git" / "hooks" / "pre-push").write_text(f"#!/bin/sh\nQ={shlex.quote(str(queue))}\n")
    tools = repo / "scripts" / "supervisor"
    tools.mkdir(parents=True)
    watch = tools / "watch.sh"
    shutil.copy(HERE / "watch.sh", watch)
    (tools / "overlap.sh").write_text("#!/bin/sh\nexit 0\n")
    (tools / "done_check.py").write_text("")
    for f in (watch, tools / "overlap.sh"):
        f.chmod(0o755)
    return watch, _git(repo, "rev-parse", "HEAD")


def run(case: Case, root: pathlib.Path) -> list[str]:
    """Runs ``watch.sh`` once for a case and compares what it said about main.

    Args:
      case: The case.
      root: An empty directory for its fixture.

    Returns:
      One message per way the case failed, empty when it held.

    Raises:
      subprocess.CalledProcessError: If the fixture does not build.
    """
    watch, sha = _fixture(root)
    bindir = root / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(pathlib.Path(__file__)))} "
        f"--fake-gh \"$@\"\n")
    (bindir / "gh").chmod(0o755)
    state = root / "gh-state.json"
    runs = [{**r, "headSha": {HEAD: sha, OLDER: "1" * 40}[r["headSha"]]} for r in case.runs]
    state.write_text(json.dumps({"fail": case.gh_fails, "runs": runs, "stale": case.stale}))
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
           "FAKE_GH_STATE": str(state), "SUPERVISOR_STATE_DIR": str(root / "state")}
    done = subprocess.run(["bash", str(watch), "--self", "me"],  # noqa: S603, S607
                          capture_output=True, text=True, env=env, timeout=60)
    said = [line.removeprefix("= ") for line in done.stdout.splitlines()]
    about_main = [line for line in said if line.startswith(("MAIN ", "ALERT "))]
    want = case.want.format(sha=sha[:8])
    problems = []
    if done.returncode != 0:
        problems.append(f"watch.sh exited {done.returncode}: {done.stderr.strip()[:200]!r}")
    if about_main != [want]:
        problems.append(f"said {about_main!r} about main, wanted [{want!r}]")
    calls = state.with_suffix(".calls")
    if not calls.is_file() or f"api {RUNS_ENDPOINT}?head_sha={sha}" not in calls.read_text():
        problems.append("the fake gh was never asked for the head's runs, so this measured "
                        "whatever gh PATH found instead")
    return problems


def main() -> int:
    """Runs every case in its own fixture and reports each failure.

    Args:
      None.

    Returns:
      0 when every case holds, 1 otherwise.

    Raises:
      None.
    """
    failed = 0
    for case in CASES:
        with tempfile.TemporaryDirectory() as root:
            problems = run(case, pathlib.Path(root))
        failed += bool(problems)
        for problem in problems:
            print(f"FAIL {case.name}: {problem}")
    print(f"{len(CASES) - failed}/{len(CASES)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fake-gh"]:
        if sys.argv[2:4] == ["pr", "list"]:
            sys.exit(0)
        sys.exit(fake_gh(sys.argv[2:]))
    sys.exit(main())
