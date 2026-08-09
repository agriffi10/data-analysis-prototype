"""SPEC-157 FR-008 — the execution role's lock grant, and the Deny it must not disturb.

Two properties, and the second matters more than the first. The lock needs read and write under
one prefix. What it must NOT do is widen anything else — and in particular the ``NoDataObjectDelete``
Deny is what forces the lock to release by OVERWRITING rather than deleting, so a change that
relaxed it would silently make an entirely different design available and nothing else would
notice.

Reads the policy template rather than a copy. ``${...}`` interpolations are substituted with
recognisable stand-ins so the statements can be reasoned about as JSON.
"""

import json
import os
import re
import sys

import pytest

_POLICY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "infra", "modules", "table-builder", "policies", "execution.json.tftpl",
)

_ADMIN = "arn:aws:s3:::admin-bucket"


def _policy():
    with open(_POLICY) as handle:
        source = handle.read()
    source = source.replace("${admin_bucket_arn}", _ADMIN)
    return json.loads(re.sub(r"\$\{[^}]+\}", "arn:aws:service:::other", source))


def _statement(sid):
    for statement in _policy()["Statement"]:
        if statement["Sid"] == sid:
            return statement
    raise AssertionError(f"no statement with Sid {sid!r}")


def _as_list(value):
    return value if isinstance(value, list) else [value]


def test_the_lock_grant_covers_read_and_write_under_exactly_one_prefix():
    statement = _statement("RefreshLockReadWrite")

    assert statement["Effect"] == "Allow"
    assert set(_as_list(statement["Action"])) == {"s3:GetObject", "s3:PutObject"}
    assert _as_list(statement["Resource"]) == [f"{_ADMIN}/locks/table-builder/*"]


def test_the_lock_grant_carries_no_delete_and_no_list():
    """Delete is the one that would matter: the release protocol exists in its current shape
    BECAUSE the role cannot delete, so granting it here would quietly permit a different design.
    """
    actions = set(_as_list(_statement("RefreshLockReadWrite")["Action"]))

    assert not {a for a in actions if "Delete" in a or "List" in a}


def test_the_admin_bucket_delete_deny_is_untouched():
    """FR-008 AC2. The Deny SPEC-149 deliberately kept when it removed glue:DeleteTable."""
    statement = _statement("NoDataObjectDelete")

    assert statement["Effect"] == "Deny"
    assert "s3:DeleteObject" in set(_as_list(statement["Action"]))
    assert f"{_ADMIN}/*" in _as_list(statement["Resource"])


def test_the_deny_still_covers_the_lock_prefix_itself():
    """The Deny is bucket-wide, so it covers `locks/` too — an explicit Deny beats the Allow
    above, which is exactly the intent: the lock may be written and never removed."""
    denied = _as_list(_statement("NoDataObjectDelete")["Resource"])

    assert any(r == f"{_ADMIN}/*" for r in denied), (
        "the Deny no longer covers the whole admin bucket, so `locks/` may now be deletable"
    )


def test_no_statement_grants_a_bare_wildcard_on_the_admin_bucket():
    """Guards against the lock grant being 'simplified' into a bucket-wide one later."""
    for statement in _policy()["Statement"]:
        if statement["Effect"] != "Allow":
            continue
        for resource in _as_list(statement["Resource"]):
            assert resource != f"{_ADMIN}/*", f"{statement['Sid']} grants the whole admin bucket"


def test_the_substitution_actually_happened():
    """Guards the guard: an un-substituted template would make every assertion above vacuous."""
    assert "${" not in json.dumps(_policy())
    assert _statement("RegistryRead")["Resource"] == f"{_ADMIN}/shared-spaces/*"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
