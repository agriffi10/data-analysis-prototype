"""Pytest baseline for the Lambda suites.

The DOMAIN ``config.py`` modules fail fast at import when a required env var is unset
; ``cpcommon.config``'s six resolve on first access,
so they fail at the read instead. Either way the suites need the values present — the
tests patch ``config.X`` attributes (via ``fakes.install()`` etc.) but the code under
test still reads the unpatched ones — so this conftest stamps dummy values before any
test module is collected. Both fail-fast paths are exercised directly by
the domain env tests.

It also puts the shared Lambda-LAYER package roots on ``sys.path`` so ``from cpcommon
import …`` (and the domain layers) resolve everywhere under ``pytest lambdas/`` without
each test re-inserting them. Tests that also run directly (``python3
test_x.py``) keep their own per-file ``sys.path.insert`` for that mode.
"""

import os
import sys

_LAYER_DIRS = (
    "control-plane-common",
    "table-builder-common",
    "table-share-common",
    "file-send-common",
    "archive-common",
    "file-ops-common",
    "results-conversion-common",
)
_HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in _LAYER_DIRS:
    _path = os.path.join(_HERE, _dir)
    if _path not in sys.path:
        sys.path.insert(0, _path)


import pytest

# The shared cpcommon modules that verb tests globally patch (config.X = …,
# clients._s3 = fake, s3_listing.list_data_objects = stub, registry.load = …,
# auth.verified_username = …). Each domain once had its OWN copy of these,
# so a global patch could not leak across domains; now they are ONE module each, so a
# test that patches (and doesn't restore) one leaks into the next — e.g. the
# table-builder inspect test stubs list_data_objects, contaminating the table-share
# inspect test. Snapshot each module's namespace before a test and restore it after,
# keeping every test self-contained without touching any assertion.
#
# This covers EVERY shared-layer module rather than five hand-listed cpcommon ones
# module. The five covered `cpcommon.config/clients/s3_listing/registry/auth` and none of
# `cpcommon.observability`, `tbcommon`, `tscommon`, `dqcommon` or the shared-space flat
# modules — so the leak the fixture exists to stop was still live everywhere else, and the
# suites that hit it worked around it locally: `test_table_share_copy_objects.py` restored
# `tscommon.athena` by hand with a comment naming this gap (that module is gone —
# the rule replaced it with a bound runner INSTANCE, which this fixture cannot restore either,
# so its test restores locally), and five files hand-rolled
# try/finally around `observability.info`. Matching by PREFIX rather than by name means a
# new module in an existing layer is covered the day it is written, which a hand-list is not.
# The FLAT half of that claim went untrue and unnoticed for as long as it stood, because a
# matcher that yields nothing and a population with nothing to restore are the same green
# run. `test_conftest_restores_flat_shared_modules.py` is the control that says it collects.
#
# `log_foundry` is deliberately absent: it is a vendored library, not one of this repo's
# layers, and its process-wide worker/config already has purpose-built save-and-restore in
# the `captured_events` fixture below. Two mechanisms restoring the same globals in an order
# nobody chose is how a quiet teardown bug starts.
# `apicommon` is not a layer — it ships inside the API function's own package — but it is a
# shared module set that tests patch, which is the only property this fixture cares about.
# Left out, a test that patches apicommon.config leaks into the next one, which is the exact
# failure the fixture exists to stop.
_LAYER_PREFIXES = (
    "cpcommon", "tbcommon", "tscommon", "dqcommon", "fscommon", "arcommon", "focommon",
    "apicommon",
)

#: shared-space-common publishes FLAT modules, so they have no package prefix to match on.
#: DERIVED FROM THE DIRECTORY, never hand-listed: a hand-list drifts silently, and the leak
#: this fixture exists to stop would reopen behind a comment claiming it cannot.
#: A bare name is not enough to identify one — `config`, `auth` and `registry` are names any
#: function directory could also publish flat — so the module's own file has to place it in this
#: directory, and that comparison is what `_is_flat_shared` exists to get right.
_SHARED_SPACE_DIR = os.path.join(_HERE, "shared-space-common")
_SHARED_SPACE_REALPATH = os.path.realpath(_SHARED_SPACE_DIR)
_FLAT_SHARED_MODULES = frozenset(
    name[:-3]
    for name in os.listdir(_SHARED_SPACE_DIR)
    if name.endswith(".py") and not name.startswith(("test_", "conftest.", "fakes."))
)


def _is_flat_shared(name, module):
    """Whether an imported module is one of shared-space-common's flat modules.

    The path is compared REALPATH to REALPATH, and that is the whole point of this function
    rather than a substring test inline. Every shared-space suite puts the layer on
    ``sys.path`` as ``<its own dir>/../shared-space-common``, so the imported module's
    ``__file__`` keeps the literal ``..`` segment and no substring of the normalised
    directory appears anywhere in it. A substring test is therefore False for every flat
    module, always — which is silent, because an empty snapshot restores nothing and a
    fixture that restores nothing looks exactly like one with nothing to restore.

    Args:
      name: The module's ``sys.modules`` key.
      module: The module object itself.

    Returns:
      True when the module is a flat shared-space module, False otherwise.

    Raises:
      None.
    """
    if name not in _FLAT_SHARED_MODULES:
        return False
    path = getattr(module, "__file__", "") or ""
    return bool(path) and os.path.dirname(os.path.realpath(path)) == _SHARED_SPACE_REALPATH


def _shared_modules():
    """Every currently-imported module belonging to a shared Lambda layer.

    Read from ``sys.modules`` rather than imported: a suite that never touches a layer
    should not pay to import it, and a module imported mid-test is out of scope for a
    snapshot taken before it existed.

    Two matchers, and only one of them touches the filesystem. A LAYER package is
    identified by its import name alone, which no ``sys.path`` spelling can change; a FLAT
    shared-space module shares its bare name with modules elsewhere in the fleet, so it is
    identified by the directory its file sits in as well.

    Args:
      None.

    Yields:
      Each imported module the snapshot fixture is responsible for restoring.

    Raises:
      None.
    """
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        if _is_flat_shared(name, module) or name.split(".")[0] in _LAYER_PREFIXES:
            yield module


@pytest.fixture(autouse=True)
def _restore_shared_layer_modules():
    saved = {module: dict(vars(module)) for module in _shared_modules()}
    yield
    for module, snapshot in saved.items():
        module.__dict__.clear()
        module.__dict__.update(snapshot)

_REQUIRED_ENV = {
    "COGNITO_USER_POOL_ID": "us-east-1_testpool",
    "ADMIN_BUCKET": "admin-bkt",
    "SHARED_SPACE_BUCKET": "shared-bkt",
    "USER_SPACE_BUCKET": "user-bkt",
    # Not one of cpcommon.config's fleet-wide required vars (only the archive
    # plane sets it); stamped here so the archive verb suites read a real name rather than
    # each re-stamping it, exactly as the six above are.
    "ARCHIVE_BUCKET": "archive-bkt",
    "PORTAL_ROLE_ARN": "arn:aws:iam::000000000000:role/test-portal",
    "ATHENA_WORKGROUP": "test-workgroup",
    "AWS_REGION": "us-east-1",
    # The API's provider block. Stamped here beside the fleet's variables so a suite reaching
    # apicommon.config reads a coherent provider rather than each test inventing one — and so
    # that a test which MEANS to exercise the missing-configuration path has to unset it
    # deliberately rather than getting it for free.
    "OIDC_ISSUER": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_testpool",
    "OIDC_AUDIENCE": "test-app-client",
    "OIDC_JWKS_URI": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_testpool/.well-known/jwks.json",
    "OIDC_USERNAME_CLAIM": "cognito:username",
    "OIDC_REQUIRED_CLAIMS": '{"token_use":"id"}',
}

for _name, _value in _REQUIRED_ENV.items():
    os.environ.setdefault(_name, _value)


class _CapturingSink:
    """Collects emitted events so a verb test can assert on what it narrated."""

    def __init__(self):
        self.events = []

    def emit(self, batch):
        self.events.extend(batch)

    def close(self):
        pass

    def messages(self, message):
        return [e for e in self.events if e["message"] == message]

    def levels(self):
        """Everything that is not a span boundary — the narrative proper."""
        return [e for e in self.events if e["message"] not in ("span.start", "span.end")]

    def spans(self, function):
        return [
            e
            for e in self.events
            if e["message"] == "span.start" and e["function"] == function
        ]


@pytest.fixture
def captured_events():
    """Capture one test's structured events.

    Lives here rather than in each verb's test file because all nine data-quality verbs need
    it, and four more control planes need it — nine copies of a sink
    harness is how three of them end up subtly different.

    Retiring the worker is the part that is easy to miss: log-foundry builds it lazily from
    whatever sink was configured at the first flush and caches it for the process, so
    reconfiguring alone would send every event to the sink a previous test installed.
    """
    import log_foundry as lf
    from log_foundry import config as lf_config
    from log_foundry import decorator as lf_decorator

    def _swap(sink):
        worker = getattr(lf_decorator, "_worker", None)
        if worker is not None:
            worker.shutdown()
            lf_decorator._worker = None
        lf.configure(service="test", version="0", env="test", sink=sink)

    saved = lf_config._config
    sink = _CapturingSink()
    _swap(sink)
    yield sink
    _swap(_CapturingSink())  # quiet, and never the previous test's collector
    lf_config._config = saved


@pytest.fixture(scope="session", autouse=True)
def _drain_log_foundry_before_capture_closes():
    """Retire log-foundry's worker while pytest's captured streams are still open.

    `cpcommon.observability.init()` runs at module import in every instrumented handler
    and log-foundry registers its terminal `shutdown()` via `atexit`. At
    interpreter exit pytest has already closed the stream StdoutSink holds, so that atexit
    call raises `ValueError: I/O operation on closed file` and prints a traceback AFTER a
    green run — noise that would happily hide a real teardown error.

    Draining here gets there first. `shutdown()` is once-only by design,
    so the later atexit call becomes a no-op rather than a second drain.
    """
    yield
    try:
        import log_foundry

        log_foundry.shutdown()
    except Exception:  # noqa: BLE001, S110 — teardown hygiene must never fail a green suite
        pass
