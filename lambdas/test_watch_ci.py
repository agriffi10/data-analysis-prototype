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


class TestWatchExitStatus:
    """The exit status, since the point is to compose with `&&`."""

    def test_settled_and_green_exits_zero(self, monkeypatch):
        """The only path to 0."""
        monkeypatch.setattr(watch_ci, "fetch_runs", lambda sha: [run("CI")])
        assert watch_ci.watch("abc", interval=0, timeout=1, once=False) == 0


    def test_once_with_unfinished_runs_exits_non_zero(self, monkeypatch):
        """`--once` reports what is there and must not call in-progress a pass."""
        monkeypatch.setattr(
            watch_ci, "fetch_runs", lambda sha: [run("CI", status="in_progress", conclusion=None)]
        )
        assert watch_ci.watch("abc", interval=0, timeout=1, once=True) == 2


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
