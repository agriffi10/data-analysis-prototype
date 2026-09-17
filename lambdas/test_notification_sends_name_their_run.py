"""Every notification a Lambda sends names its run, by a dedup id or a payload, or is listed here.

The notifications queue deduplicates a send with no dedup id on its body alone. A body naming
nothing about the run is byte-identical for two runs that end alike, and the queue delivers one.
That shipped several times, each found late and fixed one plane at a time: archive's success
notices, file-operations' failures, archive's and file-send's failures and file-send's successes,
then every table-share notice. So this reads every
call to ``emit_notification`` under ``lambdas/`` and refuses one that passes neither ``dedup_id``
nor ``payload``.

**What it cannot see.** A name passed as a value that is None at run time, such as
``dedup_id(event.get("requestId"), step)`` on an event with no id, satisfies it. It refuses the
send that forgot to name the run at all, which is how every instance so far was written.

**The exemptions are counted per function**, so a second unnamed send added beside a listed one
reddens, and one that is fixed must leave the list in the same change or the list goes stale. The
list is empty: a send that genuinely cannot name its run is added here with its reason, never
passed a placeholder name to get past the sweep.

Attributes:
  LAMBDAS: The tree the sweep reads.
  NAMING_KEYWORDS: The ``emit_notification`` parameters that name a run.
  NAMING_POSITIONS: Where each of them sits positionally, read from the sender's own signature so
    a reordered parameter moves the sweep with it.
  EXEMPT: ``(file, function) -> (count, reason)`` for the sends allowed to name no run.
"""

import ast
import collections
import inspect
import pathlib
import sys

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LAMBDAS / "control-plane-common"))

from cpcommon import notify

NAMING_KEYWORDS = frozenset({"dedup_id", "payload"})
NAMING_POSITIONS = frozenset(
    index
    for index, name in enumerate(inspect.signature(notify.emit_notification).parameters)
    if name in NAMING_KEYWORDS
)

EXEMPT: dict[tuple[str, str], tuple[int, str]] = {}


def _sender_names(tree: ast.Module) -> set:
    """Returns every bare name a module can call the sender by.

    Args:
      tree: The parsed module.

    Returns:
      ``emit_notification``, and any name it was imported as.

    Raises:
      None.
    """
    names = {"emit_notification"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname for a in node.names if a.name == "emit_notification" and a.asname)
    return names


def _is_send(call: ast.Call, names: set) -> bool:
    """Reports whether a call reaches the sender, bare, aliased or through a module attribute.

    Args:
      call: The call.
      names: The bare names the module can call the sender by.

    Returns:
      True for ``emit_notification(…)``, an alias of it, or ``anything.emit_notification(…)``.

    Raises:
      None.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in names
    return isinstance(func, ast.Attribute) and func.attr == "emit_notification"


def _names_its_run(call: ast.Call) -> bool:
    """Reports whether a send passes something that names its run.

    A literal None names nothing and does not count; a ``**`` splat cannot be read and does not
    count either, so it is refused rather than trusted.

    Args:
      call: A call to the sender.

    Returns:
      True when a dedup id or a payload is passed by keyword or by position.

    Raises:
      None.
    """
    def named(value: ast.expr) -> bool:
        """Reports whether an argument is anything but a literal None.

        Args:
          value: The argument.

        Returns:
          True unless it is the constant None.

        Raises:
          None.
        """
        return not (isinstance(value, ast.Constant) and value.value is None)

    if any(named(a) for i, a in enumerate(call.args) if i in NAMING_POSITIONS):
        return True
    return any(k.arg in NAMING_KEYWORDS and named(k.value) for k in call.keywords)


def sends(source: str) -> list:
    """Finds every send in a module, with the function it is in and whether it names its run.

    Args:
      source: The module's text.

    Returns:
      ``(qualified function name, names its run)`` per send, ``<module>`` outside any function.

    Raises:
      SyntaxError: When the source does not parse, which the sweep should not swallow.
    """
    tree = ast.parse(source)
    names = _sender_names(tree)
    found = []

    def visit(node: ast.AST, scope: str) -> None:
        """Walks one scope, entering nested functions and classes under their own names.

        Args:
          node: The node whose children are walked.
          scope: The qualified name of the enclosing function, or empty at module level.

        Returns:
          None.

        Raises:
          None.
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, f"{scope}.{child.name}" if scope else child.name)
                continue
            if isinstance(child, ast.Call) and _is_send(child, names):
                found.append((scope or "<module>", _names_its_run(child)))
            visit(child, scope)

    visit(tree, "")
    return found


def _fleet_sends(root: pathlib.Path = LAMBDAS) -> list:
    """Reads every production module under ``lambdas/``.

    Args:
      root: The tree to read, which is ``lambdas/`` everywhere but this file's own corpus.

    Returns:
      ``(relative file, function, names its run)`` per send. Test modules are excluded: they call
      stubs of the sender, not the sender.

    Raises:
      None.
    """
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("test_") or path.name.endswith("_test.py") or path.name == "conftest.py":
            continue
        relative = path.relative_to(root).as_posix()
        found.extend((relative, scope, named) for scope, named in sends(path.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f(u, m):\n    emit_notification(u, m)\n", [("f", False)]),
        ("def f(u, m):\n    notify.emit_notification(u, m)\n", [("f", False)]),
        (
            "from cpcommon.notify import emit_notification as send\ndef f(u, m):\n    send(u, m)\n",
            [("f", False)],
        ),
        ("def f(u, m, e):\n    emit_notification(u, m, payload=request_payload(e))\n", [("f", True)]),
        ("def f(u, m, r):\n    emit_notification(u, m, dedup_id=dedup_id(r, 'x'))\n", [("f", True)]),
        ("def f(u, m):\n    emit_notification(u, m, dedup_id=None, link='/files')\n", [("f", False)]),
        ("def f(u, m, d):\n    emit_notification(u, m, d)\n", [("f", True)]),
        ("def f(u, m):\n    emit_notification(u, m, None, '/files', None)\n", [("f", False)]),
        ("def f(u, m, p):\n    emit_notification(u, m, None, None, p)\n", [("f", True)]),
        ("def f(u, m, k):\n    emit_notification(u, m, **k)\n", [("f", False)]),
        ("class C:\n    def g(self):\n        def h():\n            emit_notification('u', 'm')\n", [("C.g.h", False)]),
        ("emit_notification('u', 'm')\n", [("<module>", False)]),
        ("def emit_notification(u, m, dedup_id=None):\n    send_message(u, m)\n", []),
        ("def f(u, m):\n    emit(u, m)\n    notify.emit_notifications(u, m)\n", []),
    ],
    ids=[
        "a bare send naming nothing is refused",
        "a send through a module attribute is read",
        "a send through an import alias is read",
        "a payload names the run",
        "a dedup id names the run",
        "a literal None names nothing",
        "a dedup id passed by position names the run",
        "a link passed by position names nothing",
        "a payload passed by position names the run",
        "a splat cannot be read and is refused",
        "a nested send is attributed to its innermost function",
        "a module-level send is attributed to the module",
        "the sender's own definition is not a send",
        "a neighbouring name is not the sender",
    ],
)
def test_the_sweep_reads_a_send_the_way_the_sender_does(source, expected) -> None:
    """The fixture corpus: each way of reaching the sender, and each way of naming a run or not.

    Args:
      source: A module.
      expected: What the sweep should report for it.

    Returns:
      None.

    Raises:
      AssertionError: If the sweep misreads the case.
    """
    assert sends(source) == expected


def test_the_sweep_still_reads_the_fleet() -> None:
    """Guard the guard: a sweep that finds no sends, or reads a named send as unnamed, proves nothing.

    Named sends from a bare call and from a module attribute must be among what it finds, or a path
    or resolution change has emptied the population under it. No production send is unnamed any
    more, so the unnamed reading is proved by the fixture corpus above rather than by the fleet.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a known send is missing from the population.
    """
    found = _fleet_sends()

    assert ("archive-common/arcommon/notify.py", "emit_failure", True) in found
    assert ("archive-notify-failure/ar_notify_failure.py", "handler", True) in found
    assert found.count(("table-share-common/tscommon/notify.py", "emit_recipient_success", True)) == 3
    assert ("table-share-notify-failure/ts_notify_failure.py", "_on_execution_timed_out", True) in found


def _verdict(found: list, exempt: dict) -> tuple[dict, dict]:
    """Compares the unnamed sends with the exemptions, in both directions.

    Args:
      found: ``(file, function, names its run)`` per send.
      exempt: ``(file, function) -> (count, reason)``.

    Returns:
      ``(new, stale)``: the sites with more unnamed sends than they are allowed, with their counts,
      and the exemptions with fewer unnamed sends than they allow, with the count they allow.

    Raises:
      None.
    """
    unnamed = collections.Counter((file, scope) for file, scope, named in found if not named)
    allowed = {site: count for site, (count, _reason) in exempt.items()}
    new = {site: count for site, count in unnamed.items() if count > allowed.get(site, 0)}
    stale = {site: count for site, count in allowed.items() if unnamed.get(site, 0) < count}
    return new, stale


_SITE = ("plane/notify.py", "emit")


@pytest.mark.parametrize(
    ("found", "exempt", "expected"),
    [
        ([(*_SITE, False)], {}, ({_SITE: 1}, {})),
        ([(*_SITE, True)], {}, ({}, {})),
        ([(*_SITE, False)], {_SITE: (1, "why")}, ({}, {})),
        ([(*_SITE, False), (*_SITE, False)], {_SITE: (1, "why")}, ({_SITE: 2}, {})),
        ([(*_SITE, False)], {_SITE: (2, "why")}, ({}, {_SITE: 2})),
        ([(*_SITE, True)], {_SITE: (1, "why")}, ({}, {_SITE: 1})),
    ],
    ids=[
        "an unnamed send with no exemption is new",
        "a named send needs no exemption",
        "an unnamed send its exemption allows is neither",
        "a second unnamed send beside an exempt one is new",
        "an exemption allowing more than remain is stale",
        "an exemption for a send that now names its run is stale",
    ],
)
def test_the_verdict_refuses_a_new_unnamed_send_and_a_stale_exemption(found, exempt, expected) -> None:
    """The comparison's corpus, because with the fleet's exemption list empty it is otherwise unexercised.

    Args:
      found: The sends.
      exempt: The exemptions.
      expected: ``(new, stale)``.

    Returns:
      None.

    Raises:
      AssertionError: If the comparison misjudges a case.
    """
    assert _verdict(found, exempt) == expected


def test_the_fleet_reader_reports_an_unnamed_send_and_skips_test_modules(tmp_path) -> None:
    """Guard the guard's reader: the fleet has no unnamed send left to prove it still reports one.

    Args:
      tmp_path: The pytest fixture.

    Returns:
      None.

    Raises:
      AssertionError: If the reader drops an unnamed send, reads a named one as unnamed, or reads a
        test module.
    """
    plane = tmp_path / "plane"
    plane.mkdir()
    (plane / "notify.py").write_text(
        "def emit(u, m):\n    emit_notification(u, m)\n"
        "def named(u, m, r):\n    emit_notification(u, m, dedup_id=r)\n"
    )
    for skipped in ("test_notify.py", "notify_test.py", "conftest.py"):
        (plane / skipped).write_text("def f(u, m):\n    emit_notification(u, m)\n")

    assert _fleet_sends(tmp_path) == [("plane/notify.py", "emit", False), ("plane/notify.py", "named", True)]


def test_every_send_names_its_run_or_is_exempt() -> None:
    """Unnamed sends match the exemptions exactly, in both directions.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a send names no run and is not exempt, or an exemption no longer applies.
    """
    new, stale = _verdict(_fleet_sends(), EXEMPT)
    assert not new, f"these sends name no run, so two runs ending alike collapse into one notice: {new}"
    assert not stale, f"these exemptions no longer match an unnamed send; remove or lower them: {stale}"
