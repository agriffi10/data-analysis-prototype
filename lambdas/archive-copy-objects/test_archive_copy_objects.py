"""Unit tests for the archive copy-objects Lambda (SPEC-169 FR-003).

The Distributed Map's batch copier. The engine is ``cpcommon.transfer`` and has its own suite —
including the per-item storage class this plane is the first caller of — so what is tested here is
the thin verb: the batch shape the ItemBatcher hands it, the outcome shape the collector reads
back, and the deliberate absence of a raise on a deterministic per-item fault.

Runnable under pytest or directly: python3 test_archive_copy_objects.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

import archive_copy_objects as m
import pytest
from cpcommon import clients
from cpcommon.errors import TransientError

_ARCHIVE_ROOT = "personal/alice/archive/9f2c1b8e-1111-4222-8333-444444444444/"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, fail_on=(), error=None):
        self.copies = []
        self._fail_on = set(fail_on)
        self._error = error or _S3Error("AccessDenied")

    def copy_object(self, Bucket, Key, CopySource, **extra):
        if CopySource["Key"] in self._fail_on:
            raise self._error
        self.copies.append({"Key": Key, "Source": CopySource["Key"], **extra})
        return {}


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _batch(count=3, storage_class="GLACIER"):
    return {
        "Items": [
            {
                "srcBucket": "user-bkt",
                "srcKey": f"alice/reports/f{i}.csv",
                "destBucket": "archive-bkt",
                "destKey": f"{_ARCHIVE_ROOT}reports/f{i}.csv",
                "size": 10,
                "storageClass": storage_class,
            }
            for i in range(count)
        ]
    }


def test_every_item_in_the_batch_is_copied_at_the_manifests_storage_class():
    """The class travels per ITEM rather than being configured on the verb: the manifest is the
    only thing that knows where these objects are going."""
    fake = _install()

    outcome = m.handler(_batch(), None)

    assert outcome == {"copied": 3, "failures": []}
    assert {copy["StorageClass"] for copy in fake.copies} == {"GLACIER"}
    assert {copy["Key"] for copy in fake.copies} == {
        f"{_ARCHIVE_ROOT}reports/f{i}.csv" for i in range(3)
    }


def test_a_deterministic_item_failure_reports_itself_and_succeeds_the_batch():
    """One unreadable key must not cost its siblings their copy. The batch SUCCEEDS carrying the
    failure, which is what files it under SUCCEEDED_n.json — where the collector reads it and the
    commit gate refuses the whole archive over it."""
    _install(fail_on={"alice/reports/f1.csv"})

    outcome = m.handler(_batch(), None)

    assert outcome["copied"] == 2
    assert [failure["reason"] for failure in outcome["failures"]] == ["copy_failed"]


def test_a_transient_failure_raises_so_the_map_retries_the_whole_batch():
    """The copy is idempotent and the destination is execution-scoped, so re-running a batch is
    safe — and a throttle terminalized into a per-item failure would refuse an archive that only
    needed a retry."""
    _install(fail_on={"alice/reports/f0.csv"}, error=_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        m.handler(_batch(), None)


def test_an_empty_batch_is_not_an_error():
    """The Map can hand a child an empty batch at the tail of a manifest, and a raise there would
    fail a run that had copied everything."""
    _install()

    assert m.handler({"Items": []}, None) == {"copied": 0, "failures": []}


def test_the_outcome_carries_the_count_the_collector_reconciles_against():
    """``copied`` is what lets the collector check the export against the manifest rather than
    trust it — a FAILED-only reading of the export reports universal success, and on this plane
    that reported success is a deletion."""
    _install()

    outcome = m.handler(_batch(count=5), None)

    assert outcome["copied"] == 5
    assert set(outcome) == {"copied", "failures"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
