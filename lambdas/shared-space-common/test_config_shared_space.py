"""SPEC-083 FR-001: shared-space config validates required env vars at import.

Reloads the module with a var removed/added to assert the fail-fast on required vars
and the graceful path on optional ones. Restores the conftest baseline in finally so
the rest of the suite keeps its patched config.
"""

import importlib
import os

import config


def _reload_without(name):
    """Reload config with ``name`` removed from the environment; restore afterwards."""
    saved = dict(os.environ)
    try:
        os.environ.pop(name, None)
        importlib.reload(config)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)  # restore to the conftest baseline


def test_required_var_fails_fast_naming_the_var():
    saved = dict(os.environ)
    try:
        os.environ.pop("ADMIN_BUCKET", None)
        raised = None
        try:
            importlib.reload(config)
        except RuntimeError as exc:
            raised = exc
        assert raised is not None, "expected a RuntimeError for the missing required var"
        assert "ADMIN_BUCKET" in str(raised)
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


def test_each_required_var_is_enforced():
    for name in ("COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID", "SHARED_SPACE_BUCKET", "USER_SPACE_BUCKET", "PORTAL_ROLE_ARN"):
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
        importlib.reload(config)  # must NOT raise — optional (SPEC-061 degrade-gracefully)
        assert config.NOTIFICATIONS_QUEUE_URL == ""
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)


def test_max_memberships_defaults_when_unset():
    saved = dict(os.environ)
    try:
        os.environ.pop("MAX_SHARED_MEMBERSHIPS", None)
        importlib.reload(config)
        assert config.MAX_SHARED_MEMBERSHIPS == 10  # sensible default, not required
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(config)
