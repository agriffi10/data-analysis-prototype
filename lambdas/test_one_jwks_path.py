"""One JWKS verification path in this repo, and one caller of it, enforced rather than asserted.

Why a sweep and not an allowlist, and why the subject is selected by path:
``lambdas/info/shared-layer.md``.

Two claims, and the second is newer. The first is that verification lives in one module — it
used to live in four, so a fix to any of them had to be made in all of them. The second is that
one CALLER is left: the control planes stopped verifying when the API became the only principal
that may write their queues, and they read the identity block it stamps instead. That is the
half a reader cannot check by looking, because a plane that quietly re-grew a token check would
look like defence in depth rather than like two answers to one question.

Attributes:
  LAMBDAS: The fleet root, and the sweep's subject.
  EXCLUDED_NAMES: Files that are not shipped modules.
  ONE_DECODE: Where the repo's single ``jwt.decode`` is allowed to live.
  ONE_JWKS: Where the repo's single ``clients.jwks`` call is allowed to live.
  VERIFIER_ENTRY_POINTS: What a caller of the verifier names. A module outside the API that
    names one has started answering "is this really alice?" a second time.
  CLAIM_LITERAL: The provider-specific claim name. It survives in no shipped module at all now —
    the API reads a CONFIGURED claim name, so a literal anywhere is a provider assumption
    someone hard-coded back in.
"""

import ast
import pathlib

LAMBDAS = pathlib.Path(__file__).resolve().parent

EXCLUDED_NAMES = ("test_", "conftest.")

ONE_DECODE = "control-plane-common/cpcommon/auth.py"
ONE_JWKS = "control-plane-common/cpcommon/auth.py"

VERIFIER_ENTRY_POINTS = frozenset({"verify_token", "verify_id_token", "verified_username"})

CLAIM_LITERAL = "cognito:username"


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


def test_only_the_api_calls_the_verifier_and_no_module_names_the_claim() -> None:
    """The planes take a trusted actor from the message; nothing outside the API verifies one.

    The subject set is asserted before both claims, because a filter that excluded everything
    would read as a clean pass on each — which is the shape this file's own first test already
    guards against for its own claims.

    The claim literal is swept as TEXT rather than as an AST node, and that is deliberate here
    where it is not elsewhere: the risk is a provider name hard-coded back into any position at
    all — a dict key, a docstring promising the wrong thing, an f-string — not specifically a
    call. The two modules that legitimately discussed it no longer exist.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a module outside the API verifies a token, or names the claim.
    """
    modules = _shipped_modules()
    relative = {str(path.relative_to(LAMBDAS)) for path in modules}

    assert len(relative) > 50, f"the sweep's subject collapsed to {len(relative)} modules"
    assert ONE_DECODE in relative, "the sweep lost the module it exists to pin"

    verifiers = sorted(
        str(path.relative_to(LAMBDAS))
        for path in modules
        if VERIFIER_ENTRY_POINTS & set(_calls(path))
        and not str(path.relative_to(LAMBDAS)).startswith(("api/", "control-plane-common/"))
    )
    assert verifiers == [], (
        f"{verifiers} verify a token — the API is the only principal that may write these "
        "queues, so a plane re-checking what it stamped is a second answer to one question"
    )

    claim_readers = sorted(
        str(path.relative_to(LAMBDAS))
        for path in modules
        if CLAIM_LITERAL in path.read_text(encoding="utf-8")
    )
    assert claim_readers == [], (
        f"{claim_readers} name {CLAIM_LITERAL!r} — the username claim is configuration "
        "(OIDC_USERNAME_CLAIM), and a literal is the provider assumption the federated "
        "migration exists to remove"
    )
