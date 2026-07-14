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
