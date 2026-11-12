"""Every notice sent inside a loop shares one budget, and that budget fits the verb's timeout.

A send made without a budget gets one of its own and holds its verb for one cap, which is right
for a lone send. In a loop it is a cap per iteration, and a stalled queue then holds the verb a
cap per recipient, which at ``apicommon.bounds.MAX_MEMBERS_PER_REQUEST`` members is past
add-members' timeout, and past any timeout for a delete, whose roster is unbounded. A timeout there lands in the failure
path of a run whose work had committed and whose first recipients had been told. So this reads
every ``emit_*`` call under ``lambdas/`` that sits inside a loop and refuses one that does not pass
``budget=`` a budget made outside the call, then holds each such verb's worst case — the send
deadline plus one cap — to half the timeout Terraform deploys it with, the rule the other
budgets in the fleet follow.

**What it cannot see.** A loop that calls a helper which sends, rather than an ``emit_*`` itself,
is invisible here; the DLQ drain is one, and its send is deliberately not capped at all. A
``budget=`` naming a variable the loop assigns, or iterates over, is refused as a budget per
iteration; one rebound by a helper the loop calls is not seen, and a name bound outside the loop
is trusted whatever it holds, ``sends = None`` included.

Attributes:
  LAMBDAS: The tree the sweep reads.
  INFRA: The Terraform tree the timeouts are read from: each plane's root file and the
    control-plane module that declares its verbs.
  LOOP_OWNERS: Each production file with a notice loop, mapped to the control plane and the
    verb whose invocation runs it.
  EXEMPT: ``(file, function) -> reason`` for a loop allowed to send without a shared budget.
"""

import ast
import pathlib
import re

import pytest
from cpcommon import budget, notify
from tf_blocks import (
    argument,
    lambda_declaration,
    lambda_input,
    map_entries,
    module_calls,
    span,
    strip_comments,
    strip_noise,
)

LAMBDAS = pathlib.Path(__file__).resolve().parent
INFRA = LAMBDAS.parent / "infra"

LOOP_OWNERS = {
    "shared-space-add-members/add_members.py": ("shared-spaces", "add-members"),
    "shared-space-delete/delete_space.py": ("shared-spaces", "delete"),
    "shared-space-remove-members/remove_members.py": ("shared-spaces", "remove-members"),
    "file-send-notify/file_send_notify.py": ("file-send", "notify"),
    "table-share-collect-transfer-results/table_share_collect_transfer_results.py": (
        "table-share",
        "collect-transfer-results",
    ),
}

EXEMPT: dict[tuple[str, str], str] = {}

_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _callee(call: ast.Call) -> str:
    """Returns the name a call is made by, bare or as a module attribute.

    Args:
      call: The call.

    Returns:
      The name, or an empty string for a call through anything else.

    Raises:
      None.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _shares_a_budget(call: ast.Call, rebound: set[str]) -> bool:
    """Reports whether a send passes a budget made outside the loop it sits in.

    Args:
      call: A send.
      rebound: What the loop assigns or iterates over, each spelled as ``ast.unparse`` spells it.

    Returns:
      True for ``budget=`` a name or an attribute the loop does not rebind. A literal None is no
      budget, and a call such as ``budget=send_budget()``, or a variable the loop assigns, is a
      fresh one per iteration, which shares nothing.

    Raises:
      None.
    """
    return any(
        k.arg == "budget"
        and isinstance(k.value, (ast.Name, ast.Attribute))
        and ast.unparse(k.value) not in rebound
        for k in call.keywords
    )


def _rebound(node: ast.AST) -> set[str]:
    """Returns every name and attribute a loop binds once per iteration.

    Args:
      node: A loop or a comprehension.

    Returns:
      Its targets and every assignment inside the parts that run once per iteration, each spelled
      as ``ast.unparse`` spells it.

    Raises:
      None.
    """
    targets = [g.target for g in node.generators] if isinstance(node, _COMPREHENSIONS) else []
    if isinstance(node, (ast.For, ast.AsyncFor)):
        targets.append(node.target)
    stores = [
        n
        for part in [*targets, *_looped(node)]
        for n in ast.walk(part)
        if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, ast.Store)
    ]
    return {ast.unparse(n) for n in stores}


def _looped(node: ast.AST) -> list[ast.AST]:
    """Returns the parts of a loop or comprehension that run once per iteration.

    Args:
      node: A loop or a comprehension.

    Returns:
      The loop's body and ``else`` statements, or the comprehension's element and conditions.

    Raises:
      None.
    """
    if isinstance(node, _LOOPS):
        return [*node.body, *node.orelse]
    parts: list[ast.AST] = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    return parts + [condition for generator in node.generators for condition in generator.ifs]


def loop_sends(source: str) -> list[tuple[str, str, bool]]:
    """Finds every ``emit_*`` call that runs once per iteration of a loop.

    Args:
      source: A module's text.

    Returns:
      ``(enclosing function, callee, shares a budget)`` per call, in source order, each call
      once however many loops enclose it, and sharing only if no loop around it rebinds the
      budget it passes.

    Raises:
      SyntaxError: If the module does not parse.
    """
    tree = ast.parse(source)
    enclosing: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                enclosing.setdefault(child, fn.name) if child is not fn else None
    found: dict[ast.Call, tuple[str, str, bool]] = {}
    for loop in ast.walk(tree):
        if not isinstance(loop, _LOOPS + _COMPREHENSIONS):
            continue
        rebound = _rebound(loop)
        for part in _looped(loop):
            for call in ast.walk(part):
                if isinstance(call, ast.Call) and _callee(call).startswith("emit_"):
                    shared = _shares_a_budget(call, rebound) and found.get(call, ("", "", True))[2]
                    found[call] = (enclosing.get(call, "<module>"), _callee(call), shared)
    return [found[call] for call in sorted(found, key=lambda c: (c.lineno, c.col_offset))]


def _production_files():
    """Every production module under ``lambdas/``.

    Args:
      None.

    Returns:
      Each module's path, tests, conftests and test fakes left out.

    Raises:
      None.
    """
    return sorted(
        path
        for path in LAMBDAS.rglob("*.py")
        if "__pycache__" not in path.parts
        and not path.name.startswith("test_")
        and path.name not in ("conftest.py", "fakes.py")
    )


def _local_map(text: str, name: str) -> dict[str, str]:
    """The entries of one map assigned in a plane's ``locals``.

    Args:
      text: The plane's root file, ``infra/plane-<plane>.tf``.
      name: The local's name.

    Returns:
      Each key mapped to its entry text.

    Raises:
      AssertionError: If no such map is assigned, so a renamed local reddens rather than reading
        as a map with nothing in it.
    """
    found = re.search(rf"(?m)^[ \t]*{re.escape(name)}[ \t]*=[ \t]*\{{", strip_noise(text))
    assert found, f"no `{name} = {{…}}` in the plane's root file"
    return map_entries(span(text, found.end() - 1))


def deployed_timeout(plane: str, verb: str) -> int:
    """Reads one verb's Lambda timeout the way the control-plane module's declaration computes it.

    The plane's root file passes a local map as the module call's ``functions``, and the module
    iterates that map and deploys each entry's own ``timeout``. Both links are read rather than
    assumed, and the verb is first required to be one the map deploys at all, so a misspelt name
    reddens instead of reading some other entry.

    Args:
      plane: The plane's name, as in ``infra/plane-<plane>.tf``.
      verb: The verb's key in the plane's function map.

    Returns:
      The timeout in seconds.

    Raises:
      AssertionError: If the verb is not deployed, or the declaration computes its timeout in a
        way this does not read.
    """
    root = (INFRA / f"plane-{plane}.tf").read_text()
    calls = [
        body for body in module_calls(root).values() if argument(body, "source") == '"./modules/control-plane"'
    ]
    assert len(calls) == 1, f"plane-{plane}.tf makes {len(calls)} control-plane calls, not one"
    functions = re.fullmatch(r"local\.(\w+)", argument(calls[0], "functions"))
    assert functions, "the plane's call no longer passes a local map as its functions"
    entries = _local_map(root, functions.group(1))
    assert verb in entries, f"{plane} deploys no {verb!r} verb"
    declaration = lambda_declaration((INFRA / "modules" / "control-plane" / "lambda.tf").read_text(), "functions")
    assert argument(declaration, "for_each") == "var.functions", "the module no longer iterates its functions"
    expression = lambda_input(declaration, "timeout")
    assert expression == "each.value.timeout", f"the module computes a timeout as {expression!r}, which this does not read"
    return int(re.search(r"\btimeout\s*=\s*(\d+)", strip_comments(entries[verb])).group(1))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "def f(us):\n    for u in us:\n        emit_notification(u, 'm')\n",
            [("f", "emit_notification", False)],
            id="a-for-loop-send-without-a-budget",
        ),
        pytest.param(
            "def f(us):\n    s = send_budget()\n    for u in us:\n        emit_notification(u, 'm', budget=s)\n",
            [("f", "emit_notification", True)],
            id="a-for-loop-send-sharing-one",
        ),
        pytest.param(
            "def f(us):\n    for u in us:\n        emit_notification(u, 'm', budget=send_budget())\n",
            [("f", "emit_notification", False)],
            id="a-budget-made-per-iteration",
        ),
        pytest.param(
            "def f(us):\n    for u in us:\n        emit_notification(u, 'm', budget=None)\n",
            [("f", "emit_notification", False)],
            id="a-literal-none",
        ),
        pytest.param(
            "def f(us):\n    for u in us:\n        s = send_budget()\n        emit_x(u, budget=s)\n",
            [("f", "emit_x", False)],
            id="a-budget-assigned-inside-the-loop",
        ),
        pytest.param(
            "def f(u, budgets):\n    for s in budgets:\n        emit_x(u, budget=s)\n",
            [("f", "emit_x", False)],
            id="a-budget-the-loop-iterates-over",
        ),
        pytest.param(
            "def f(xs):\n    for a in xs:\n        s = send_budget()\n        for b in a:\n            emit_x(b, budget=s)\n",
            [("f", "emit_x", False)],
            id="a-budget-an-outer-loop-rebinds",
        ),
        pytest.param(
            "def f(self, us):\n    for u in us:\n        self.s = send_budget()\n        emit_x(u, budget=self.s)\n",
            [("f", "emit_x", False)],
            id="an-attribute-the-loop-assigns",
        ),
        pytest.param(
            "def f(q):\n    while q:\n        notify.emit_recipient_failure(q.pop())\n",
            [("f", "emit_recipient_failure", False)],
            id="a-while-loop-attribute-call",
        ),
        pytest.param(
            "def f(us, s):\n    return [emit_x(u, budget=s.sends) for u in us if emit_y(u)]\n",
            [("f", "emit_x", True), ("f", "emit_y", False)],
            id="a-comprehension-element-and-condition",
        ),
        pytest.param(
            "def f(us, s):\n    for a in us:\n        for b in a:\n            emit_x(b, budget=s)\n",
            [("f", "emit_x", True)],
            id="nested-loops-count-a-call-once",
        ),
        pytest.param(
            "def f(u):\n    emit_notification(u, 'm')\n    for x in range(3):\n        log(x)\n",
            [],
            id="a-send-outside-the-loop-is-silent",
        ),
        pytest.param(
            "def f(us):\n    '''for u in us: emit_notification(u)'''\n    for u in us:\n        emitter(u)\n",
            [],
            id="a-docstring-and-a-non-emit-name-are-silent",
        ),
        pytest.param(
            "for u in us:\n    emit_notification(u, 'm')\n",
            [("<module>", "emit_notification", False)],
            id="a-module-level-loop",
        ),
    ],
)
def test_the_sweep_finds_the_sends_a_loop_makes_and_whether_they_share_a_budget(source, expected):
    assert loop_sends(source) == expected


def test_every_notice_sent_in_a_loop_shares_one_budget():
    unshared = [
        (str(path.relative_to(LAMBDAS)), function, callee)
        for path in _production_files()
        for function, callee, shared in loop_sends(path.read_text())
        if not shared and (str(path.relative_to(LAMBDAS)), function) not in EXEMPT
    ]

    assert unshared == [], "a notice sent in a loop without the loop's budget, from send_budget()"


def test_every_notice_loop_names_the_verb_whose_timeout_bounds_it():
    """Set equality, so a new loop has to be mapped to its verb and a removed one leaves the map."""
    loops = {
        str(path.relative_to(LAMBDAS)) for path in _production_files() if loop_sends(path.read_text())
    }

    assert loops == set(LOOP_OWNERS)


@pytest.mark.parametrize(("plane", "verb"), sorted(set(LOOP_OWNERS.values())))
def test_a_loops_notices_leave_half_of_its_verbs_timeout(plane, verb):
    """The notices run after the verb's real work, and a budget holds them to its deadline plus
    one call started just before it, however many there are; the other half is the work's."""
    worst = notify.SEND_DEADLINE_SECONDS + budget.CALL_CAP_SECONDS
    timeout = deployed_timeout(plane, verb)

    assert worst <= timeout / 2, f"a loop's notices can take {worst}s inside {verb}, whose timeout is {timeout}s"


@pytest.mark.parametrize(
    ("plane", "verb", "timeout"),
    [("shared-spaces", "add-members", 60), ("shared-spaces", "backfill-ever-active", 900), ("file-send", "notify", 60)],
    ids=["a-shared-space-verb", "the-long-shared-space-entry", "a-file-send-verb"],
)
def test_the_timeout_reader_follows_the_declaration(plane, verb, timeout):
    """Positive controls on two planes, one entry far from its neighbours. These restate numbers on
    purpose: the reader is what is under test here, and the comparison above never restates one."""
    assert deployed_timeout(plane, verb) == timeout


def test_the_timeout_reader_refuses_a_verb_the_module_does_not_deploy():
    """Without this a misspelt verb could read some other entry's number and pass."""
    with pytest.raises(AssertionError, match="deploys no 'add-member' verb"):
        deployed_timeout("shared-spaces", "add-member")
