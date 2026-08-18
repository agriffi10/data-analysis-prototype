"""Keeps this function's two test files from patching each other.

``test_notifications_writer.py`` fakes ``verified_username`` and the bucket name on the module
and does not restore them — harmless while it was the only file here, and it runs as a plain
script too, so a pytest fixture is not available to it. The config gained
``test_verifier_parity.py``, which exercises the REAL verifier, and the stale fake made it pass
or fail on collection order.

Same mechanism as ``lambdas/conftest.py``'s shared-layer snapshot, scoped to this directory:
that fixture deliberately covers only the layers, and ``notifications_writer`` is a verb.
"""

import pytest


@pytest.fixture(autouse=True)
def _restore_notifications_writer_module():
    import notifications_writer

    saved = dict(vars(notifications_writer))
    yield
    notifications_writer.__dict__.clear()
    notifications_writer.__dict__.update(saved)
