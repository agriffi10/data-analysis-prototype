"""Every plane that raises a reason nobody is told keeps it quiet in its own ``emit_failure``.

The silent vocabulary and its predicate live in the shared layer, so a silent code validates in
every plane. Silence is still each emitter's to ask for, and one that does not ask renders the
resolver's fallback — "something went wrong" — beside the report of the run that holds the id. So
the planes are derived from where a silent code is named rather than listed, and a plane that
starts raising one is held to this before it deploys.
"""

import importlib
import pathlib
import sys

import pytest
from cpcommon import messages
from cpcommon.errors import TerminalError

_LAMBDAS = pathlib.Path(__file__).resolve().parent
_OWNER = "control-plane-common"
_KNOWN_RAISERS = {"arcommon", "dqcommon", "focommon"}


def _silent_spellings() -> set[str]:
    """Returns every way a silent code can be named in source: its value and its constant.

    Args:
      None.

    Returns:
      Each silent reason's value, and the name of every ``cpcommon.messages`` constant holding one.

    Raises:
      None.
    """
    names = {
        name
        for name, value in vars(messages).items()
        if isinstance(value, str) and value in messages.SILENT_REASONS
    }
    return set(messages.SILENT_REASONS) | names


def _common_dir_for(top: str) -> str | None:
    """Maps a directory under ``lambdas/`` to the shared-layer directory of its plane.

    Args:
      top: The first path segment under ``lambdas/``.

    Returns:
      The ``*-common`` directory whose plane the segment belongs to, or None when it belongs to
      none.

    Raises:
      None.
    """
    commons = sorted((p.name for p in _LAMBDAS.glob("*-common")), key=len, reverse=True)
    for common in commons:
        if top == common or top.startswith(common.removesuffix("common")):
            return common
    return None


def _raising_planes() -> dict[str, str]:
    """Finds every plane whose non-test source names a silent code.

    A mention in a docstring counts, which errs toward holding a plane to silence rather than
    missing one that raises the code.

    Args:
      None.

    Returns:
      Each plane's shared-layer directory mapped to the first file that named a silent code.

    Raises:
      AssertionError: When a file names a silent code outside any plane, which this test cannot
        hold to anything.
    """
    spellings = _silent_spellings()
    found: dict[str, str] = {}
    for path in sorted(_LAMBDAS.rglob("*.py")):
        rel = path.relative_to(_LAMBDAS)
        if path.name.startswith("test_") or rel.parts[0] == _OWNER or "__pycache__" in rel.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if not any(spelling in text for spelling in spellings):
            continue
        common = _common_dir_for(rel.parts[0])
        assert common is not None, f"{rel} names a silent reason but belongs to no plane"
        found.setdefault(common, str(rel))
    return found


def _emit_failure_of(common: str):
    """Imports a plane's ``notify`` module from its shared-layer package.

    Args:
      common: The plane's ``*-common`` directory.

    Returns:
      The imported module.

    Raises:
      AssertionError: When the directory holds no package with a ``notify.emit_failure``.
    """
    root = _LAMBDAS / common
    packages = [p.name for p in root.iterdir() if (p / "notify.py").is_file()]
    assert len(packages) == 1, f"{common} has no single package with a notify module: {packages}"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = importlib.import_module(f"{packages[0]}.notify")
    assert hasattr(module, "emit_failure"), f"{packages[0]}.notify has no emit_failure"
    return module


def test_the_derivation_finds_the_planes_known_to_raise_a_silent_reason():
    """A derivation that silently finds nothing would pass the test below over an empty set."""
    derived = {_emit_failure_of(common).__name__.split(".")[0] for common in _raising_planes()}

    assert derived >= _KNOWN_RAISERS


@pytest.mark.parametrize("common", sorted(_raising_planes()))
@pytest.mark.parametrize("reason", sorted(messages.SILENT_REASONS))
def test_a_silent_reason_sends_nothing_where_an_ordinary_refusal_is_told(
    common, reason, monkeypatch
):
    """The forbidden refusal after it is the positive control: the same event, through the same
    emitter, IS sent, so an empty result is the silence and not a patch that missed."""
    notify = _emit_failure_of(common)
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, *a, **kw: sent.append(user))
    event = {
        "requestId": "0f8fad5b-d9cb-469f-a165-70867728950e",
        "actor": {"username": "alice"},
        "mode": "archive",
        "operation": "copy",
    }

    notify.emit_failure(event, TerminalError(reason, "held by another execution"), "inspect")
    silent = list(sent)
    notify.emit_failure(event, TerminalError(messages.FORBIDDEN, "not a member"), "inspect")

    assert silent == []
    assert len(sent) == 1
