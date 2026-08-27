"""One JWKS verification path in this repo, enforced rather than asserted in a docstring.

There were four copies of the claim checks once, so a fix to any of them had to be made in every
one and would eventually have been made in one. Deduplicating them was a whole change; keeping
them deduplicated is this file. A second ``jwt.decode`` is a new deliberate twin, and it would be
added by someone who had a good local reason and no way to see the other three.

**THE SUBJECT IS EVERY NON-TEST MODULE, SELECTED BY PATH — never a hand-kept allowlist.** That is
a stated rule and not a convenience, and it has to be: the auth suite legitimately calls
``jwt.decode`` to read back the claims of a token it minted, calls ``clients.jwks`` three times to
prove the client cache is keyed per URL, and three further suites rebind ``clients.jwks`` to a
fake. Run unfiltered, this sweep fails on those assertions the day it is written, and the repair
a builder reaches for is to delete them. An allowlist would work today and rot quietly; a path
rule cannot.

Attributes:
  LAMBDAS: The fleet root, and the sweep's subject.
  EXCLUDED_NAMES: Files that are not shipped modules. Two categories, deliberately — a third
    would be an exemption in an allowlist's clothing.
  ONE_DECODE: Where the repo's single ``jwt.decode`` is allowed to live.
  ONE_JWKS: Where the repo's single ``clients.jwks`` call is allowed to live.
"""

import ast
import pathlib

LAMBDAS = pathlib.Path(__file__).resolve().parent

EXCLUDED_NAMES = ("test_", "conftest.")

ONE_DECODE = "control-plane-common/cpcommon/auth.py"
ONE_JWKS = "control-plane-common/cpcommon/auth.py"


def _shipped_modules() -> list[pathlib.Path]:
    """Every module that reaches a Lambda, selected by path.

    Args:
      None.

    Returns:
      The sorted module paths.

    Raises:
      None.
    """
    return sorted(
        path
        for path in LAMBDAS.rglob("*.py")
        if not path.name.startswith(EXCLUDED_NAMES) and "__pycache__" not in path.parts
    )


def _calls(path: pathlib.Path) -> list[str]:
    """Names every call in a module, as ``receiver.attribute`` or a bare name.

    Parsed rather than grepped: a substring scan cannot tell a call from a docstring saying the
    call is forbidden, and this file's own prose would trip one.

    Args:
      path: The module to parse.

    Returns:
      One entry per call site.

    Raises:
      None.
    """
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                found.append(f"{target.value.id}.{target.attr}")
            elif isinstance(target, ast.Name):
                found.append(target.id)
        # `from jwt import decode` then a bare `decode(...)` reads as a plain Name and would
        # slip past a sweep looking only for the attribute form. Flagging the import closes it
        # at the only place it can be written.
        elif isinstance(node, ast.ImportFrom) and node.module == "jwt":
            found.extend(f"jwt.{alias.name}" for alias in node.names)
    return found


def _sites(call: str) -> list[str]:
    """Every shipped module containing the named call, as a repo-relative path."""
    return [
        str(path.relative_to(LAMBDAS))
        for path in _shipped_modules()
        if call in _calls(path)
    ]


def test_the_sweep_has_a_subject() -> None:
    """Guard-the-guard: a filter that excluded everything would read as a clean pass.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the subject set is empty or has lost the module it exists to pin.
    """
    modules = {str(path.relative_to(LAMBDAS)) for path in _shipped_modules()}
    assert len(modules) > 50, f"the sweep's subject collapsed to {len(modules)} modules"
    assert ONE_DECODE in modules
    assert not any(name.startswith(EXCLUDED_NAMES) for name in (p.rsplit("/", 1)[-1] for p in modules))


def test_exactly_one_module_decodes_a_jwt() -> None:
    """Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a second module decodes a token.
    """
    assert _sites("jwt.decode") == [ONE_DECODE]


def test_exactly_one_module_builds_a_jwks_client() -> None:
    """Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a second module reaches the JWKS factory.
    """
    assert _sites("clients.jwks") == [ONE_JWKS]
