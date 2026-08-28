"""The CI watcher's two decisions, tested against the failures that produced them.

``scripts/watch_ci.py`` exists because hand-rolled watch loops reported a green that was
not there — twice, in different ways. Its whole claim is that the "are we done" and "did it
pass" decisions live in tested functions instead of being rewritten each time, so these
tests are that claim rather than incidental coverage. Two of them state a historical bug as
their name and would have failed against the code that shipped it.

The tests live here rather than beside the script because ``pytest lambdas/`` is what CI
runs, which is the same reason ``test_plan_deploy.py`` tests a ``.github/scripts/`` module
from this directory.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("watch_ci", ROOT / "scripts" / "watch_ci.py")
assert _spec is not None and _spec.loader is not None
watch_ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch_ci)


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

    @pytest.mark.parametrize("status", ["queued", "in_progress", "requested", "waiting", "pending"])
    def test_every_github_running_status_blocks(self, status):
        """Each status GitHub uses for work in flight holds the verdict back."""
        assert watch_ci.is_settled([run("CI", status=status, conclusion=None)]) is False

    @pytest.mark.parametrize("status", sorted(watch_ci.FINISHED_STATUSES))
    def test_every_finished_status_settles(self, status):
        """Parametrised over the constant, so a status added to the allowlist is covered."""
        assert watch_ci.is_settled([run("CI", status=status)]) is True

    def test_an_unrecognised_status_is_treated_as_unfinished(self):
        """An unknown status waits rather than deciding.

        GitHub has added statuses before. The safe direction for one this does not know is
        to keep waiting — declaring a result from a status whose meaning is unknown is the
        failure mode, and waiting merely costs time.
        """
        assert watch_ci.is_settled([run("CI", status="something_new", conclusion=None)]) is False

    def test_all_completed_is_settled(self):
        """The ordinary case still terminates."""
        assert watch_ci.is_settled([run("CI"), run("Security", conclusion="skipped")]) is True


class TestVerdict:
    """What counts as a pass, once everything has finished."""

    def test_a_failure_is_named_not_just_counted(self):
        """The report has to say which one, or the reader goes hunting."""
        ok, bad = watch_ci.verdict([run("CI"), run("lambdas", conclusion="failure")])
        assert ok is False
        assert bad == ["lambdas (failure)"]

    def test_skipped_and_neutral_pass(self):
        """A skipped job decided correctly not to run.

        This repo's ``apply`` skips on every pull request. Treating that as red would make
        the watcher useless on pull requests, which is the case it is most wanted for.
        """
        ok, bad = watch_ci.verdict([run("apply", conclusion="skipped"), run("x", conclusion="neutral")])
        assert (ok, bad) == (True, [])

    @pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
    def test_every_bad_conclusion_fails(self, conclusion):
        """Cancelled and timed-out are not passes, and are easy to read as "not a failure"."""
        ok, _ = watch_ci.verdict([run("CI", conclusion=conclusion)])
        assert ok is False

    def test_a_finished_run_with_NO_conclusion_fails(self):
        """An unknown outcome is not a pass.

        A completed run can carry a null conclusion. Defaulting that to good is how a
        watcher launders "I don't know" into "it's fine".
        """
        ok, bad = watch_ci.verdict([run("CI", conclusion=None)])
        assert ok is False
        assert bad == ["CI (no conclusion)"]

    def test_one_failure_among_many_passes_still_fails(self):
        """The verdict is an AND, and a majority-green report would be worse than none."""
        runs = [run("a"), run("b"), run("c", conclusion="failure"), run("d")]
        assert watch_ci.verdict(runs)[0] is False


class TestResolveSha:
    """The selector, which is what keeps a report attached to a commit."""

    def test_pr_and_branch_together_are_refused(self):
        """Two selectors name two commits, and picking one silently is how the wrong one wins."""
        with pytest.raises(watch_ci.WatchError, match="pass one"):
            watch_ci.resolve_sha(pr=1, branch="main")


class TestMoved:
    """Detecting that the thing being watched is no longer the head."""

    def test_a_bare_sha_has_no_ref_to_move(self, monkeypatch):
        """With no selector there is nothing to re-resolve, and no call should be made."""
        monkeypatch.setattr(
            watch_ci, "resolve_sha", lambda *a, **k: pytest.fail("must not re-resolve")
        )
        assert watch_ci.moved("abc", None, None) is None

    def test_an_unchanged_ref_reports_nothing(self, monkeypatch):
        """The common case must not produce a spurious abort."""
        monkeypatch.setattr(watch_ci, "resolve_sha", lambda pr, branch: "abc")
        assert watch_ci.moved("abc", 538, None) is None

    def test_a_moved_ref_reports_the_new_sha(self, monkeypatch):
        """Someone pushed, so a verdict about the old commit is about superseded work."""
        monkeypatch.setattr(watch_ci, "resolve_sha", lambda pr, branch: "def")
        assert watch_ci.moved("abc", 538, None) == "def"

    def test_a_failed_re_resolution_does_not_abort_the_watch(self, monkeypatch):
        """A transient API failure must not read as "the ref moved".

        The watch is the useful thing; a blip in the extra check should cost nothing.
        """

        def boom(pr, branch):
            raise watch_ci.WatchError("network")

        monkeypatch.setattr(watch_ci, "resolve_sha", boom)
        assert watch_ci.moved("abc", 538, None) is None


class TestWatchExitStatus:
    """The exit status, since the point is to compose with `&&`."""

    def test_settled_and_green_exits_zero(self, monkeypatch):
        """The only path to 0."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha: [run("CI")])
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 0

    def test_settled_and_red_exits_one(self, monkeypatch):
        """A real failure is 1 — distinguishable from the watch not working."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha: [run("CI", conclusion="failure")])
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 1

    def test_no_runs_at_all_exits_non_zero_rather_than_green(self, monkeypatch):
        """A sha nothing ran for is never a pass, however long you wait."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha: [])
        monkeypatch.setattr(watch_ci, "STARTUP_GRACE", -1)
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 2

    def test_once_with_unfinished_runs_exits_non_zero(self, monkeypatch):
        """`--once` reports what is there and must not call in-progress a pass."""
        monkeypatch.setattr(
            watch_ci, "fetch_runs", lambda sha: [run("CI", status="in_progress", conclusion=None)]
        )
        assert watch_ci.watch("abc", interval=0, timeout=1, once=True) == 2

    def test_a_moved_ref_stops_the_watch_AND_SAYS_SO(self, monkeypatch, capsys):
        """Asserting the reason, not just the code — 2 is also what a timeout returns.

        The first version of this test asserted only ``== 2`` and passed with the moved-ref
        guard **deleted**, because the deadline path returns 2 as well. A test that cannot
        tell its own guard from the one beside it is not holding anything.

        ``once=True`` rather than a long timeout, so deleting the guard fails this in
        milliseconds instead of spinning until the deadline — which the guard sitting above
        the ``once`` branch is what makes possible.
        """
        monkeypatch.setattr(
            watch_ci, "fetch_runs", lambda sha: [run("CI", status="in_progress", conclusion=None)]
        )
        monkeypatch.setattr(watch_ci, "moved", lambda sha, pr, branch: "def")
        assert watch_ci.watch("abc", interval=0, timeout=9999, once=True, pr=538) == 2
        assert "the ref moved to def" in capsys.readouterr().out

    def test_a_moved_ref_stops_a_watch_that_would_have_gone_GREEN(self, monkeypatch, capsys):
        """The settled path is the one that returns 0, so it is the one that must be gated.

        The guard originally sat below the settled branch, so a watch that settled green on
        the old commit never asked whether the ref had moved — and the `&&` the docs
        recommend would then merge the new head on the strength of a verdict about the old.
        """
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha: [run("CI")])
        monkeypatch.setattr(watch_ci, "moved", lambda sha, pr, branch: "def")
        assert watch_ci.watch("abc", interval=0, timeout=9999, once=False, pr=538) == 2
        out = capsys.readouterr().out
        assert "the ref moved to def" in out
        assert "green" not in out


class TestReport:
    """What gets printed, since the report is the product.

    ``verdict`` counts a null conclusion against, which is correct for a finished run and
    wrong for one still going — so a report that ran it over an unsettled list called healthy
    in-flight jobs failures. These pin the two shapes apart.
    """

    def test_an_unsettled_report_gives_NO_verdict_and_calls_nothing_failed(self, capsys):
        """The `--once`-during-CI case, which printed `RED … failed: CI (no conclusion)`."""
        runs = [
            run("CI", status="in_progress", conclusion=None),
            run("Security", status="queued", conclusion=None),
        ]
        watch_ci._report("abc", runs, settled=False)
        out = capsys.readouterr().out
        assert "no verdict on abc" in out
        assert "2 of 2 still going" in out
        assert "RED" not in out
        assert "failed:" not in out

    def test_a_settled_green_report_says_green(self, capsys):
        """And names the sha, so a reader can check the attachment themselves."""
        watch_ci._report("abc", [run("CI"), run("apply", conclusion="skipped")], settled=True)
        out = capsys.readouterr().out
        assert "green on abc" in out
        assert "RED" not in out

    def test_a_settled_red_report_names_the_failure(self, capsys):
        """A count without a name sends the reader hunting."""
        watch_ci._report("abc", [run("CI", conclusion="failure")], settled=True)
        out = capsys.readouterr().out
        assert "RED on abc" in out
        assert "failed: CI (failure)" in out

    def test_once_during_running_ci_exits_2_without_claiming_red(self, monkeypatch, capsys):
        """End to end: the invocation the docs advertise, against healthy in-flight CI."""
        monkeypatch.setattr(
            watch_ci,
            "fetch_runs",
            lambda sha: [run("CI", status="in_progress", conclusion=None)],
        )
        assert watch_ci.watch("abc", interval=0, timeout=1, once=True) == 2
        assert "RED" not in capsys.readouterr().out


class TestFetchRuns:
    """The one place a silent cap could hide."""

    def test_a_second_page_of_runs_is_refused_not_silently_dropped(self, monkeypatch):
        """Judging the first hundred of more, and calling it the whole, is this file's own bug."""
        monkeypatch.setattr(
            watch_ci, "_gh", lambda *a: '{"total": 140, "runs": [{"name": "CI"}]}'
        )
        with pytest.raises(watch_ci.WatchError, match="fit one page"):
            watch_ci.fetch_runs("abc")

    def test_a_single_page_is_returned(self, monkeypatch):
        """The ordinary case still works."""
        monkeypatch.setattr(watch_ci, "_gh", lambda *a: '{"total": 1, "runs": [{"name": "CI"}]}')
        assert watch_ci.fetch_runs("abc") == [{"name": "CI"}]


class TestMainSelectors:
    """The CLI, which had its own way past the mutual-exclusion refusal."""

    def test_sha_with_pr_is_refused(self, monkeypatch, capsys):
        """`args.sha or resolve_sha(...)` short-circuited, so the refusal never ran.

        With all three passed, `moved` also self-disabled silently; with `--sha X --pr N`, a
        deliberately pinned commit got aborted as "the ref moved".
        """
        monkeypatch.setattr("sys.argv", ["watch_ci.py", "--sha", "abc", "--pr", "1"])
        assert watch_ci.main() == 2
        assert "Pass one of the three" in capsys.readouterr().err

    def test_an_unexpected_exception_exits_2_not_1(self, monkeypatch, capsys):
        """1 means "settled and red". A broken watch must not be readable as a failed build."""
        monkeypatch.setattr("sys.argv", ["watch_ci.py", "--sha", "abc"])

        def boom(*a, **k):
            raise RuntimeError("something else")

        monkeypatch.setattr(watch_ci, "watch", boom)
        assert watch_ci.main() == 2
        assert "the watch itself broke" in capsys.readouterr().err
