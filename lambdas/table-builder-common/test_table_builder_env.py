"""Every table-builder verb's environment must satisfy the layers' import-time fail-fast.

THE TRAP THIS EXISTS FOR HAS FIRED TWICE. ``tbcommon/config.py`` calls ``_require`` AT
IMPORT and every verb reaches it, so a verb missing ONE of its variables does not
misbehave — it raises ``RuntimeError`` at COLD START, before the handler exists. PR #196
broke the whole plane that way (check-table-absent, ``COGNITO_USER_POOL_ID`` unset); PR
#317 broke sign-up the same way through a missing layer.

``cpcommon/config.py``'s six moved to first access in SPEC-156, so they are no longer a cold
start away — but they are still one code path away, and this test's obligation is unchanged:
the common environment must satisfy the UNION of what both modules can demand. Narrowing the
guard to match the narrower failure window would be assuming the branch that reads the
missing variable never runs.

Nothing else catches it: ``update-function-code`` succeeds against a function that cannot
import, and ``lambdas/conftest.py`` stamps the variables before collection so every test
imports happily. This reads the deployed Terraform instead and joins it against what the
layers actually demand.

Runnable under pytest or directly: python3 test_table_builder_env.py.
"""

import ast
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE = os.path.join(_HERE, "..", "..", "infra", "modules", "table-builder")
_LAMBDA_TF = os.path.join(_MODULE, "lambda.tf")
_LOCALS_TF = os.path.join(_MODULE, "locals.tf")
_CPCONFIG = os.path.join(_HERE, "..", "control-plane-common", "cpcommon", "config.py")
_TBCONFIG = os.path.join(_HERE, "tbcommon", "config.py")


def _read(path):
    with open(path) as handle:
        return handle.read()


def _required_variables():
    """Every variable the two config modules require.

    Two forms, because the two modules resolve differently. ``tbcommon.config`` still calls
    ``_require`` at import; ``cpcommon.config`` declares its set in ``_REQUIRED_VARS`` and
    resolves on first access (SPEC-156 FR-004), so a regex over call sites would find none of
    its six and every assertion below would pass by measuring nothing.
    """
    names = set(re.findall(r'_require\(\s*"([A-Z0-9_]+)"\s*\)', _read(_TBCONFIG)))
    for node in ast.walk(ast.parse(_read(_CPCONFIG))):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_REQUIRED_VARS"
            for target in node.targets
        ):
            names |= set(ast.literal_eval(node.value).values())
    return names


def _common_environment():
    """The variable names set in lambda.tf's shared `environment { variables = merge({…` block."""
    source = _read(_LAMBDA_TF)
    start = source.index("environment {")
    end = source.index("lookup(local.table_builder_verb_env", start)
    return set(re.findall(r"^\s+([A-Z0-9_]+)\s*=", source[start:end], re.MULTILINE))


def _function_suffixes():
    """The keys of locals.tf's `table_builder_functions` map.

    Read to the map's own closing brace, not to the first one after a NAMED entry. The earlier
    parse ended at ``execute-ddl``, so every entry declared after it was invisible — SPEC-152's
    ``notify-failure`` had been outside the guard since the day it landed, and the assertion
    below looked exhaustive while measuring eight of nine. A parse anchored to one entry's
    position is a hand-maintained list wearing a regex.
    """
    source = _read(_LOCALS_TF)
    start = source.index("table_builder_functions = {")
    end = source.index("\n  }\n", start)
    return set(re.findall(r'^\s+"([a-z-]+)"\s+=', source[start:end], re.MULTILINE))


def test_the_common_environment_satisfies_every_import_time_require():
    missing = _required_variables() - _common_environment()

    assert not missing, (
        f"{sorted(missing)} is _require()d at import but absent from the table-builder "
        "common environment — every verb attaching the layer crashes at COLD START, which "
        "a green deploy cannot see (PR #196)"
    )


def test_the_new_refresh_verb_is_in_the_map_that_grants_that_environment():
    """lambda.tf is entirely `for_each` over this map, so being in it IS how a function
    gets the common environment block. A function created any other way would not."""
    suffixes = _function_suffixes()

    assert "load-table-definition" in suffixes
    assert "notify-failure" in suffixes, "the parse stopped early again — see _function_suffixes"
    assert suffixes == {
        "validate-authorize", "check-table-absent", "load-table-definition",
        "acquire-refresh-lock", "release-refresh-lock",
        "inspect-source", "infer-schema", "diff-schema", "apply-refresh", "execute-ddl",
        "notify-failure",
    }


def test_no_per_verb_override_can_remove_a_required_variable():
    """`table_builder_verb_env` is merged OVER the common block, so an entry could shadow a
    required variable with an empty string — which `_require` rejects, at cold start again.
    It is empty today; this pins the reason it must stay that way for required names."""
    source = _read(_LOCALS_TF)
    block = source[source.index("table_builder_verb_env = {"):]
    declared = set(re.findall(r'^\s+([A-Z0-9_]+)\s*=', block[: block.index("}")], re.MULTILINE))

    assert not declared & _required_variables(), (
        f"per-verb env {sorted(declared & _required_variables())} shadows a required variable"
    )


def test_the_required_set_is_actually_being_found():
    """Guards every assertion above against passing vacuously if a regex stops matching."""
    assert "COGNITO_USER_POOL_ID" in _required_variables()
    assert len(_required_variables()) >= 6
    assert "LOGS_QUEUE_URL" in _common_environment()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
