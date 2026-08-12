"""The archive plane's constants, and the bounds they are supposed to hold.

Every cap here is COMPUTED against the thing that sizes it rather than asserted as a number.
A hard-coded number in a test restates the constant; it does not check it, and it hides a
wrong model — which on this plane means a request the Pipe cannot start, or a state that
breaches 256 KB and raises States.DataLimitExceeded outside every Catch.
"""

import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import config

#: Step Functions' hard cap on a state payload AND on an execution input. Breaching either
#: raises States.DataLimitExceeded, which is thrown OUTSIDE every Catch.
_STATE_PAYLOAD_LIMIT = 256 * 1024

#: S3's own maximum key length. The worst case a cap has to survive, not the typical one.
_MAX_S3_KEY = 1024


# ── FR-002: the storage class is the single definition, and it is GLACIER ────


def test_the_storage_class_is_glacier():
    assert config.ARCHIVE_STORAGE_CLASS == "GLACIER"


def test_the_storage_class_is_one_of_the_three_archival_classes():
    """A typo here would not fail an apply — S3 rejects an unknown class at COPY time, per
    object, halfway through a transfer that has already started deleting nothing yet but has
    spent real time."""
    assert config.ARCHIVE_STORAGE_CLASS in config.GLACIER_CLASSES


def test_no_verb_hard_codes_the_storage_class_literal():
    """FR-002 AC1: ONE definition. A second literal is how the copy verb and the restore verb
    come to disagree about what class the objects are actually in — which is not a cosmetic
    disagreement, because whether a CopyObject fails InvalidObjectState depends on it."""
    plane = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for root, _dirs, files in os.walk(plane):
        if "__pycache__" in root or not os.path.basename(root).startswith(("archive-", "arcommon")):
            continue
        for name in files:
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            path = os.path.join(root, name)
            if os.path.abspath(path) == os.path.abspath(config.__file__):
                continue
            body = pathlib.Path(path).read_text()
            if re.search(r'"(GLACIER|GLACIER_IR|DEEP_ARCHIVE)"', body):
                offenders.append(path)

    assert not offenders, f"storage-class literal outside arcommon.config: {offenders}"


def test_the_restore_path_is_not_conditional_on_the_class():
    """FR-002 AC4. Setting this to GLACIER_IR must not silently bypass SPEC-171's restore
    machinery: a class that needs no restore still TOLERATES one being requested, and making
    the machinery conditional on a constant is how a config change deletes a code path with
    nothing to show for it in a diff.

    Asserted as the absence of any branch on the constant anywhere on the plane, which is the
    form the mistake would take.
    """
    plane = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for root, _dirs, files in os.walk(plane):
        if "__pycache__" in root or not os.path.basename(root).startswith(("archive-", "arcommon")):
            continue
        for name in files:
            if not name.endswith(".py") or name.startswith("test_"):
                continue
            body = pathlib.Path(root, name).read_text()
            for line in body.splitlines():
                if "ARCHIVE_STORAGE_CLASS" in line and re.match(r"\s*(if|elif|assert|while)\b", line):
                    offenders.append(f"{name}: {line.strip()}")

    assert not offenders, f"the restore path must be unconditional: {offenders}"


# ── FR-005: the item cap, and what actually sizes it ─────────────────────────


def test_the_item_cap_fits_the_per_item_work_inside_the_validators_timeout():
    """COMPUTED against the thing that sizes it, not restated. An earlier version asserted
    `200 % 25 == 0` — which is arithmetic about the file browser's page size and says nothing
    about whether the cap is safe.

    What sizes it is the per-item work: the two containment rules and the reserved-root scan
    here (pure string work, microseconds), and in SPEC-169 **one round trip per ITEM** — a
    `ListObjectsV2` walk for a folder, a serial `HeadObject` for a file. The per-item cost is
    therefore a NETWORK round trip, and the file case is the binding one because 200 files is
    200 serial round trips where 20,000 objects in one folder is 20 paged ones.

    The budget is validate-authorize's own 15-second timeout (`locals.tf`, READ BACK here so
    lowering it fails the build) minus a cold start. SPEC-169's expansion runs in its own verb
    with its own longer timeout, so this bounds THIS verb.
    """
    locals_tf = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "infra" / "modules" / "archive" / "locals.tf"
    ).read_text()
    block = locals_tf[locals_tf.index('"validate-authorize"'):]
    timeout = int(re.search(r"timeout = (\d+)", block).group(1))

    # Conservative: 25 ms per S3 round trip, and 3 s of the budget spent on a cold start plus
    # the JWKS fetch and the registry read that precede the loop.
    worst_case_seconds = config.ARCHIVE_MAX_ITEMS * 0.025
    assert worst_case_seconds < timeout - 3, (
        f"{config.ARCHIVE_MAX_ITEMS} items is ~{worst_case_seconds:.1f}s of serial round trips "
        f"against a {timeout}s verb timeout"
    )


def test_a_count_cap_cannot_bound_the_bytes_and_that_is_why_there_are_two():
    """S3 keys are arbitrary UTF-8, and JSON escaping expands a control character to six
    bytes. Computed, not asserted: at the count cap alone the worst case is several times the
    payload limit, which is the whole reason ARCHIVE_MAX_ITEM_BYTES exists."""
    worst = [{"kind": "file", "key": "\x01" * _MAX_S3_KEY} for _ in range(config.ARCHIVE_MAX_ITEMS)]
    serialized = len(json.dumps(worst, separators=(",", ":")).encode())

    assert serialized > _STATE_PAYLOAD_LIMIT, (
        f"the count cap alone bounds the selection at {serialized:,} bytes, inside the "
        f"{_STATE_PAYLOAD_LIMIT:,}-byte limit — so this test no longer demonstrates why the "
        "byte cap exists"
    )


def test_the_byte_cap_survives_every_link_of_the_chain_it_bounds():
    """THE MIDDLE LINK IS THE ONE AN OBVIOUS MODEL MISSES, and file-send got it wrong once at
    a value measured against the validated output alone — which would have permitted a request
    whose execution could not start at all.

    The chain: the browser's SQS body carries the selection; the EventBridge Pipe wraps that
    body into a record as an ESCAPED JSON STRING and hands it to StartExecution as the
    execution input; Step Functions caps that input at 256 KB exactly as it caps a state.
    Escaping is not a rounding error — every `"` the selection already spent two bytes on
    costs four in the record.

    All three links are computed here, so changing one without the others fails the build.
    """
    # A quote-heavy selection at exactly the byte cap: the worst case the cap admits.
    at_cap = "x" + '"' * (config.ARCHIVE_MAX_ITEM_BYTES // 2)
    body = json.dumps(
        {
            "requestId": "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f",
            "mode": "archive",
            "actor": {"idToken": "e" * 2048},
            "source": {"space": {"kind": "personal", "name": "a" * 63}, "items": at_cap},
        },
        separators=(",", ":"),
    )

    # LINK 1 — the SQS body itself.
    assert len(body.encode()) < _STATE_PAYLOAD_LIMIT

    # LINK 2 — the Pipe's record, which carries the body as an ESCAPED STRING.
    record = json.dumps([{"messageId": "m" * 36, "body": body}], separators=(",", ":"))
    assert len(record.encode()) < _STATE_PAYLOAD_LIMIT, (
        f"a selection at ARCHIVE_MAX_ITEM_BYTES reaches {len(record.encode()):,} bytes once the "
        f"Pipe escapes it into StartExecution's input — over the {_STATE_PAYLOAD_LIMIT:,}-byte "
        "limit, so the execution could not start and no state would exist to refuse it"
    )

    # LINK 3 — the validated state the verb returns, which carries the selection again plus
    # the resolved source and archive blocks.
    validated = json.dumps(
        {
            "requestId": "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f",
            "mode": "archive",
            "actor": {"username": "a" * 63},
            "source": {"bucket": "b" * 63, "root": "a" * 64, "kind": "personal", "name": "a" * 63,
                       "items": at_cap},
            "archive": {"bucket": "b" * 63, "root": "personal/" + "a" * 63 + "/archive/" + "0" * 36 + "/",
                        "receiptBucket": "b" * 63, "receiptKey": "a" * 63 + "/archive/" + "0" * 36 + "/receipt.txt"},
        },
        separators=(",", ":"),
    )
    assert len(validated.encode()) < _STATE_PAYLOAD_LIMIT


# ── FR-005: the reserved list ────────────────────────────────────────────────


def test_every_reserved_root_is_a_bare_folder_name():
    """A trailing slash or a leading one here would silently stop the anchored comparison in
    `assert_not_reserved` from matching anything, and the rule would pass by refusing nothing."""
    for folder in config.RESERVED_SOURCE_ROOTS:
        assert folder and not folder.startswith("/") and not folder.endswith("/")


def test_the_reserved_list_has_no_duplicates():
    assert len(set(config.RESERVED_SOURCE_ROOTS)) == len(config.RESERVED_SOURCE_ROOTS)


# ── The archive bucket is read from the env, and only on demand ──────────────


def test_the_archive_bucket_is_a_function_so_the_layer_stays_import_safe():
    """A constant resolved at import time in a layer module runs for every attaching function
    whether or not it uses the value, and an unset variable then crashes at COLD START, where
    no test and no deploy can see it (PR #196)."""
    assert callable(config.archive_bucket)
    assert not hasattr(config, "ARCHIVE_BUCKET")


def test_the_archive_bucket_raises_where_it_is_read_when_the_variable_is_unset():
    previous = os.environ.pop("ARCHIVE_BUCKET", None)
    try:
        with pytest.raises(RuntimeError) as caught:
            config.archive_bucket()
        assert "ARCHIVE_BUCKET" in str(caught.value)
    finally:
        if previous is not None:
            os.environ["ARCHIVE_BUCKET"] = previous


def test_the_archive_bucket_is_not_in_cpcommons_fleet_wide_required_set():
    """That set is a contract EVERY plane's Lambda environment must satisfy, asserted per
    plane by test_the_common_environment_satisfies_every_import_time_require. A variable only
    this plane sets belongs in this layer, not there — putting it there fails every other
    plane's guard, which is how this was caught while it was being written."""
    from cpcommon import config as cpconfig

    assert "ARCHIVE_BUCKET" not in cpconfig._REQUIRED_VARS.values()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
