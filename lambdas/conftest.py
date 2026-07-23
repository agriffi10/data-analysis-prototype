"""Pytest baseline for the Lambda suites.

The control-plane ``config.py`` modules now fail fast at import when a required env
var is unset (SPEC-083 FR-001). The tests patch ``config.X`` attributes after import
(via ``fakes.install()`` etc.), but the import itself needs the required vars present,
so this conftest stamps dummy values before any test module (and its transitive
``import config``) is collected. The config fail-fast is still exercised directly by
``test_config.py``, which reloads the module with a var removed.

It also puts the shared Lambda-LAYER package roots on ``sys.path`` so ``from cpcommon
import …`` (and the domain layers) resolve everywhere under ``pytest lambdas/`` without
each test re-inserting them (SPEC-107). Tests that also run directly (``python3
test_x.py``) keep their own per-file ``sys.path.insert`` for that mode.
"""

import os
import sys

_LAYER_DIRS = ("control-plane-common", "table-builder-common", "table-share-common")
_HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in _LAYER_DIRS:
    _path = os.path.join(_HERE, _dir)
    if _path not in sys.path:
        sys.path.insert(0, _path)


import importlib  # noqa: E402

import pytest  # noqa: E402

# The shared cpcommon modules that verb tests globally patch (config.X = …,
# clients._s3 = fake, s3_listing.list_data_objects = stub, registry.load = …,
# auth.verified_username = …). Before SPEC-107 each domain had its OWN copy of these,
# so a global patch could not leak across domains; now they are ONE module each, so a
# test that patches (and doesn't restore) one leaks into the next — e.g. the
# table-builder inspect test stubs list_data_objects, contaminating the table-share
# inspect test. Snapshot each module's namespace before a test and restore it after,
# keeping every test self-contained without touching any assertion.
_SHARED_MODULES = ("cpcommon.config", "cpcommon.clients", "cpcommon.s3_listing", "cpcommon.registry", "cpcommon.auth")


@pytest.fixture(autouse=True)
def _restore_cpcommon_modules():
    saved = {}
    for name in _SHARED_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a suite that never imports it needs no reset
            continue
        saved[module] = dict(vars(module))
    yield
    for module, snapshot in saved.items():
        module.__dict__.clear()
        module.__dict__.update(snapshot)

_REQUIRED_ENV = {
    "COGNITO_USER_POOL_ID": "us-east-1_testpool",
    "COGNITO_APP_CLIENT_ID": "test-app-client",
    "ADMIN_BUCKET": "admin-bkt",
    "SHARED_SPACE_BUCKET": "shared-bkt",
    "USER_SPACE_BUCKET": "user-bkt",
    "PORTAL_ROLE_ARN": "arn:aws:iam::000000000000:role/test-portal",
    "ATHENA_WORKGROUP": "test-workgroup",
    "AWS_REGION": "us-east-1",
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
    """Capture one test's structured events (SPEC-132 FR-001).

    Lives here rather than in each verb's test file because all nine data-quality verbs need
    it, and SPEC-133→137 will need it for four more control planes — nine copies of a sink
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
    (SPEC-127), and log-foundry registers its terminal `shutdown()` via `atexit`. At
    interpreter exit pytest has already closed the stream StdoutSink holds, so that atexit
    call raises `ValueError: I/O operation on closed file` and prints a traceback AFTER a
    green run — noise that would happily hide a real teardown error.

    Draining here gets there first. `shutdown()` is once-only by design (log-forge SPEC-013),
    so the later atexit call becomes a no-op rather than a second drain.
    """
    yield
    try:
        import log_foundry

        log_foundry.shutdown()
    except Exception:  # noqa: BLE001 — teardown hygiene must never fail a green suite
        pass
