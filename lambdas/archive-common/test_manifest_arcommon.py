"""``_manifest.json``: what it records, where it sits, and the thing it must never become.

The interesting test in this file is the last one. The manifest is an integrity RECORD, and the
moment a restore verb reads it, a lost or hand-edited file can make a restore wrong — which is
exactly what the self-describing archive key exists to prevent. SPEC-170 and SPEC-171 have not
been written yet, so the sweep is a tripwire for them rather than a check on today's code.

Runnable under pytest or directly: python3 test_manifest_arcommon.py.
"""

import ast
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import manifest
from arcommon.config import ARCHIVE_STORAGE_CLASS
from cpcommon import clients
from cpcommon.errors import TransientError


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, error=None):
        self.puts = []
        self._error = error

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._error:
            raise self._error
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {}


def _install(error=None):
    fake = _FakeS3(error)
    clients._s3 = fake
    return fake


_ROOT = "personal/alice/archive/9f2c1b8e-1111-4222-8333-444444444444/"

#: The files that may name the record: the writer, the module that defines it, and — since
#: SPEC-170 — the restore layer that reads it as a CROSS-CHECK. The third one is the interesting
#: entry, and its exemption is only sound because ``test_restore_arcommon`` pins the tolerance
#: that makes it a cross-check rather than a dependency: an absent, unreadable or malformed
#: record lets the restore proceed, and only a record that DISAGREES refuses. Delete those tests
#: and this exemption becomes the hole the sweep exists to keep shut.
_ALLOWED = {
    "arcommon/manifest.py",
    "arcommon/restore.py",
    "arcommon/plan.py",
    "archive-write-manifest/archive_write_manifest.py",
}

#: The only VERB permitted to name the record, asserted separately below. Everything else in
#: _ALLOWED is layer code, where the rule has one home and one tested behaviour.
_ALLOWED_VERBS = {"archive-write-manifest/archive_write_manifest.py"}

#: Files under this prefix are VERBS. No restore verb may name the record itself: the cross-check
#: belongs to the layer, where its tolerance is tested once, and a verb reaching for the basename
#: directly is a verb that has grown its own rule about it.
_VERB_PREFIXES = ("archive-",)


def receipt_module_path() -> str:
    """The receipt module, which names the basename in its DOCSTRING and in no code.

    Used by the guard-the-guard test below: it is the case that makes an AST walk necessary
    rather than a text scan, so if it ever stops carrying the mention, the walk stops being
    exercised against the thing it exists to tolerate.
    """
    return str(pathlib.Path(__file__).resolve().parent / "arcommon" / "receipt.py")


def _docstring_constants(tree) -> set:
    """The ids of every Constant node that is a module, class or function docstring.

    By NODE IDENTITY, and SPEC-165 records why: skipping the ``Expr`` and not its ``Constant``
    child is how an earlier sweep of this shape flagged two docstrings it meant to exempt.
    """
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            ids.add(id(body[0].value))
    return ids


def _basename_users() -> dict:
    """Every module in the archive plane, mapped to whether it USES the record's name in code.

    A use is a non-docstring string constant carrying the basename, or an import of THIS
    ``manifest`` module — the two ways a verb could come to depend on the record. Docstrings are
    exempt: the write ordering is explained in several of them, and a sweep that has to be
    silenced with exceptions is a sweep nobody will keep.

    **The import test is qualified rather than by bare name, because there are two modules called
    ``manifest``.** ``cpcommon.transfer.manifest`` writes the Distributed Map's JSONL dataset and
    has nothing to do with the record; a bare-name match flagged the manifest BUILDER, which is
    the one verb in the plane that must import it.
    """
    plane = pathlib.Path(__file__).resolve().parent.parent
    users = {}
    for path in sorted(plane.glob("archive*/**/*.py")):
        if "__pycache__" in str(path) or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text())
        exempt = _docstring_constants(tree)
        uses = any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and manifest.BASENAME in node.value
            and id(node) not in exempt
            for node in ast.walk(tree)
        ) or any(
            isinstance(node, ast.ImportFrom)
            and (
                (node.module or "").endswith("arcommon.manifest")
                or (
                    ((node.module or "").split(".")[-1] == "arcommon" or node.level)
                    and any(alias.name == "manifest" for alias in node.names)
                )
            )
            for node in ast.walk(tree)
        )
        users["/".join(path.parts[-2:])] = uses
    return users


def _record():
    return {
        "requestId": "9f2c1b8e-1111-4222-8333-444444444444",
        "startedAt": "2026-08-10T14:02:11.123Z",
        "actor": "alice",
        "source": {"bucket": "dat-prod-user-space", "root": "alice/"},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
    }


def test_the_record_sits_at_the_archive_root_beside_the_data_it_describes():
    fake = _install()

    key = manifest.write("archive-bkt", _ROOT, _record())

    assert key == f"{_ROOT}_manifest.json"
    assert fake.puts[0]["Bucket"] == "archive-bkt"


def test_the_record_carries_everything_a_cross_check_needs_and_no_keys():
    """Counts and locations, never the object list: it is a cross-check that can only fire when
    something is already wrong, not a copy of the plan."""
    fake = _install()

    manifest.write("archive-bkt", _ROOT, _record())
    body = json.loads(fake.puts[0]["Body"])

    assert body["version"] == manifest.VERSION
    assert body["archivedAt"] == "2026-08-10T14:02:11.123Z"
    assert body["actor"] == "alice"
    assert body["source"] == {"bucket": "dat-prod-user-space", "root": "alice/"}
    assert (body["objectCount"], body["totalBytes"]) == (1204, 8_412_339_201)
    assert "objects" not in body


def test_the_storage_class_is_recorded_from_the_one_definition():
    """Never a literal here: whether a later CopyObject fails ``InvalidObjectState`` depends on
    this value, so a second home for it is how the copy verb and the restore verb come to
    disagree about what class the objects are actually in."""
    fake = _install()

    manifest.write("archive-bkt", _ROOT, _record())

    assert json.loads(fake.puts[0]["Body"])["storageClass"] == ARCHIVE_STORAGE_CLASS


def test_a_retryable_write_fault_stays_transient():
    _install(error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        manifest.write("archive-bkt", _ROOT, _record())


def test_no_restore_verb_requires_the_manifest():
    """SPEC-169 FR-006 AC3, now that SPEC-170 has arrived and the tripwire has fired once.

    The restore rebuilds every destination by listing the archive prefix and running each key
    through ``paths.origin_key`` — the archived key encodes its own origin — exactly as SPEC-143
    judges a table by its shape rather than by the marker it also writes. That is what makes a
    lost, truncated or hand-edited manifest unable to make a restore WRONG rather than merely
    unavailable.

    SPEC-170 reads the record for its count cross-check, which the sweep caught and which is
    allowed: the property is that no restore path REQUIRES it, and ``arcommon.restore`` tolerates
    absent, unreadable and malformed alike. What stays forbidden is a VERB naming the basename —
    the cross-check has one home, tested once, and a verb reaching past it has grown its own rule
    about a file this arc deliberately made optional.
    """
    offenders = [name for name, uses in _basename_users().items() if uses and name not in _ALLOWED]

    assert not offenders, (
        f"{offenders} read {manifest.BASENAME} — a restore that depends on the record can be "
        "made wrong by a lost or edited file, which is what the self-describing archive key "
        "exists to prevent"
    )


def test_the_only_verb_that_may_name_the_record_is_the_one_that_writes_it():
    """The half of the rule the exemption above could otherwise swallow, and it is asserted
    against ``_ALLOWED`` itself rather than against the sweep's output.

    An earlier version of this test filtered the sweep's offenders — which made it a strict SUBSET
    of the test above and therefore unable to fail on its own, the exact "test that cannot fail"
    shape SPEC-163 records. What it checks now is the exemption LIST: adding a verb to it, which is
    how a future spec would quietly reach for the record, fails here and nowhere else.

    ``arcommon/plan.py`` and ``arcommon/restore.py`` are layer modules and are allowed. A VERB is
    not, including the ones SPEC-171 has not written yet.
    """
    verbs = {name for name in _ALLOWED if name.startswith(_VERB_PREFIXES)}

    assert verbs == _ALLOWED_VERBS, (
        f"{sorted(verbs - _ALLOWED_VERBS)} were exempted from the record sweep — the cross-check "
        "belongs to arcommon.restore and the collision guard to arcommon.plan, where each has one "
        "home and one tested behaviour"
    )


def test_the_manifest_sweep_would_see_a_reader():
    """Guards the guard, twice over.

    The sweep is a negative claim over a glob, and a glob that matches nothing passes it
    silently. It also reads the AST rather than the file's text, because the basename appears in
    several module DOCSTRINGS explaining the write ordering — a text scan flags those, and a
    sweep that has to be silenced with exceptions is a sweep nobody will keep.
    """
    users = _basename_users()

    assert len(users) > 5, "the sweep is reading the wrong files"
    assert {name for name, uses in users.items() if uses} == _ALLOWED
    assert manifest.BASENAME in pathlib.Path(receipt_module_path()).read_text(), (
        "the docstring case this sweep is written to tolerate has gone, so the AST walk is no "
        "longer being tested against it"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
