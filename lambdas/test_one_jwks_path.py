"""One JWKS verification path in this repo, enforced rather than asserted in a docstring.

Why a sweep and not an allowlist, and why the subject is selected by path:
``lambdas/info/shared-layer.md``.

Attributes:
  LAMBDAS: The fleet root, and the sweep's subject.
  EXCLUDED_NAMES: Files that are not shipped modules.
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
    call is forbidden, and this file's own prose would trip one. A ``from jwt import decode``
    followed by a bare ``decode(...)`` reads as a plain Name, so the import is flagged too.

    Args:
      path: The module to parse.

    Returns:
      One entry per call site.

    Raises:
      None.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                found.append(f"{target.value.id}.{target.attr}")
            elif isinstance(target, ast.Name):
                found.append(target.id)
        elif isinstance(node, ast.ImportFrom) and node.module == "jwt":
            found.extend(f"jwt.{alias.name}" for alias in node.names)
    return found


def test_exactly_one_module_decodes_a_jwt_and_one_builds_a_jwks_client() -> None:
    """A second ``jwt.decode`` is a deliberate twin added by someone with a good local reason
    and no way to see the other three that used to exist.

    The subject set is asserted first: a filter that excluded everything would read as a clean
    pass on both claims below.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the sweep lost its subject, or a second module decodes a token or
        reaches the JWKS factory.
    """
    modules = _shipped_modules()
    relative = {str(path.relative_to(LAMBDAS)) for path in modules}

    sites = {
        call: [
            str(path.relative_to(LAMBDAS)) for path in modules if call in _calls(path)
        ]
        for call in ("jwt.decode", "clients.jwks")
    }

    assert len(relative) > 50, f"the sweep's subject collapsed to {len(relative)} modules"
    assert ONE_DECODE in relative, "the sweep lost the module it exists to pin"
    assert sites["jwt.decode"] == [ONE_DECODE], (
        f"{sites['jwt.decode']} decode a JWT — the claim checks were deduplicated to one place, "
        "and a fix made in one of four copies is a fix made nowhere"
    )
    assert sites["clients.jwks"] == [ONE_JWKS], (
        f"{sites['clients.jwks']} build a JWKS client"
    )
