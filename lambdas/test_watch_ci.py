"""The CI watcher's two decisions, tested against the failures that produced them.

``scripts/watch_ci.py`` exists because hand-rolled watch loops reported a green that was
not there — twice, in different ways. Its whole claim is that the "are we done" and "did it
pass" decisions live in tested functions instead of being rewritten each time, so these
tests are that claim rather than incidental coverage. Two of them state a historical bug as
their name and would have failed against the code that shipped it.

The third decision is which runs count, and it is tested end to end: ``main`` is driven
against a fake GitHub that filters and pages as the API does and runs the watcher's real
``--jq`` through the real ``jq``, every case asserts the line printed rather than the exit
status alone, and each check that decides the population is planted into a copy of the
script to prove the cases it names notice.

The tests live here rather than beside the script because ``pytest lambdas/`` is the suite
a session runs before every push — CI's pytest step is disabled, so that run is the only
one — which is the same reason every other test of a ``.github/scripts/`` module sits in
this directory.

Attributes:
  ROOT: The repository root.
  WATCH_CI: The watcher's source, which the plants copy and never edit.
  JQ: The real ``jq``, or None when it is not installed.
  TIP: ``main``'s head in the fake.
  OLDER: A commit ``main`` has moved past, which the comparison calls ``behind``.
  BRANCH: A pull request's head, which the comparison calls ``diverged`` from ``main``.
  AHEAD: A commit built on ``main``'s head, which the comparison calls ``ahead`` of it.
  UNPUSHED: A commit GitHub has never seen, which the comparison answers Not Found.
  DEPLOYS: The workflows a push to ``main`` triggers.
  PUSH_ONLY: What the watcher's first line says when it judges push runs only.
  EVERY: What it says when it judges every run.
  VERDICTS: Every line that ends a watch. A case may print only the one it expects.
  TRUNK_SETS: The watcher's two comparison allowlists as written. A plant moves a status from
    one to the other, since deleting it would only prove it sits in some allowlist, not which.
"""

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.parse
from types import ModuleType
from typing import Any, NamedTuple

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WATCH_CI = ROOT / "scripts" / "watch_ci.py"
JQ = shutil.which("jq")

TIP = "a" * 40
OLDER = "b" * 40
BRANCH = "c" * 40
AHEAD = "d" * 40
UNPUSHED = "e" * 40
DEPLOYS = ("Deploy Infrastructure", "Deploy Lambdas", "Deploy Lambda image", "Deploy SPA image")
PUSH_ONLY = "on main, so its push runs only"
EVERY = "every run on it"
VERDICTS = (
    "green on ",
    "RED on ",
    "no verdict on ",
    "for this commit yet",
    " triggered nothing",
    " nothing was triggered",
    "gave up after ",
    "the ref moved to ",
    "watch failed: ",
    "the watch itself broke",
)
TRUNK_SETS = 'ON_TRUNK = frozenset({"identical", "behind"})\nOFF_TRUNK = frozenset({"ahead", "diverged"})'


def load(path: pathlib.Path, name: str) -> ModuleType:
    """Load the watcher from a file, so a planted copy runs exactly as the original does.

    Args:
      path: The source file.
      name: The module's name, distinct per copy so no two share state.

    Returns:
      The loaded module.

    Raises:
      AssertionError: If the file cannot be loaded as a module.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


watch_ci = load(WATCH_CI, "watch_ci")


def run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict:
    """Build one workflow-run record.

    Args:
      name: The workflow's name.
      status: The run's status.
      conclusion: The run's conclusion, or None for a run that has none.

    Returns:
      A record shaped like the one ``fetch_runs`` returns.

    Raises:
      None.
    """
    return {"name": name, "status": status, "conclusion": conclusion, "url": "u"}


class TestIsSettled:
    """When the watcher is allowed to say the answer is in."""

    def test_an_empty_list_is_NOT_settled(self):
        """Zero runs is a question, and the shape a false green takes.

        A watch pointed at a sha nothing was triggered for sees an empty list forever. If
        that counted as settled, ``verdict`` would find nothing bad in it and the watcher
        would report a pass for a commit CI never touched — which is the same wrong answer
        as reporting against a stale sha, arrived at differently.
        """
        assert watch_ci.is_settled([]) is False

    def test_one_unfinished_run_among_finished_ones_is_not_settled(self):
        """THE BUG THIS FILE EXISTS FOR, stated as a test.

        The shell condition it replaces was ``! echo "$OUT" | grep -qv completed``, which
        was intended as "no line lacks 'completed'" and printed "settled" while two deploys
        were still in progress. This is that exact fixture: two finished, two not.
        """
        runs = [
            run("Deploy Infrastructure"),
            run("Deploy App"),
            run("Deploy SPA image", status="in_progress", conclusion=None),
            run("Deploy Lambdas", status="in_progress", conclusion=None),
        ]
        assert watch_ci.is_settled(runs) is False


    @pytest.mark.parametrize("status", sorted(watch_ci.FINISHED_STATUSES))
    def test_every_finished_status_settles(self, status):
        """Parametrised over the constant, so a status added to the allowlist is covered."""
        assert watch_ci.is_settled([run("CI", status=status)]) is True


class TestVerdict:
    """What counts as a pass, once everything has finished."""

    def test_a_failure_is_named_not_just_counted(self):
        """The report has to say which one, or the reader goes hunting."""
        ok, bad = watch_ci.verdict([run("CI"), run("lambdas", conclusion="failure")])
        assert ok is False
        assert bad == ["lambdas (failure)"]


    @pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
    def test_every_bad_conclusion_fails(self, conclusion):
        """Cancelled and timed-out are not passes, and are easy to read as "not a failure"."""
        ok, _ = watch_ci.verdict([run("CI", conclusion=conclusion)])
        assert ok is False

    @pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
    def test_a_skipped_or_neutral_run_passes(self, conclusion):
        """A workflow whose jobs all skipped, as the Lambda builds do while switched off, must still read as green."""
        ok, bad = watch_ci.verdict([run("Deploy Lambdas", conclusion=conclusion)])
        assert ok is True
        assert bad == []

    def test_a_finished_run_with_NO_conclusion_fails(self):
        """An unknown outcome is not a pass.

        A completed run can carry a null conclusion. Defaulting that to good is how a
        watcher launders "I don't know" into "it's fine".
        """
        ok, bad = watch_ci.verdict([run("CI", conclusion=None)])
        assert ok is False
        assert bad == ["CI (no conclusion)"]


class TestMoved:
    """Detecting that the thing being watched is no longer the head."""


    def test_an_unchanged_ref_reports_nothing(self, monkeypatch):
        """The common case must not produce a spurious abort."""
        monkeypatch.setattr(watch_ci, "resolve_sha", lambda pr, branch: "abc")
        assert watch_ci.moved("abc", 538, None) is None

    def test_a_moved_ref_reports_the_new_sha(self, monkeypatch):
        """Someone pushed, so a verdict about the old commit is about superseded work."""
        monkeypatch.setattr(watch_ci, "resolve_sha", lambda pr, branch: "def")
        assert watch_ci.moved("abc", 538, None) == "def"


class TestWatchExitStatus:
    """The exit status, since the point is to compose with `&&`."""

    def test_settled_and_green_exits_zero(self, monkeypatch):
        """The only path to 0."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha, event: [run("CI")])
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 0

    def test_settled_and_red_exits_one(self, monkeypatch):
        """A real failure is 1 — distinguishable from the watch not working."""
        monkeypatch.setattr(
            watch_ci, "fetch_runs", lambda sha, event: [run("CI", conclusion="failure")]
        )
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 1

    def test_no_runs_at_all_exits_non_zero_rather_than_green(self, monkeypatch):
        """A sha nothing ran for is never a pass, however long you wait."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha, event: [])
        monkeypatch.setattr(watch_ci, "STARTUP_GRACE", -1)
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 2

    def test_once_with_unfinished_runs_exits_non_zero(self, monkeypatch):
        """`--once` reports what is there and must not call in-progress a pass."""
        monkeypatch.setattr(
            watch_ci,
            "fetch_runs",
            lambda sha, event: [run("CI", status="in_progress", conclusion=None)],
        )
        assert watch_ci.watch("abc", interval=0, timeout=1, once=True) == 2


    def test_a_moved_ref_stops_a_watch_that_would_have_gone_GREEN(self, monkeypatch, capsys):
        """The settled path is the one that returns 0, so it is the one that must be gated.

        The guard originally sat below the settled branch, so a watch that settled green on
        the old commit never asked whether the ref had moved — and the `&&` the docs
        recommend would then merge the new head on the strength of a verdict about the old.
        """
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha, event: [run("CI")])
        monkeypatch.setattr(watch_ci, "moved", lambda sha, pr, branch: "def")
        assert watch_ci.watch("abc", interval=0, timeout=9999, once=False, pr=538) == 2
        out = capsys.readouterr().out
        assert "the ref moved to def" in out
        assert "green" not in out


def api_run(
    sha: str, event: str, name: str, conclusion: str | None = "success", status: str = "completed"
) -> dict[str, Any]:
    """Build one workflow run as the Actions API lists it, before the watcher's ``--jq``.

    Args:
      sha: The commit it ran for.
      event: What triggered it — ``push`` is ``main``'s build, ``dynamic`` is Dependabot's.
      name: The workflow's name.
      conclusion: How it ended, or None while it has not.
      status: ``completed`` once it has ended.

    Returns:
      The run, carrying the fields the API filters on beside the ones the watcher reads.

    Raises:
      None.
    """
    return {
        "head_sha": sha,
        "event": event,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.invalid/runs/{name}",
    }


def pushed(name: str = "Deploy SPA image", conclusion: str = "success", sha: str = TIP) -> dict[str, Any]:
    """Build a finished run that a push to ``main`` triggered.

    Args:
      name: The workflow's name.
      conclusion: How it ended.
      sha: The commit it built.

    Returns:
      The run.

    Raises:
      None.
    """
    return api_run(sha, "push", name, conclusion)


def dependabot(sha: str = TIP) -> dict[str, Any]:
    """Build Dependabot's own job on a ``main`` commit, failed because its update was not possible.

    Args:
      sha: The commit it recorded.

    Returns:
      The run that once made a green ``main`` read as red.

    Raises:
      None.
    """
    return api_run(sha, "dynamic", "npm_and_yarn in /. for dompurify - Update", "failure")


class Case(NamedTuple):
    """One state of GitHub, the selector the watcher is run with, and what it must print.

    Attributes:
      name: Identifies the case, and is how a plant names it.
      argv: The watcher's selector arguments.
      runs: Every run GitHub holds, for every commit, newest first as the API orders them.
      said: Text the watcher must print — its verdict, or the reason it has none.
      exit: The exit status that must come with it.
      scope: What the first line must say is judged, or None when the watch must fail before
        judging anything.
      compare: A comparison status to answer instead of the fixture's, or ``fails`` for a
        comparison GitHub does not answer.
      offline: The watch must refuse before its first read of GitHub, so no query carries the
        input it refused.
    """

    name: str
    argv: tuple[str, ...]
    runs: tuple[dict[str, Any], ...]
    said: str
    exit: int
    scope: str | None
    compare: str | None = None
    offline: bool = False


def refused(name: str, sha: str) -> Case:
    """Build a case where ``--sha`` is not a full sha, beside ``main``'s green push runs.

    The runs are there so that anything but the refusal has something to judge: a watch that
    reached GitHub with the full sha would print green, and with anything else, no verdict.

    Args:
      name: The case's name.
      sha: What ``--sha`` is given.

    Returns:
      A case that must print the refusal naming ``sha`` and ask GitHub nothing.

    Raises:
      None.
    """
    return Case(
        name,
        ("--sha", sha),
        (dependabot(), *(pushed(deploy) for deploy in DEPLOYS)),
        f"watch failed: --sha takes a full 40-character commit sha, and {sha!r} is not one",
        2,
        None,
        offline=True,
    )


CASES: tuple[Case, ...] = (
    Case(
        "a_failed_dependabot_run_beside_green_push_runs_is_green",
        ("--branch", "main"),
        (
            dependabot(),
            api_run(TIP, "dynamic", "Dependency Graph"),
            *(pushed(name) for name in DEPLOYS),
            pushed("Deploy Lambdas", "failure", sha=OLDER),
        ),
        f"green on {TIP}",
        0,
        PUSH_ONLY,
    ),
    Case(
        "a_failed_push_run_is_red_whatever_passed_beside_it",
        ("--branch", "main"),
        (api_run(TIP, "dynamic", "Dependency Graph"), pushed("Deploy Lambdas", "failure"), pushed()),
        f"RED on {TIP}\n  failed: Deploy Lambdas (failure)",
        1,
        PUSH_ONLY,
    ),
    Case(
        "only_non_push_runs_on_main_wait_for_the_push_runs",
        ("--branch", "main", "--once"),
        (
            dependabot(),
            api_run(TIP, "dynamic", "Dependency Graph"),
            api_run(TIP, "workflow_dispatch", "Migrate system_settings"),
            api_run(TIP, "schedule", "Security", "failure"),
            pushed(sha=OLDER),
        ),
        "no push runs for this commit yet",
        2,
        PUSH_ONLY,
    ),
    Case(
        "only_non_push_runs_on_main_are_no_verdict_once_the_grace_runs_out",
        ("--branch", "main"),
        (
            dependabot(),
            api_run(TIP, "dynamic", "Dependency Graph"),
            api_run(TIP, "workflow_dispatch", "Migrate system_settings"),
            api_run(TIP, "schedule", "Security", "failure"),
            pushed(sha=OLDER),
        ),
        f"no push runs exist for {TIP} after -1s — the push triggered nothing",
        2,
        PUSH_ONLY,
    ),
    Case(
        "a_commit_main_has_moved_past_is_judged_by_its_push_runs",
        ("--sha", OLDER),
        (dependabot(OLDER), *(pushed(name, sha=OLDER) for name in DEPLOYS), pushed()),
        f"green on {OLDER}",
        0,
        PUSH_ONLY,
    ),
    Case(
        "a_pull_request_head_is_judged_by_every_run_on_it",
        ("--pr", "538"),
        (
            api_run(BRANCH, "pull_request", "CI"),
            api_run(BRANCH, "workflow_dispatch", "Deploy Infrastructure", "failure"),
        ),
        f"RED on {BRANCH}\n  failed: Deploy Infrastructure (failure)",
        1,
        EVERY,
    ),
    Case(
        "a_pull_request_watch_never_asks_where_its_head_sits",
        ("--pr", "538"),
        (api_run(BRANCH, "pull_request", "CI"), api_run(BRANCH, "pull_request", "Security")),
        f"green on {BRANCH}",
        0,
        EVERY,
        compare="fails",
    ),
    Case(
        "a_commit_diverged_from_main_is_judged_by_every_run_on_it",
        ("--sha", BRANCH),
        (api_run(BRANCH, "pull_request", "CI"), api_run(BRANCH, "pull_request", "Security")),
        f"green on {BRANCH}",
        0,
        EVERY,
    ),
    Case(
        "a_commit_ahead_of_main_is_judged_by_every_run_on_it",
        ("--sha", AHEAD),
        (api_run(AHEAD, "pull_request", "CI"),),
        f"green on {AHEAD}",
        0,
        EVERY,
    ),
    Case(
        "a_burst_of_dependabot_jobs_cannot_push_main_past_one_page",
        ("--branch", "main"),
        (*(dependabot() for _ in range(120)), *(pushed(name) for name in DEPLOYS)),
        f"green on {TIP}",
        0,
        PUSH_ONLY,
    ),
    Case(
        "more_push_runs_than_one_page_is_no_verdict",
        ("--branch", "main"),
        tuple(pushed() for _ in range(101)),
        f"watch failed: 101 runs exist for {TIP} but only 100 fit one page",
        2,
        PUSH_ONLY,
    ),
    Case(
        "a_comparison_github_does_not_answer_is_no_verdict",
        ("--branch", "main"),
        (dependabot(), *(pushed(name) for name in DEPLOYS)),
        f"watch failed: could not ask GitHub whether {TIP} is on main",
        2,
        None,
        compare="fails",
    ),
    Case(
        "a_commit_github_has_never_seen_is_no_verdict",
        ("--sha", UNPUSHED),
        (),
        f"watch failed: could not ask GitHub whether {UNPUSHED} is on main",
        2,
        None,
    ),
    Case(
        "a_comparison_status_it_does_not_know_is_no_verdict",
        ("--branch", "main"),
        (dependabot(), *(pushed(name) for name in DEPLOYS)),
        f"watch failed: could not tell whether {TIP} is on main",
        2,
        None,
        compare="unrelated",
    ),
    *(
        refused(name, sha)
        for name, sha in (
            ("a_short_sha_is_refused_rather_than_read_as_a_push_that_triggered_nothing", TIP[:8]),
            ("an_empty_sha_is_refused_rather_than_judging_local_head", ""),
            ("a_padded_sha_is_refused_before_github_is_asked", TIP + " "),
            ("a_sha_longer_than_forty_characters_is_refused", TIP + "a"),
            ("forty_characters_that_are_not_hex_are_refused", "g" * 40),
        )
    ),
    Case(
        "an_uppercase_sha_is_judged_since_github_matches_it",
        ("--sha", TIP.upper()),
        tuple(pushed(name) for name in DEPLOYS),
        f"green on {TIP.upper()}",
        0,
        PUSH_ONLY,
    ),
)


class FakeGitHub:
    """GitHub as the watcher's four reads see it: a PR head, a branch tip, a comparison, runs.

    Runs are filtered by ``head_sha`` and ``event`` BEFORE the page is cut, and
    ``total_count`` counts what the filter left, which is how the API pages — the property a
    burst of Dependabot jobs tests. A query parameter it does not know is ignored, as the API
    ignores one, so a misspelt filter shows up as the runs it failed to drop. Every answer
    goes through the real ``jq`` with the watcher's own ``--jq``, so the expression measured is
    the one it sends. A call this does not recognise is recorded and refused, never answered.

    Attributes:
      module: The watcher under test, whose ``WatchError`` a read GitHub refuses raises.
      case: The case being driven.
      reads: Every call that was answered.
      unfaked: Every call that was not recognised.
    """

    def __init__(self, module: ModuleType, case: Case) -> None:
        """Hold one case's state of GitHub.

        Args:
          module: The watcher under test.
          case: The case being driven.

        Returns:
          None.

        Raises:
          None.
        """
        self.module = module
        self.case = case
        self.reads: list[tuple[str, ...]] = []
        self.unfaked: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        """Answer one ``gh`` call the way ``watch_ci._gh`` returns it.

        Args:
          *args: The arguments ``gh`` was called with.

        Returns:
          The stripped output of the call's ``--jq`` over the document GitHub would send.

        Raises:
          WatchError: For a comparison the case says GitHub does not answer, or a commit it
            does not know.
          AssertionError: For a call this fake does not recognise.
        """
        kind = self.kind(args)
        if kind is None or "--jq" not in args:
            self.unfaked.append(args)
            raise AssertionError(f"the fake GitHub does not answer {args}")
        self.reads.append(args)
        path, _, query = args[1].partition("?")
        if kind == "pr":
            document: dict[str, Any] = {"headRefOid": BRANCH}
        elif kind == "tip":
            document = {"sha": TIP}
        elif kind == "compare":
            document = {"status": self.status(path.rsplit("...", 1)[1], args)}
        else:
            document = self.runs(urllib.parse.parse_qs(query))
        return self.jq(document, args[args.index("--jq") + 1], args)

    @staticmethod
    def kind(args: tuple[str, ...]) -> str | None:
        """Name which of the four reads one ``gh`` call is.

        Args:
          args: The arguments ``gh`` was called with.

        Returns:
          ``pr``, ``tip``, ``compare`` or ``runs``, or None for a call this fake does not answer.

        Raises:
          None.
        """
        if args[:2] == ("pr", "view"):
            return "pr"
        if len(args) < 2 or args[0] != "api":
            return None
        path = args[1].partition("?")[0]
        if path == "repos/{owner}/{repo}/commits/main":
            return "tip"
        if path.startswith("repos/{owner}/{repo}/compare/main..."):
            return "compare"
        if path == "repos/{owner}/{repo}/actions/runs":
            return "runs"
        return None

    def status(self, sha: str, args: tuple[str, ...]) -> str:
        """Compare a commit with ``main``, as ``compare/main...<sha>`` reports it.

        A short sha is resolved to the one commit it begins, and an ambiguous or unknown one
        is Not Found, as GitHub's comparison answers both — while the run list matches a full
        sha only, which is the gap a short ``--sha`` fell through. Both reads ignore case, as
        GitHub's do.

        Args:
          sha: The commit compared, in full or as a prefix.
          args: The whole call, for the error GitHub's refusal carries.

        Returns:
          The comparison's status.

        Raises:
          WatchError: When the case says GitHub does not answer, or the commit is unknown.
        """
        if self.case.compare == "fails":
            raise self.module.WatchError(f"gh {' '.join(args)} failed: HTTP 502: Server Error")
        if self.case.compare is not None:
            return self.case.compare
        known = {TIP: "identical", OLDER: "behind", BRANCH: "diverged", AHEAD: "ahead"}
        begun = [full for full in known if full.startswith(sha.lower())]
        if len(begun) != 1:
            raise self.module.WatchError(f"gh {' '.join(args)} failed: Not Found (HTTP 404)")
        return known[begun[0]]

    def runs(self, query: dict[str, list[str]]) -> dict[str, Any]:
        """List one commit's runs as ``actions/runs`` does: filter, count, then page.

        Args:
          query: The parsed query string.

        Returns:
          The API's document: the filtered total, and one page of runs.

        Raises:
          None.
        """
        sha = query["head_sha"][0].lower()
        event = query.get("event", [None])[0]
        kept = [
            r for r in self.case.runs if r["head_sha"] == sha and event in (None, r["event"])
        ]
        per_page = int(query.get("per_page", ["30"])[0])
        return {"total_count": len(kept), "workflow_runs": kept[:per_page]}

    def jq(self, document: dict[str, Any], expression: str, args: tuple[str, ...]) -> str:
        """Run the watcher's ``--jq`` over a document with the real ``jq``, as ``gh`` does.

        Args:
          document: What GitHub would send.
          expression: The watcher's ``--jq`` expression.
          args: The whole call, for the error an unparseable expression carries.

        Returns:
          The output, stripped, raw for a string as ``gh`` prints one.

        Raises:
          WatchError: When ``jq`` refuses the expression, as ``gh`` fails on one.
        """
        done = subprocess.run(  # noqa: S603
            [require_jq(), "-r", expression],
            input=json.dumps(document),
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise self.module.WatchError(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
        return done.stdout.strip()


def require_jq() -> str:
    """Return the real ``jq``, or fail the test outright rather than let it pass unmeasured.

    Args:
      None.

    Returns:
      The path to ``jq``.

    Raises:
      pytest.fail.Exception: When ``jq`` is not installed, since every read goes through it.
    """
    if JQ is None:
        pytest.fail("no jq on PATH — the fake GitHub runs the watcher's real --jq through it")
    return JQ


def drive(
    module: ModuleType, case: Case, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str | None:
    """Run the watcher's ``main`` against one case, and say what it got wrong.

    Asserts the printed line, never the exit status alone: RED and no verdict differ by one
    exit code, and "watch failed" and "the watch itself broke" by none. A case also fails if a
    verdict other than its own was printed beside it, if the first line misstates which runs
    were judged, or if a case that must refuse offline asked GitHub anything.

    Args:
      module: The watcher, original or planted.
      case: The case to drive.
      monkeypatch: The fixture that installs the fake and the arguments.
      capsys: The fixture that captures what the watcher prints.

    Returns:
      None when the watcher did what the case requires, otherwise why not.

    Raises:
      None.
    """
    fake = FakeGitHub(module, case)
    monkeypatch.setattr(module, "_gh", fake)
    monkeypatch.setattr(module, "STARTUP_GRACE", -1)
    monkeypatch.setattr(
        sys, "argv", ["watch_ci.py", *case.argv, "--interval", "0", "--timeout", "1"]
    )
    code = module.main()
    printed = capsys.readouterr()
    said = printed.out + printed.err
    if fake.unfaked or bool(fake.reads) == case.offline:
        wanted = "none" if case.offline else "some"
        return (
            f"the fake answered {len(fake.reads)} reads, wanted {wanted}, and refused "
            f"{fake.unfaked}: {said!r}"
        )
    if code != case.exit:
        return f"exit {code}, wanted {case.exit}: {said!r}"
    if case.said not in said:
        return f"did not say {case.said!r}: {said!r}"
    others = [v for v in VERDICTS if v in said and v not in case.said]
    if others:
        return f"also said {others}: {said!r}"
    if case.scope is None:
        return f"judged runs it should have refused to: {said!r}" if "watching " in said else None
    if case.scope not in said:
        return f"did not say it judged {case.scope!r}: {said!r}"
    return None


class Plant(NamedTuple):
    """One check in the watcher, broken, and the cases that must notice.

    Attributes:
      name: Identifies the plant.
      old: The check's text, which must occur exactly once in the watcher.
      new: What the check is replaced with.
      breaks: Every case that must fail against the planted copy. No other may.
    """

    name: str
    old: str
    new: str
    breaks: tuple[str, ...]


PLANTS: tuple[Plant, ...] = (
    Plant(
        "main_counts_push_runs_only",
        'only = f"&event={event}" if event else ""',
        'only = ""',
        (
            "a_failed_dependabot_run_beside_green_push_runs_is_green",
            "only_non_push_runs_on_main_wait_for_the_push_runs",
            "only_non_push_runs_on_main_are_no_verdict_once_the_grace_runs_out",
            "a_commit_main_has_moved_past_is_judged_by_its_push_runs",
            "a_burst_of_dependabot_jobs_cannot_push_main_past_one_page",
        ),
    ),
    Plant(
        "the_api_filters_the_runs_not_the_jq",
        'only = f"&event={event}" if event else ""\n'
        "    raw = _gh(\n"
        '        "api",\n'
        '        f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}&per_page=100{only}",\n'
        '        "--jq",\n'
        '        "{total: .total_count, runs: [.workflow_runs[] | {name',
        "only = f' | select(.event == \"{event}\")' if event else \"\"\n"
        "    raw = _gh(\n"
        '        "api",\n'
        '        f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}&per_page=100",\n'
        '        "--jq",\n'
        '        "{total: .total_count, runs: [.workflow_runs[]" + only + " | {name',
        (
            "a_failed_dependabot_run_beside_green_push_runs_is_green",
            "a_failed_push_run_is_red_whatever_passed_beside_it",
            "only_non_push_runs_on_main_wait_for_the_push_runs",
            "only_non_push_runs_on_main_are_no_verdict_once_the_grace_runs_out",
            "a_commit_main_has_moved_past_is_judged_by_its_push_runs",
            "a_burst_of_dependabot_jobs_cannot_push_main_past_one_page",
        ),
    ),
    Plant(
        "the_tip_of_main_is_on_main",
        TRUNK_SETS,
        'ON_TRUNK = frozenset({"behind"})\nOFF_TRUNK = frozenset({"ahead", "diverged", "identical"})',
        (
            "a_failed_dependabot_run_beside_green_push_runs_is_green",
            "a_failed_push_run_is_red_whatever_passed_beside_it",
            "only_non_push_runs_on_main_wait_for_the_push_runs",
            "only_non_push_runs_on_main_are_no_verdict_once_the_grace_runs_out",
            "a_burst_of_dependabot_jobs_cannot_push_main_past_one_page",
            "more_push_runs_than_one_page_is_no_verdict",
            "an_uppercase_sha_is_judged_since_github_matches_it",
        ),
    ),
    Plant(
        "a_commit_behind_main_is_on_main",
        TRUNK_SETS,
        'ON_TRUNK = frozenset({"identical"})\nOFF_TRUNK = frozenset({"ahead", "diverged", "behind"})',
        ("a_commit_main_has_moved_past_is_judged_by_its_push_runs",),
    ),
    Plant(
        "a_diverged_commit_is_off_main",
        TRUNK_SETS,
        'ON_TRUNK = frozenset({"identical", "behind", "diverged"})\nOFF_TRUNK = frozenset({"ahead"})',
        ("a_commit_diverged_from_main_is_judged_by_every_run_on_it",),
    ),
    Plant(
        "a_commit_ahead_of_main_is_off_main",
        TRUNK_SETS,
        'ON_TRUNK = frozenset({"identical", "behind", "ahead"})\nOFF_TRUNK = frozenset({"diverged"})',
        ("a_commit_ahead_of_main_is_judged_by_every_run_on_it",),
    ),
    Plant(
        "a_status_in_neither_allowlist_is_no_verdict",
        "    raise WatchError(f\"could not tell whether",
        "    return None\n    raise WatchError(f\"could not tell whether",
        ("a_comparison_status_it_does_not_know_is_no_verdict",),
    ),
    Plant(
        "a_pull_request_is_judged_without_the_comparison",
        "    if pr is not None:\n        return None\n    try:\n",
        "    try:\n",
        ("a_pull_request_watch_never_asks_where_its_head_sits",),
    ),
    Plant(
        "a_pull_request_keeps_every_run_on_its_head",
        "    if pr is not None:\n        return None\n",
        '    if pr is not None:\n        return "pull_request"\n',
        (
            "a_pull_request_head_is_judged_by_every_run_on_it",
            "a_pull_request_watch_never_asks_where_its_head_sits",
        ),
    ),
    Plant(
        "a_comparison_github_refuses_is_no_verdict",
        "    except WatchError as exc:\n        raise WatchError(\n",
        "    except WatchError as exc:\n        return None\n        raise WatchError(\n",
        (
            "a_comparison_github_does_not_answer_is_no_verdict",
            "a_commit_github_has_never_seen_is_no_verdict",
        ),
    ),
    Plant(
        "a_page_that_cannot_hold_every_run_is_no_verdict",
        "    if total > len(runs):",
        "    if False:",
        ("more_push_runs_than_one_page_is_no_verdict",),
    ),
    Plant(
        "no_run_yet_is_no_verdict_in_one_poll",
        'print(f"  no {what} for this commit yet")\n                return 2',
        'print(f"  no {what} for this commit yet")\n                return 0',
        ("only_non_push_runs_on_main_wait_for_the_push_runs",),
    ),
    Plant(
        "no_run_after_the_grace_is_no_verdict",
        '— {cause}")\n            return 2',
        '— {cause}")\n            return 0',
        ("only_non_push_runs_on_main_are_no_verdict_once_the_grace_runs_out",),
    ),
    Plant(
        "a_pinned_sha_must_be_a_full_one",
        "        if args.sha is not None and not FULL_SHA.fullmatch(args.sha):\n",
        "        if False:\n",
        (
            "a_short_sha_is_refused_rather_than_read_as_a_push_that_triggered_nothing",
            "an_empty_sha_is_refused_rather_than_judging_local_head",
            "a_padded_sha_is_refused_before_github_is_asked",
            "a_sha_longer_than_forty_characters_is_refused",
            "forty_characters_that_are_not_hex_are_refused",
        ),
    ),
)


class TestWhichRunsCount:
    """Which runs are a commit's build: push runs on ``main``, every run anywhere else."""

    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    def test_the_watcher_prints_each_cases_verdict(self, case, monkeypatch, capsys):
        """Drive the real watcher through one state of GitHub, and read what it printed.

        Args:
          case: The case.
          monkeypatch: Installs the fake GitHub and the arguments.
          capsys: Captures what the watcher prints.

        Returns:
          None.

        Raises:
          AssertionError: When the watcher's verdict, exit status or scope is not the case's.
        """
        why = drive(watch_ci, case, monkeypatch, capsys)
        assert why is None, why

    @pytest.mark.parametrize("plant", PLANTS, ids=lambda plant: plant.name)
    def test_each_planted_check_breaks_exactly_its_cases(self, plant, tmp_path, monkeypatch, capsys):
        """Break one check in a copy of the watcher, and require exactly its cases to notice.

        The copy is written beside the test, never over the script, so no restore can fail and
        leave a later run measuring a mutant. A plant whose text no longer occurs once has
        drifted from the script and fails rather than planting nothing.

        Args:
          plant: The check to break.
          tmp_path: Where the planted copy is written.
          monkeypatch: Installs the fake GitHub and the arguments, per case.
          capsys: Captures what the planted copy prints.

        Returns:
          None.

        Raises:
          AssertionError: When the plant's text has drifted, or the cases that broke are not
            the ones it names.
        """
        source = WATCH_CI.read_text()
        assert plant.breaks, f"{plant.name}: a plant that names no case proves nothing"
        assert source.count(plant.old) == 1, f"{plant.name}: its text occurs {source.count(plant.old)} times"
        planted = tmp_path / "watch_ci_planted.py"
        planted.write_text(source.replace(plant.old, plant.new))
        module = load(planted, f"watch_ci_{plant.name}")
        broken = set()
        for case in CASES:
            with monkeypatch.context() as patch:
                if drive(module, case, patch, capsys) is not None:
                    broken.add(case.name)
        assert broken == set(plant.breaks)
