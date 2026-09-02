"""Every way `lambdas/fleet.py` refuses, exercised — and a sweep proving none was missed.

**The module's entire safety story is that it refuses rather than skips.** A declaration it cannot
resolve must raise, because a skipped one shrinks the fleet on both sides of every comparison built
on it and nothing anywhere disagrees. That story is worth exactly as much as its refusals are
reachable, and when this file was written every refusal in the module was unexercised — no test named one,
and the module's uncovered lines were precisely its guards.

Two things live here, and the second is what makes the first honest. The corpus drives each refusal
through a real fixture repository and asserts the REASON, never that "something raised" — every one
of these paths raises `FleetError`, so a test asserting the type alone passes when the wrong guard
fires. The sweep then traces which `raise` statements the corpus actually reached and fails on any
it did not, which is the project's "enumerate the codes raised against the codes asserted" rule
applied mechanically rather than by sampling.

Attributes:
  ROOT: The repository root.
  PREFIX: The deployed-name prefix every fixture template carries.
  CASES: Each refusal, as (id, the module files to write, the phrase the message must carry).
"""

import pathlib
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
import fleet

PREFIX = "${var.project_name}-${var.environment}-"


def _module(call: str = "functions", **arguments: str) -> str:
    """One `docker-lambda` module call, with the given arguments.

    Args:
      call: The module call's local name.
      **arguments: Terraform arguments, as written.

    Returns:
      The module block.

    Raises:
      None.
    """
    body = "\n".join(f"  {key.rstrip('_')} = {value}" for key, value in arguments.items())
    return f'module "{call}" {{\n  source = "../docker-lambda"\n{body}\n}}\n'


def _plane(*, locals_: str = "", calls: str) -> str:
    """One bounded-context module's Terraform.

    Args:
      locals_: The body of a `locals` block, or empty for none.
      calls: The module calls.

    Returns:
      The module's single `.tf` file.

    Raises:
      None.
    """
    block = f"locals {{\n{textwrap.indent(textwrap.dedent(locals_).strip(), '  ')}\n}}\n\n" if locals_ else ""
    return block + calls


#: A plane whose verbs resolve, used to lift a fixture over the thirty-function floor so that a
#: case testing some OTHER refusal cannot pass by tripping the floor instead.
def _filler(count: int) -> str:
    """A plane declaring `count` resolvable functions.

    Args:
      count: How many.

    Returns:
      The module's Terraform.

    Raises:
      None.
    """
    verbs = "\n".join(f'    "verb{n}" = 1' for n in range(count))
    return _plane(
        locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}filler-${{suffix}}"\n}}\n\nverbs = {{\n{verbs}\n  }}',
        calls=_module(for_each="local.verbs", function_name="local.names[each.key]"),
    )


CASES = [
    (
        "a local that is not declared",
        {"plane": _plane(calls=_module(function_name="local.missing_name"))},
        "no local named `missing_name`",
    ),
    (
        "a name template missing the project/environment prefix",
        {"plane": _plane(calls=_module(function_name='"lonely-function"'))},
        "does not start with",
    ),
    (
        "a function_name expression of an unknown shape",
        {"plane": _plane(calls=_module(function_name="try(local.a, local.b)"))},
        "cannot resolve",
    ),
    (
        "a name map that is not a comprehension",
        {"plane": _plane(locals_='names = { "a" = "x" }',
                         calls=_module(for_each="local.names", function_name="local.names[each.key]"))},
        'is not a `for … in local.<map> : k => "…"` map',
    ),
    (
        "a for_each that does not create the instances the names assume",
        {"plane": _plane(
            locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}p-${{suffix}}"\n}}\n\nverbs = {{\n    "a" = 1\n  }}',
            calls=_module(for_each="var.on ? local.verbs : {}", function_name="local.names[each.key]"))},
        "Only the instances `for_each` creates exist",
    ),
    (
        "a verb map with no verbs in it",
        {"plane": _plane(
            locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}p-${{suffix}}"\n}}\n\nverbs = {{\n  }}',
            calls=_module(for_each="local.verbs", function_name="local.names[each.key]"))},
        "names no verbs",
    ),
    (
        "a verb map key written unquoted",
        {"plane": _plane(
            locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}p-${{suffix}}"\n}}\n\nverbs = {{\n    "a" = 1\n    bare = 2\n  }}',
            calls=_module(for_each="local.verbs", function_name="local.names[each.key]"))},
        "as bare identifier key",
    ),
    (
        "an unquoted key sharing the opening brace's line",
        {"plane": _plane(
            locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}p-${{suffix}}"\n}}\n\nverbs = {{ bare = 2\n    "a" = 1\n  }}',
            calls=_module(for_each="local.verbs", function_name="local.names[each.key]"))},
        "as bare identifier key",
    ),
    (
        "a name template that never interpolates its loop variable",
        {"plane": _plane(
            locals_=f'names = {{\n  for suffix, _ in local.verbs :\n  suffix => "{PREFIX}p-fixed"\n}}\n\nverbs = {{\n    "a" = 1\n    "b" = 2\n  }}',
            calls=_module(for_each="local.verbs", function_name="local.names[each.key]"))},
        "does not interpolate",
    ),
    (
        "a name still carrying an unresolved reference",
        {"plane": _plane(locals_=f'n = "{PREFIX}${{local.slug}}-thing"',
                         calls=_module(function_name="local.n"))},
        "still carries an unresolved interpolation",
    ),
    (
        "two modules declaring one name",
        {"one": _plane(calls=_module(call="a", function_name=f'"{PREFIX}twin"')),
         "two": _plane(calls=_module(call="b", function_name=f'"{PREFIX}twin"'))},
        "both declare",
    ),
    (
        "a sweep that has stopped finding the fleet",
        {"plane": _plane(calls=_module(function_name=f'"{PREFIX}lonely"'))},
        "has stopped working",
    ),
]


def _repo(tmp_path: pathlib.Path, files: dict[str, str], *, pad: bool) -> pathlib.Path:
    """Builds a fixture repository holding the given modules.

    Args:
      tmp_path: The temporary directory.
      files: Module directory name mapped to its `.tf` source.
      pad: Whether to add a filler plane that lifts the fleet over the thirty-function floor.

    Returns:
      The repository root.

    Raises:
      None.
    """
    modules = tmp_path / "infra" / "modules"
    for name, source in files.items():
        (modules / name).mkdir(parents=True)
        (modules / name / "main.tf").write_text(source, encoding="utf-8")
    if pad:
        (modules / "zz-filler").mkdir(parents=True)
        (modules / "zz-filler" / "main.tf").write_text(_filler(40), encoding="utf-8")
    return tmp_path


def test_the_fixture_builder_produces_a_fleet_that_resolves(tmp_path: pathlib.Path) -> None:
    """The positive control, without which every refusal below could be the fixture's fault.

    A malformed fixture raises for a reason the case did not intend, and a corpus of refusals is
    the one place that is invisible — every case expects an exception, so a builder that produces
    unparseable Terraform makes every one of them pass for the wrong reason.

    Args:
      tmp_path: Pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: When the builder's own output does not resolve.
    """
    names = fleet.function_names(_repo(tmp_path, {}, pad=True))
    assert len(names) == 40, f"the filler plane resolved to {len(names)} functions, not 40"
    assert names[0] == "filler-verb0"


@pytest.mark.parametrize("label, files, phrase", CASES, ids=[case[0] for case in CASES])
def test_the_refusal_names_its_reason(
    tmp_path: pathlib.Path, label: str, files: dict[str, str], phrase: str
) -> None:
    """Each refusal fires, and says which one it is.

    Matched on the message rather than on the type. Every path here raises `FleetError`, so a test
    asserting only the type passes when a neighbouring guard fires instead — which is the shape
    that makes a refusal test vacuous while reading as coverage.

    Args:
      tmp_path: Pytest's temporary directory.
      label: The case, for the failure message.
      files: The fixture modules.
      phrase: The phrase the refusal must carry.

    Returns:
      None.

    Raises:
      AssertionError: When nothing raises, or the wrong guard does.
    """
    repo = _repo(tmp_path, files, pad=phrase != "has stopped working")
    with pytest.raises(fleet.FleetError) as raised:
        fleet.function_names(repo)
    assert phrase in str(raised.value), (
        f"{label}: expected a refusal saying {phrase!r}, got {str(raised.value)!r}. A different "
        "guard fired, so this case is not exercising what it names."
    )


def test_every_refusal_in_the_module_is_exercised_above(tmp_path: pathlib.Path) -> None:
    """The corpus reaches every `raise FleetError` in `fleet.py`.

    **This is the half that keeps the corpus honest.** A refusal added later, or one that becomes
    unreachable, is invisible to a hand-kept list of cases — so the sites are enumerated from the
    module's own source and compared against the lines the corpus actually executed. A guard nobody
    can reach and a guard nobody tested look identical from the outside, and both fail here.

    The tracer that was here is RESTORED rather than cleared, and that is not tidiness.
    `coverage.py` installs its own trace function, so `sys.settrace(None)` discards it and every
    module imported afterwards is measured at zero for the rest of the session — measured: the
    suite reported 88.31% with this test and 89.25% without it, with four files losing measurement
    including the one this change extends. A test that silently blinds the coverage gate is worse
    than the gap it closes.

    Args:
      tmp_path: Pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: When a `raise FleetError` site is never reached by the corpus.
    """
    import ast

    source = pathlib.Path(fleet.__file__)
    declared = {
        node.lineno
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and getattr(node.exc.func, "id", None) == "FleetError"
    }
    assert declared, "found no `raise FleetError` in fleet.py — the sweep has stopped working"

    executed: set[int] = set()
    previous = sys.gettrace()

    def trace(frame, event, _arg):
        """Records the lines executed in fleet.py.

        Args:
          frame: The frame being traced.
          event: The trace event.
          _arg: Unused.

        Returns:
          This tracer, so line events keep arriving.

        Raises:
          None.
        """
        if frame.f_code.co_filename == str(source):
            executed.add(frame.f_lineno)
        return trace

    for index, (_, files, _phrase) in enumerate(CASES):
        repo = _repo(tmp_path / str(index), files, pad=_phrase != "has stopped working")
        sys.settrace(trace)
        try:
            fleet.function_names(repo)
        except fleet.FleetError:
            pass
        finally:
            sys.settrace(previous)

    missed = sorted(declared - executed)
    assert not missed, (
        f"fleet.py raises FleetError at lines {missed} and the corpus reaches none of them. Either "
        "add a case, or the guard is unreachable — a refusal that cannot fire is not a refusal."
    )
