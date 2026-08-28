"""SPEC-083 FR-001 / SPEC-125: the shared-space verbs' env contract fails fast.

SPEC-125 split this module's constants in two: the buckets / User Pool / notifications
queue moved to ``cpcommon.config`` (whose own fail-fast is pinned by
``test_config_cpcommon.py``), and ``PORTAL_ROLE_ARN`` + ``MAX_SHARED_MEMBERSHIPS`` stayed
here. So this file no longer re-tests the shared five — it tests what this module still
owns, plus the one thing neither file would otherwise cover: that the UNION a shared-space
verb needs is still required by SOMETHING.

That union test is the PR #196 lesson made executable. A verb must satisfy the requirements
of ALL its layers, so the set is the union across them. **The two layers now fail at
different moments** — this module's ``require`` at import, ``cpcommon``'s six at first read
(SPEC-156 FR-004) — and the union is unchanged by that. A variable that fails on a branch
instead of at cold start is narrower, not optional.
"""

import importlib
import os

from cpcommon import config as cpconfig

import config


def _requires(module, name):
    """True iff reloading ``module`` without ``name`` raises a RuntimeError naming it."""
    saved = dict(os.environ)
    raised = None
    try:
        os.environ.pop(name, None)
        try:
            importlib.reload(module)
        except RuntimeError as exc:
            raised = exc
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(module)
    return raised is not None and name in str(raised)


def _cpcommon_requires(name):
    """True iff reading the attribute ``name`` backs raises a RuntimeError naming it.

    ``cpcommon.config`` resolves on first access rather than at import (SPEC-156 FR-004), so
    the reload probe above cannot see its fail-fast — a reload with the variable removed now
    succeeds by design. The requirement is asserted where it now lives: at the read.

    Reloading first is not enough on its own, because ``importlib.reload`` re-executes a module
    in its EXISTING namespace — a value another test already resolved would still be cached and
    the lazy hook would never run. The cached names are dropped explicitly.
    """
    saved = dict(os.environ)
    raised = None
    try:
        os.environ.pop(name, None)
        module = importlib.reload(cpconfig)
        for attribute, variable in module._REQUIRED_VARS.items():
            if variable == name:
                vars(module).pop(attribute, None)
                try:
                    getattr(module, attribute)
                except RuntimeError as exc:
                    raised = exc
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(cpconfig)
    return raised is not None and name in str(raised)


def test_portal_role_arn_fails_fast_naming_the_var():
    # The one required var this module still owns: Lake Formation grants target it, and a
    # missing value would surface as an opaque LF failure mid-request instead.
    assert _requires(config, "PORTAL_ROLE_ARN")


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


def test_every_var_a_shared_space_verb_needs_is_required_by_one_of_its_two_layers():
    """The union across `cpcommon` + `shared-space-common`, which is what a cold start sees.

    Each var is checked against the module that now owns it, and by the mechanism that module
    uses: ``PORTAL_ROLE_ARN`` fails at import, the six fail at first read (SPEC-156 FR-004). If
    a future refactor moves one and forgets to require it, the var silently becomes optional in
    code while Terraform keeps setting it — and the break shows up only when an environment
    stops setting it.
    """
    owned_by_cpcommon = (
        "COGNITO_USER_POOL_ID",
        "COGNITO_APP_CLIENT_ID",
        "ADMIN_BUCKET",
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        # SPEC-125 added this one to the shared-space Lambdas' env for exactly this reason:
        # cpcommon requires it even though no shared-space verb calls Athena.
        "ATHENA_WORKGROUP",
    )
    for name in owned_by_cpcommon:
        assert _cpcommon_requires(name), f"{name} should be required by cpcommon.config"
    assert _requires(config, "PORTAL_ROLE_ARN")


def test_the_notifications_queue_stays_optional():
    # SPEC-061 degrade-gracefully: an unset queue makes every emit a logged no-op rather
    # than crashing a control plane that is otherwise working.
    saved = dict(os.environ)
    try:
        os.environ.pop("NOTIFICATIONS_QUEUE_URL", None)
        importlib.reload(cpconfig)  # must NOT raise
        assert cpconfig.NOTIFICATIONS_QUEUE_URL == ""
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(cpconfig)
