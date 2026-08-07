"""SPEC-083 FR-001 / SPEC-107 / SPEC-156 FR-004: cpcommon config resolves lazily and loudly.

The shared config core moved from tbcommon to cpcommon (SPEC-107); SPEC-156 moved the
``_require`` of its six variables from import time to first access, because the eager
version made ``cpcommon.auth`` unimportable for any function that does not set all six.

The fail-fast property is the one that must survive that move, so it is asserted at the new
boundary: reading the attribute with the variable removed still raises a ``RuntimeError``
naming the variable. Each test reloads the module first so no earlier read has cached the
value, and restores the conftest baseline afterward.
"""

import importlib
import os
import subprocess
import sys

import pytest
from cpcommon import config

REQUIRED = (
    ("USER_POOL_ID", "COGNITO_USER_POOL_ID"),
    ("APP_CLIENT_ID", "COGNITO_APP_CLIENT_ID"),
    ("ADMIN_BUCKET", "ADMIN_BUCKET"),
    ("USER_SPACE_BUCKET", "USER_SPACE_BUCKET"),
    ("SHARED_SPACE_BUCKET", "SHARED_SPACE_BUCKET"),
    ("ATHENA_WORKGROUP", "ATHENA_WORKGROUP"),
)


def _reload_without(var):
    """Reloads config with one variable removed, returning the freshly-loaded module.

    The cached values are dropped explicitly because ``importlib.reload`` re-executes a module
    in its EXISTING namespace: a value an earlier test resolved survives the reload, the lazy
    hook never runs, and the assertion below passes or fails on test ORDER rather than on
    behaviour. It did — two of the six, in the full suite only.
    """
    os.environ.pop(var, None)
    module = importlib.reload(config)
    for attribute in (*module._REQUIRED_VARS, *module._OPTIONAL_VARS):
        vars(module).pop(attribute, None)
    return module


@pytest.mark.parametrize(("attribute", "var"), REQUIRED, ids=lambda v: v)
def test_a_required_var_fails_loudly_at_first_use_naming_the_var(attribute, var):
    saved = dict(os.environ)
    try:
        module = _reload_without(var)
        with pytest.raises(RuntimeError) as excinfo:
            getattr(module, attribute)
        assert var in str(excinfo.value)
        assert "unset or empty" in str(excinfo.value)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


@pytest.mark.parametrize(("attribute", "var"), REQUIRED, ids=lambda v: v)
def test_importing_config_does_not_require_the_var(attribute, var):
    """The whole point of the move: the import must not touch the variable at all.

    The eager version raised here, which is why a function setting three of the six could
    not import ``cpcommon.auth`` and grew its own JWKS verifier instead (SPEC-156 FR-004).
    """
    saved = dict(os.environ)
    try:
        _reload_without(var)  # must NOT raise
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


def test_a_resolved_value_is_cached_and_stays_patchable():
    """Read once, then an ordinary module global — the contract every caller was written to.

    ``config.X`` is read at call time precisely so a test can patch it; the lazy hook only
    runs while the name is absent, so it must not shadow a patched value.
    """
    module = importlib.reload(config)
    assert os.environ["ADMIN_BUCKET"] == module.ADMIN_BUCKET
    assert "ADMIN_BUCKET" in vars(module), "the resolved value was not cached in the module"
    module.ADMIN_BUCKET = "patched-bkt"
    assert module.ADMIN_BUCKET == "patched-bkt"
    importlib.reload(config)


def test_optional_notifications_queue_absent_is_ok():
    saved = dict(os.environ)
    try:
        module = _reload_without("NOTIFICATIONS_QUEUE_URL")
        assert module.NOTIFICATIONS_QUEUE_URL == ""  # optional (degrade-gracefully)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


def test_an_unknown_attribute_is_still_an_attribute_error():
    """Laziness must not turn a typo into a silent empty string."""
    with pytest.raises(AttributeError):
        getattr(config, "NOT_A_SETTING")  # noqa: B009 - the lookup IS the assertion


def test_dir_lists_the_unresolved_attributes_too():
    module = importlib.reload(config)
    assert {"USER_POOL_ID", "ATHENA_WORKGROUP", "REGION"} <= set(dir(module))


_IMPORT_PROBE = """
import sys
from cpcommon import config

config.CATALOG_IDENTIFIER_RE  # a constant needs no environment
print("IMPORT_OK", file=sys.stderr)
try:
    config.ADMIN_BUCKET
except RuntimeError as exc:
    print(f"RAISED {exc}", file=sys.stderr)
"""


def test_config_imports_with_no_environment_and_raises_only_on_the_read():
    """Asserted in a fresh interpreter, because ``lambdas/conftest.py`` stamps all six.

    An in-process assertion would pass no matter when the ``_require`` ran, which is the
    same trap ``test_layer_import_safety.py`` documents.
    """
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH")}
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _IMPORT_PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stderr, result.stderr
    assert "RAISED required environment variable 'ADMIN_BUCKET' is unset or empty" in result.stderr
