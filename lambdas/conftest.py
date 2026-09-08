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

import ast
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
# layers, and the `captured_events` fixture below re-points it through the library's own
# public `configure()` rather than by restoring globals. Two mechanisms restoring the same
# globals in an order nobody chose is how a quiet teardown bug starts.
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
    """Collects emitted events so a verb test can assert on what it narrated.

    Every read DRAINS log-foundry's worker first, and that is a property the readers exist for
    rather than a convenience. An event emitted with no span open is delivered synchronously;
    one emitted INSIDE a span is buffered until the worker flushes. So the moment a narrating
    helper gains an ``observability.step``, its existing events stop arriving before the
    assertion that reads them — and an absence over an undrained sink means "nothing has been
    flushed yet", which is green for exactly the same assertions as "nothing was emitted" and
    cannot be told apart from it.

    The drain reaches the sinks this fixture hands out and no others. Two suites configure
    collectors of their own — ``control-plane-common/test_observability_cpcommon.py`` and
    ``log-sweep/test_log_sweep.py`` — and each stays responsible for its own flushing.

    Attributes:
      _events: Every event delivered to ``emit``, in the order the worker delivered them — which
        a read now influences, because a read drains. An event emitted inside a span lands where
        the next read puts it rather than where it was emitted, so this list is a set to filter,
        not a sequence to index. Nothing asserts global ordering over it today. Private so that
        ``events`` can be the draining reader: ``emit`` appends here directly, which is what keeps
        a drain triggered by a read from re-entering the flush that caused it.
    """

    def __init__(self):
        """Starts with no events.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self._events = []

    def emit(self, batch):
        """Keeps one delivered batch.

        Appends to the private list rather than through ``events``: a read drains, and a drain
        delivers, so going through the property here would re-enter the flush it triggered.

        Args:
          batch: The events log-foundry is delivering.

        Returns:
          None.

        Raises:
          None.
        """
        self._events.extend(batch)

    def close(self):
        """Releases nothing.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """

    def _drain(self):
        """Flushes log-foundry's worker, but only while this sink is the live one.

        The guard is not defensive tidiness. ``flush`` delivers to whatever sink the library is
        configured with, not to the one being read — so draining from a RETIRED collector, which
        every teardown creates, would push its pending events into somebody else's collector as
        a side effect of reading this one.

        ``observability.flush`` rather than ``log_foundry.flush`` because it swallows. A read is
        expected to answer, and a caller reaching this through ``getattr(sink, "events", None)``
        would otherwise see a library fault as an absent attribute — a wrong verdict rather than
        a failure.

        Args:
          None.

        Returns:
          None.

        Raises:
          None. A library that cannot report its configuration leaves the collected events as
          they stand rather than failing the read.
        """
        import log_foundry as lf
        from cpcommon import observability

        try:
            live = lf.get_config().sink
        except Exception:  # noqa: BLE001
            return
        if live is self:
            observability.flush()

    @property
    def events(self):
        """Every event delivered so far, with the worker drained first.

        Args:
          None.

        Returns:
          The collected events, in delivery order.

        Raises:
          None.
        """
        self._drain()
        return self._events

    def messages(self, message):
        """Every event carrying one literal message.

        Args:
          message: The literal message to match.

        Returns:
          The matching events.

        Raises:
          None.
        """
        return [e for e in self.events if e["message"] == message]

    def levels(self):
        """Everything that is not a span boundary — the narrative proper.

        Args:
          None.

        Returns:
          The non-boundary events.

        Raises:
          None.
        """
        return [e for e in self.events if e["message"] not in ("span.start", "span.end")]

    def spans(self, function):
        """Every span opened under one function name, root or child.

        Args:
          function: The span's ``function`` field.

        Returns:
          The matching ``span.start`` events.

        Raises:
          None.
        """
        return [
            e
            for e in self.events
            if e["message"] == "span.start" and e["function"] == function
        ]

    def child_spans(self, parent_function, name=None):
        """The child spans opened inside one named span.

        Read from ONE snapshot of the events rather than from two: a parent set and a child set
        taken either side of a delivery would pair spans from different moments, and the
        mismatch would present as a child that is missing rather than as a race.

        Args:
          parent_function: The parent span's ``function`` — a verb's root span name.
          name: Restrict to child spans of this name, or None for every child.

        Returns:
          The ``span.start`` events whose ``parent_span_id`` is a span id of
          ``parent_function``.

        Raises:
          None.
        """
        collected = list(self.events)
        parents = {
            e["span_id"]
            for e in collected
            if e["message"] == "span.start" and e.get("function") == parent_function
        }
        return [
            e
            for e in collected
            if e["message"] == "span.start"
            and e.get("parent_span_id") in parents
            and (name is None or e.get("function") == name)
        ]


def observability_decorator_names(tree, attribute="step"):
    """Every local name in one parsed module that resolves to ``observability.<attribute>``.

    The spelling a decorator wears is the author's choice, and a guard that matches the rendered
    text ``observability.step`` is blind to every other one. Measured: a
    ``from .observability import step`` plus a bare ``@step("…")`` planted the exact per-recipient
    instrumentation the control planes forbid, and the whole suite stayed green. No such spelling
    exists in ``lambdas/`` today — which is why this resolves bindings rather than adding a second
    literal to match, since the next spelling will not be one anybody predicted either.

    Args:
      tree: The parsed module.
      attribute: The observability name being looked for — ``step`` or ``traced``.

    Returns:
      The set of dotted or bare names that decorate a function with it.

    Raises:
      None.
    """
    names = {f"observability.{attribute}"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("observability"):
                    # `import a.b.observability` binds `a`, so the only spelling that works at a
                    # call site is the FULL dotted path — taking the last segment registered a
                    # name no decorator can wear, and three forbidden functions took a step with
                    # the whole suite green. `as` binds the alias alone, which is the other case.
                    names.add(f"{alias.asname or alias.name}.{attribute}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "observability":
                    names.add(f"{alias.asname or 'observability'}.{attribute}")
                elif alias.name == attribute and module.endswith("observability"):
                    names.add(alias.asname or attribute)
    return names


def stepped_functions(tree, attribute="step"):
    """Every function in one parsed module carrying a span decorator, with the name it declares.

    Args:
      tree: The parsed module.
      attribute: ``step`` for a child span, ``traced`` for a verb's root span.

    Returns:
      A list of ``(function name, span name)`` pairs; the span name is None when the decorator
      names none. A name passed by KEYWORD counts: read from positional arguments alone it came
      back None, and the collision sweep skips a None.

    Raises:
      None.
    """
    bound = observability_decorator_names(tree, attribute)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = decorator.func if isinstance(decorator, ast.Call) else decorator
            if ast.unparse(call) not in bound:
                continue
            arguments = list(getattr(decorator, "args", [])) + [
                keyword.value
                for keyword in getattr(decorator, "keywords", [])
                if keyword.arg == "name"
            ]
            literals = [
                a.value
                for a in arguments
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            found.append((node.name, literals[0] if literals else None))
    return found


@pytest.fixture
def step_scan():
    """Hands a test the shared step-decorator scanners.

    A fixture rather than a helper each suite copies: the two guards that use it live in
    different files, and the same matcher written twice is the one that is wrong in one copy.

    Args:
      None.

    Returns:
      The ``stepped_functions`` scanner, which takes a parsed module and optionally ``"traced"``.

    Raises:
      None.
    """
    return stepped_functions


@pytest.fixture
def captured_events():
    """Capture one test's structured events.

    Lives here rather than in each verb's test file because all nine data-quality verbs need
    it, and four more control planes need it — nine copies of a sink
    harness is how three of them end up subtly different.

    `configure()` is the whole mechanism, and that is a change: it used to be insufficient.
    log-foundry built its worker lazily from whichever sink was configured at the first flush
    and cached it for the process, so reconfiguring alone left delivery pointed at the sink a
    previous test had installed — measured. The library now drains, closes the old sink and
    re-points delivery, so the hand-written worker retirement this fixture used to do is gone.
    It could not have stayed in any case: the private name it reached for no longer exists,
    and it had degraded to a silent no-op behind a `getattr` default.

    Nothing here saves and restores `config._config` either. That reach is worse than
    redundant now: the library keeps a live sink beside the stored config, so assigning the
    old config back leaves it REPORTING one sink while DELIVERING to another. The teardown
    swap below is what actually re-points delivery. One consequence is stated rather than
    discovered: with no restore, the service/version/env this fixture stamps stay configured
    for the rest of the session. Nothing asserts the stamped service today and no `init()` call
    site passes `defaults`, so it is a standing condition rather than a defect — but a test
    that starts asserting on them must configure its own.

    Args:
      None.

    Yields:
      The capturing sink for one test.

    Raises:
      None.
    """
    import log_foundry as lf

    def _swap(sink):
        lf.configure(service="test", version="0", env="test", sink=sink)

    sink = _CapturingSink()
    _swap(sink)
    yield sink
    _swap(_CapturingSink())  # quiet, and never the previous test's collector


@pytest.fixture(scope="session", autouse=True)
def _drain_log_foundry_before_capture_closes():
    """Retire log-foundry's worker while pytest's captured streams are still open.

    `cpcommon.observability.init()` runs at module import in every instrumented handler
    and log-foundry registers its terminal `shutdown()` via `atexit`. At interpreter exit
    pytest has already closed the stream StdoutSink holds, so that atexit call fails.

    WHAT IT FAILS WITH CHANGED WITH THE PIN, and the fixture is kept for a smaller reason than
    the one it used to give. On the version this was written against, the failure printed a
    full traceback after a green run — noise that would happily hide a real teardown error.
    The pinned version absorbs it into a single line naming the exception type, which hides
    nothing. Draining here still gets there first and keeps the run silent; it is now tidiness
    rather than a guard against a masked failure.

    `shutdown()` is once-only by design, so the later atexit call becomes a no-op rather than
    a second drain.

    Args:
      None.

    Yields:
      None. Everything happens after the session.

    Raises:
      None.
    """
    yield
    try:
        import log_foundry

        log_foundry.shutdown()
    except Exception:  # noqa: BLE001, S110 — teardown hygiene must never fail a green suite
        pass
