"""SPEC-083 FR-001: tbcommon config validates required env vars at import.

Reloads tbcommon.config with a var removed/added to assert the fail-fast on required
vars and the graceful path on optional ones; restores the conftest baseline afterward.
"""

import importlib
import os

from tbcommon import config


def test_required_var_fails_fast_naming_the_var():
    saved = dict(os.environ)
    try:
        os.environ.pop("ATHENA_WORKGROUP", None)
        raised = None
        try:
            importlib.reload(config)
        except RuntimeError as exc:
            raised = exc
        assert raised is not None, "expected a RuntimeError for the missing required var"
        assert "ATHENA_WORKGROUP" in str(raised)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


def test_each_required_var_is_enforced():
    for name in ("COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID", "ADMIN_BUCKET", "USER_SPACE_BUCKET", "SHARED_SPACE_BUCKET"):
        raised = None
        saved = dict(os.environ)
        try:
            os.environ.pop(name, None)
            try:
                importlib.reload(config)
            except RuntimeError as exc:
                raised = exc
        finally:
            os.environ.clear()
            os.environ.update(saved)
            importlib.reload(config)
        assert raised is not None and name in str(raised), f"{name} should be required"


def test_optional_notifications_queue_absent_is_ok():
    saved = dict(os.environ)
    try:
        os.environ.pop("NOTIFICATIONS_QUEUE_URL", None)
        importlib.reload(config)  # must NOT raise — optional (degrade-gracefully)
        assert config.NOTIFICATIONS_QUEUE_URL == ""
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)
