"""A pattern anchored with ``$`` is applied with ``fullmatch`` in every module the fleet deploys.

Python's ``$`` also matches immediately before a final newline, so
``re.compile(r"^[a-z]+$").match("alice\\n")`` succeeds. Every such pattern under ``lambdas/`` is a
whole-string validator — a catalog identifier, a UUID, a FIFO key, a column name — and all but one
were applied with ``match`` until a caller-chosen request id ending in a newline passed the FIFO
key check and SQS refused the send. The pattern strings stay as they are, because the docs quote
them; the call is what changes.

**What the sweep sees.** A name bound to ``re.compile`` of a literal (an f-string's literal parts
included) whose last character is an unescaped ``$``, applied through ``.match`` or ``.search`` —
by its own name in the module that binds it, by an imported name, or attribute-style
(``config.CATALOG_IDENTIFIER_RE.match``) anywhere; and a ``$``-ended literal passed straight to
``re.match`` or ``re.search``. A ``MULTILINE`` pattern is exempt, since there ``$`` means the end
of a line on purpose — recognised as a leading ``(?m)`` group, the only place Python accepts a
global flag, or as ``re.M``/``re.MULTILINE`` written into the call.

**What it cannot see.** It follows only the shapes above, so any other route from a pattern to its
application goes unseen: a pattern built at runtime or held in a string constant, a container or a
tuple unpack; an import under an alias; a method reference passed without being called, or a
chained ``re.compile(...).match``; a ``pattern=`` keyword; a verbose-mode pattern whose ``$`` is
followed by whitespace; a function-local rebinding, since bindings are read per module; and a
compiled pattern handed to a helper and applied under the helper's parameter name. None of these
occurs in the tree today. In the other direction, a ``MULTILINE`` flag passed through a variable is
not recognised, and that pattern is refused.
"""

import ast
import pathlib
import re

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent

_PARTIAL = frozenset({"match", "search"})
_GLOBAL_MULTILINE = re.compile(r"\(\?[a-zA-Z]*m[a-zA-Z]*\)")


def _production_sources():
    """Reads every module under ``lambdas/`` that is not test scaffolding.

    That is the deployed fleet plus the few repo-reading helpers beside it, which the sweep reads
    as well rather than carving out.

    Args:
      None.

    Returns:
      A mapping of each path, relative to ``lambdas/``, to its source.

    Raises:
      None.
    """
    return {
        str(path.relative_to(LAMBDAS)): path.read_text()
        for path in sorted(LAMBDAS.rglob("*.py"))
        if not path.name.startswith("test_") and path.name not in {"conftest.py", "fakes.py"}
    }


def _literal(node):
    """Reads the text of a pattern literal, so its last character can be judged.

    Args:
      node: The expression passed as the pattern.

    Returns:
      The string, or an f-string's literal parts joined when the f-string ends in one; None for
      anything built at runtime, including an f-string whose last part is an interpolation.

    Raises:
      None.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[-1], ast.Constant):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return None


def _anchored_at_end(call):
    """Whether a ``re`` call's pattern ends in a ``$`` anchor that is not a line anchor.

    Args:
      call: A ``re.compile``, ``re.match`` or ``re.search`` call.

    Returns:
      True when its first argument is a literal whose last character is a ``$`` preceded by an
      even run of backslashes, and neither a leading ``(?m)`` group nor a ``MULTILINE`` flag
      applies.

    Raises:
      None.
    """
    text = _literal(call.args[0]) if call.args else None
    if text is None or not text.endswith("$"):
        return False
    head = text[:-1]
    if (len(head) - len(head.rstrip("\\"))) % 2:
        return False
    if _GLOBAL_MULTILINE.match(text):
        return False
    flags = [*call.args[1:], *(k.value for k in call.keywords if k.arg == "flags")]
    return not any(
        isinstance(n, ast.Attribute) and n.attr in {"M", "MULTILINE"}
        for flag in flags
        for n in ast.walk(flag)
    )


def _re_call(node, names):
    """Whether a node calls one of the ``re`` module's functions directly.

    Args:
      node: Any AST node.
      names: The function names to accept.

    Returns:
      True for ``re.<name>(...)`` with ``<name>`` in ``names``.

    Raises:
      None.
    """
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in names
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
    )


def _bindings(tree):
    """Collects the names one module binds to a compiled pattern, and whether each is anchored.

    Args:
      tree: The module's AST.

    Returns:
      A mapping of each bound name — a plain name, or an attribute's own name — to True when the
      pattern it compiles ends in a ``$`` anchor.

    Raises:
      None.
    """
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not _re_call(value, {"compile"}):
            continue
        for target in targets:
            name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", None)
            if name:
                bound[name] = _anchored_at_end(value)
    return bound


def _scan(sources):
    """Finds every application of a ``$``-anchored pattern, and names the method each one uses.

    A plain name resolves against the binding in its own module first, which is Python's own
    scoping; failing that, and for every attribute-style receiver, it resolves against the names
    bound to an anchored pattern anywhere in the population. The two differ on purpose: a plain
    name's binding is fixed by its module, but an attribute's object can come from anywhere, so a
    name two modules bind differently is refused rather than missed.

    Args:
      sources: A mapping of each module's path to its source.

    Returns:
      The set of names bound to an anchored pattern, and one ``(path:line, receiver, method,
      shape)`` row per application, where ``shape`` is ``name``, ``attribute`` or ``re``.

    Raises:
      SyntaxError: If a module does not parse, so an unreadable file fails the sweep rather than
        leaving it.
    """
    trees = {path: ast.parse(source) for path, source in sources.items()}
    local = {path: _bindings(tree) for path, tree in trees.items()}
    anchored = {name for bound in local.values() for name, is_anchored in bound.items() if is_anchored}
    rows = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if _re_call(node, _PARTIAL) and _anchored_at_end(node):
                rows.append((f"{path}:{node.lineno}", "re", node.func.attr, "re"))
                continue
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _PARTIAL | {"fullmatch"}
            ):
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name):
                name, shape = receiver.id, "name"
                hit = local[path].get(name, name in anchored)
            elif isinstance(receiver, ast.Attribute):
                name, shape = receiver.attr, "attribute"
                hit = name in anchored
            else:
                continue
            if hit:
                rows.append((f"{path}:{node.lineno}", name, node.func.attr, shape))
    return anchored, rows


def _refused(sources):
    """Lists the applications the sweep refuses, in the form its failure message prints.

    Args:
      sources: A mapping of each module's path to its source.

    Returns:
      One ``path:line receiver.method`` string per ``match`` or ``search`` of an anchored pattern.

    Raises:
      SyntaxError: If a module does not parse.
    """
    _, rows = _scan(sources)
    return [f"{where} {name}.{method}" for where, name, method, _ in rows if method in _PARTIAL]


_CFG = 'import re\nX = re.compile(r"^[a-z]+$")\n'


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="match-on-a-dollar-pattern-is-refused",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$")\ndef f(v):\n    return X.search(v)\n'},
            ["a.py:4 X.search"],
            id="search-on-a-dollar-pattern-is-refused",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$")\ndef f(v):\n    return X.fullmatch(v)\n'},
            [],
            id="fullmatch-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+\\Z")\ndef f(v):\n    return X.match(v)\n'},
            [],
            id="a-backslash-z-anchor-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^cost\\$")\ndef f(v):\n    return X.match(v)\n'},
            [],
            id="an-escaped-dollar-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^a\\\\$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="an-escaped-backslash-before-the-anchor-is-refused",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"(?m)^[a-z]+$")\ndef f(v):\n    return X.search(v)\n'},
            [],
            id="an-inline-multiline-pattern-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$", re.MULTILINE)\ndef f(v):\n    return X.search(v)\n'},
            [],
            id="a-multiline-flag-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$", re.M)\ndef f(v):\n    return X.search(v)\n'},
            [],
            id="the-short-multiline-flag-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[a-z]+$", flags=re.M)\ndef f(v):\n    return X.search(v)\n'},
            [],
            id="a-multiline-flags-keyword-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^\\(?mobile\\)?$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="an-escaped-paren-before-m-is-not-a-multiline-flag",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"(?m:^[a-z]+)$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="a-scoped-multiline-group-leaves-the-final-anchor-alone",
        ),
        pytest.param(
            {"a.py": 'import re\nX = re.compile(r"^[(?m)]+$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="a-flag-shaped-class-past-the-start-is-not-a-flag",
        ),
        pytest.param(
            {"a.py": 'import other\nX = other.compile(r"^[a-z]+$")\ndef f(v):\n    return X.match(v)\n'},
            [],
            id="a-compile-that-is-not-re-is-silent",
        ),
        pytest.param(
            {"a.py": 'import re\nN = 5\nX = re.compile(rf"^[a-z]{{1,{N}}}$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:5 X.match"],
            id="an-f-string-pattern-is-read",
        ),
        pytest.param(
            {"a.py": 'import re\nX: re.Pattern[str] = re.compile(r"^[a-z]+$")\ndef f(v):\n    return X.match(v)\n'},
            ["a.py:4 X.match"],
            id="an-annotated-binding-is-read",
        ),
        pytest.param(
            {
                "a.py": "import re\nclass C:\n    def __init__(self):\n"
                '        self.x = re.compile(r"^[a-z]+$")\n'
                "    def f(self, v):\n        return self.x.match(v)\n"
            },
            ["a.py:6 x.match"],
            id="a-pattern-bound-to-an-attribute-is-read",
        ),
        pytest.param(
            {"cfg.py": _CFG, "use.py": "import cfg\ndef f(v):\n    return cfg.X.match(v)\n"},
            ["use.py:3 X.match"],
            id="an-attribute-style-receiver-is-resolved",
        ),
        pytest.param(
            {"cfg.py": _CFG, "use.py": "from cfg import X\ndef f(v):\n    return X.match(v)\n"},
            ["use.py:3 X.match"],
            id="an-imported-name-is-resolved",
        ),
        pytest.param(
            {
                "cfg.py": _CFG,
                "use.py": 'import re\nX = re.compile(r"^[a-z]+")\ndef f(v):\n    return X.match(v)\n',
            },
            [],
            id="a-local-binding-shadows-a-foreign-one",
        ),
        pytest.param(
            {"a.py": 'import re\ndef f(v):\n    return re.match(r"^[a-z]+$", v)\n'},
            ["a.py:3 re.match"],
            id="a-direct-re-call-is-refused",
        ),
    ],
)
def test_the_sweep_refuses_a_partial_match_and_nothing_else(sources, expected):
    """Each check the sweep makes, fired and held silent on a module written for it."""
    assert _refused(sources) == expected


def test_no_deployed_module_applies_a_dollar_anchored_pattern_partially():
    """The sweep over the fleet, with a positive control that it read the tree it was pointed at.

    An empty result is also what a collector that found nothing returns, so the control asserts the
    sweep resolved a known pattern through each receiver shape before the refusal list means
    anything. The control ignores which method was used, so a regression at one of its own sites
    is reported by the refusal list naming it rather than by the control.
    """
    sources = _production_sources()
    anchored, rows = _scan(sources)
    shapes = {(name, shape) for _, name, _, shape in rows}

    assert {"CATALOG_IDENTIFIER_RE", "COLUMN_NAME_RE", "FIFO_KEY_RE"} <= anchored
    assert ("FIFO_KEY_RE", "name") in shapes
    assert ("CATALOG_IDENTIFIER_RE", "attribute") in shapes
    assert _refused(sources) == []
