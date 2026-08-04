"""Every table-builder verb's environment must satisfy the layers' import-time fail-fast.

THE TRAP THIS EXISTS FOR HAS FIRED TWICE. ``cpcommon/config.py`` calls ``_require`` on six
variables AT IMPORT, and every verb reaches it (each imports ``tbcommon.notify`` →
``tbcommon.config`` → ``cpcommon.config``). So a verb missing ONE variable does not
misbehave — it raises ``RuntimeError`` at COLD START, before the handler exists. PR #196
broke the whole plane that way (check-table-absent, ``COGNITO_USER_POOL_ID`` unset); PR
#317 broke sign-up the same way through a missing layer.

Nothing else catches it: ``update-function-code`` succeeds against a function that cannot
import, and ``lambdas/conftest.py`` stamps the variables before collection so every test
imports happily. This reads the deployed Terraform instead and joins it against what the
layers actually demand.

Runnable under pytest or directly: python3 test_table_builder_env.py.
"""

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
    """Every variable the two config modules ``_require`` at import."""
    sources = _read(_CPCONFIG) + _read(_TBCONFIG)
    return set(re.findall(r'_require\(\s*"([A-Z0-9_]+)"\s*\)', sources))


def _common_environment():
    """The variable names set in lambda.tf's shared `environment { variables = merge({…` block."""
    source = _read(_LAMBDA_TF)
    start = source.index("environment {")
    end = source.index("lookup(local.table_builder_verb_env", start)
    return set(re.findall(r"^\s+([A-Z0-9_]+)\s*=", source[start:end], re.MULTILINE))


def _function_suffixes():
    """The keys of locals.tf's `table_builder_functions` map."""
    source = _read(_LOCALS_TF)
    start = source.index("table_builder_functions = {")
    end = source.index("}\n", source.index("execute-ddl", start))
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
    assert suffixes == {
        "validate-authorize", "check-table-absent", "load-table-definition",
        "inspect-source", "infer-schema", "diff-schema", "execute-ddl",
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
