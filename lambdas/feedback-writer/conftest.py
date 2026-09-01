"""Keeps this function's module state from leaking between its own tests.

The suite fakes ``ADMIN_BUCKET`` and the S3 client on the module. Restoring them here rather than
in each test means a file added later cannot inherit a previous one's fake and pass or fail on
collection order — the failure ``notifications-writer``'s own conftest was added for.
"""

import pytest


@pytest.fixture(autouse=True)
def _restore_feedback_writer_module():
    """Snapshots the handler module's globals and puts them back afterwards.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    import feedback_writer

    saved = dict(vars(feedback_writer))
    yield
    feedback_writer.__dict__.clear()
    feedback_writer.__dict__.update(saved)
