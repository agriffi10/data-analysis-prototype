"""Unit tests for the data-quality byte-scan Lambda (SPEC-112 FR-001).

Pure logic, AWS stubbed: the S3 client and the manifest read are replaced on the verb, so
no bucket is touched.

TWO BOUNDS ARE UNDER TEST, and they fail differently — the spec's whole point is that the
first one is not enough on its own:

  BYTES    — never more than DQ_SCAN_TOTAL_BYTES, whatever the file count or file size.
             Breaking it times out a 300 s function on ~276 GB.
  REQUESTS — never more than ~1000 GetObjects. Breaking it times out the SAME function on
             21,000 round trips while reading a perfectly legal 2 GiB.

The bound tests shrink the budget via monkeypatch rather than moving 2 GiB through a unit
test; the REAL constants are exercised by the pure-planning tests over _regions, which need
no I/O at all.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TransientError  # noqa: E402
from dqcommon import config  # noqa: E402

import dq_byte_scan as v  # noqa: E402

BUCKET = "dq-user-bkt"
MANIFEST_KEY = "alice/_data-quality-reports/req-1/manifest.json"

GIB = 1024**3


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError enough for cpcommon.errors.error_code.

    botocore ships in the Lambda RUNTIME but is not a test dependency of this repo, so the
    suites fake it rather than import it (matching the sibling verb suites).
    """

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeBody:
    """A streaming body. Either real bytes, or ``length`` synthetic ones.

    The synthetic mode is what lets a 250 GB file be a test fixture: the bytes are
    generated a chunk at a time and never held, exactly as the verb reads them.
    """

    def __init__(self, data=None, length=0, mid_stream_error=None):
        self.data = data
        self.length = length
        self.mid_stream_error = mid_stream_error

    def iter_chunks(self, size):
        if self.data is not None:
            for start in range(0, len(self.data), size):
                yield self.data[start : start + size]
                # Faults DURING the transfer, which is where a dropped connection actually
                # lands — not on the request that opened it.
                if self.mid_stream_error:
                    raise self.mid_stream_error
            return
        remaining = self.length
        while remaining > 0:
            take = min(size, remaining)
            yield b"a" * take
            remaining -= take


class _FakeS3:
    """Records every ranged GET and serves content (real or synthetic)."""

    def __init__(self, content=None, error=None, mid_stream_error=None):
        self.content = content or {}
        self.error = error
        self.mid_stream_error = mid_stream_error
        self.gets = []
        self.bytes_served = 0

    def get_object(self, Bucket, Key, Range=None):  # noqa: N803 - boto3's kwarg casing
        if self.error:
            raise self.error
        span = Range.removeprefix("bytes=")
        start, end = (int(part) for part in span.split("-"))
        self.gets.append((Key, start, end))
        if Key in self.content:
            data = self.content[Key][start : end + 1]
            # S3 answers a range past the end of an object with 416, not a short read.
            if start >= len(self.content[Key]):
                raise _FakeClientError("InvalidRange")
            self.bytes_served += len(data)
            return {"Body": _FakeBody(data=data, mid_stream_error=self.mid_stream_error)}
        self.bytes_served += end - start + 1
        return {"Body": _FakeBody(length=end - start + 1, mid_stream_error=self.mid_stream_error)}


def _setup(monkeypatch, files, fmt="csv", content=None, error=None, mid_stream_error=None):
    """Install a fake S3 + manifest and return the fake."""
    fake = _FakeS3(content=content, error=error, mid_stream_error=mid_stream_error)
    monkeypatch.setattr(v.clients, "s3", lambda: fake)
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: {"files": files})
    return fake


def _event(fmt="csv"):
    return {
        "requestId": "req-1",
        "actor": "alice",
        "space": {"bucket": BUCKET, "prefix": "alice/"},
        "manifestKey": MANIFEST_KEY,
        "format": fmt,
    }


def _shrink(monkeypatch, total=4096, min_sample=64):
    """Shrink the budget so a bound can be asserted without moving gigabytes."""
    monkeypatch.setattr(config, "DQ_SCAN_TOTAL_BYTES", total)
    monkeypatch.setattr(config, "DQ_SCAN_MIN_SAMPLE_BYTES", min_sample)


# ── The text-only gate (FR-001) ──────────────────────────────────────────────


def test_parquet_is_skipped_without_reading_a_byte(monkeypatch):
    fake = _setup(monkeypatch, [{"key": "alice/s/a.parquet", "size": 10 * GIB}], fmt="parquet")

    out = v.handler(_event(fmt="parquet"), None)

    assert out["encoding"] == {"status": "skipped", "reason": v.SKIP_BINARY}
    assert fake.gets == []


def test_an_all_gzip_source_is_skipped_without_reading_a_byte(monkeypatch):
    fake = _setup(
        monkeypatch,
        [{"key": "alice/s/a.csv.gz", "size": 5}, {"key": "alice/s/b.csv.gz", "size": 5}],
    )

    out = v.handler(_event(), None)

    assert out["encoding"] == {"status": "skipped", "reason": v.SKIP_COMPRESSED}
    assert fake.gets == []


def test_a_gzip_sibling_is_skipped_but_the_plain_files_are_still_scanned(monkeypatch):
    """One .gz file must not cost the whole folder its encoding figure."""
    content = {"alice/s/a.csv": b"id,name\n1,ok\n"}
    fake = _setup(
        monkeypatch,
        [
            {"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])},
            {"key": "alice/s/b.csv.gz", "size": 900},
        ],
        content=content,
    )

    out = v.handler(_event(), None)["encoding"]

    assert out["filesScanned"] == 1
    assert out["filesSkipped"] == 1
    # The .gz bytes are NOT in the denominator: they were never scannable, and counting
    # them would depress the coverage percentage for a reason that has nothing to do with
    # sampling.
    assert out["bytesTotal"] == len(content["alice/s/a.csv"])
    assert [key for key, _, _ in fake.gets] == ["alice/s/a.csv"]


@pytest.mark.parametrize("key", ["alice/s/A.CSV.GZ", "alice/s/a.csv.Gz", "alice/s/A.Csv.gZ"])
def test_an_uppercase_gzip_extension_is_still_skipped(monkeypatch, key):
    """inspect-source lowercases before classifying, so SALES.CSV.GZ enters the manifest as
    compressed csv. A case-SENSITIVE test here would hand its DEFLATE output to the UTF-8
    decoder — about 42 fabricated findings per 100 bytes, i.e. a confident corruption
    report over a file that is fine, on exactly the Windows-tooling population this check
    is aimed at."""
    fake = _setup(monkeypatch, [{"key": key, "size": 5}])

    out = v.handler(_event(), None)

    assert out["encoding"] == {"status": "skipped", "reason": v.SKIP_COMPRESSED}
    assert fake.gets == []


# ── Coverage: complete vs sampled (FR-001) ───────────────────────────────────


def test_a_file_read_in_full_is_complete(monkeypatch):
    content = {"alice/s/a.csv": b"id,name\n1,alice\n2,bob\n"}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "complete"
    assert out["bytesExamined"] == out["bytesTotal"] == len(content["alice/s/a.csv"])
    assert out["invalidUtf8Sequences"] == 0


def test_a_file_larger_than_its_share_is_sampled(monkeypatch):
    _shrink(monkeypatch)
    _setup(monkeypatch, [{"key": "alice/s/big.csv", "size": 250 * GIB}])

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "sampled"
    assert out["bytesExamined"] <= config.DQ_SCAN_TOTAL_BYTES
    assert out["bytesTotal"] == 250 * GIB
    # The figure the report turns into a coverage percentage — vanishingly small, and that
    # is the honest answer rather than a bigger budget.
    assert out["bytesExamined"] / out["bytesTotal"] < 0.001


@pytest.mark.parametrize("sampled_first", [True, False])
def test_one_sampled_file_makes_the_whole_figure_sampled(monkeypatch, sampled_first):
    """Parametrized on ORDER: a reduce written as `complete = in_full` rather than
    `complete = complete and in_full` still passes when the sampled file happens to come
    last, and reports a 250 GB folder as fully examined when it comes first."""
    _shrink(monkeypatch)
    content = {"alice/s/small.csv": b"ok\n"}
    files = [
        {"key": "alice/s/big.csv", "size": 250 * GIB},
        {"key": "alice/s/small.csv", "size": 3},
    ]
    _setup(monkeypatch, files if sampled_first else files[::-1], content=content)

    assert v.handler(_event(), None)["encoding"]["coverage"] == "sampled"


def test_a_file_exactly_the_size_of_its_share_is_complete(monkeypatch):
    """FR-001's boundary: read IN FULL WITHIN its share. The planner and the coverage
    verdict must agree on which side `==` falls, or coverage lies in the reassuring
    direction."""
    _shrink(monkeypatch, total=20, min_sample=2)
    content = {"alice/s/a.csv": b"a" * 20}
    fake = _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 20}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "complete"
    assert out["bytesExamined"] == 20
    # ONE contiguous read, which is the whole reason the boundary is `<=`. Falling to the
    # sampled branch here still reads all 20 bytes, so no figure would look wrong — it just
    # spends six round trips to do it, and that cost is invisible except right here.
    assert len(fake.gets) == 1


def test_skipped_files_make_the_figure_sampled_however_complete_the_rest_was(monkeypatch):
    """One tiny .csv beside ninety-nine 1 GiB .csv.gz files must not read "complete".

    Otherwise the coverage figure reads cleanest exactly where it has looked least: 100% of
    13 bytes, over a folder holding 99 GB nobody examined.
    """
    content = {"alice/s/a.csv": b"id,name\n1,ok\n"}
    files = [{"key": "alice/s/a.csv", "size": 13}]
    files += [{"key": f"alice/s/{i}.csv.gz", "size": GIB} for i in range(99)]
    _setup(monkeypatch, files, content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "sampled"
    assert out["filesSkipped"] == 99


# ── Invalid UTF-8 (FR-001) ───────────────────────────────────────────────────


def test_invalid_utf8_is_counted_with_its_offset_and_file(monkeypatch):
    # 0xE9 is Latin-1 'e-acute' — a UTF-8 lead byte followed by a non-continuation, i.e.
    # exactly what a Windows-codepage export from Excel looks like.
    content = {"alice/s/a.csv": b"id,name\n1,caf\xe9,x\n"}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["invalidUtf8Sequences"] == 1
    assert out["sampleOffsets"] == [{"key": "alice/s/a.csv", "offset": 13}]


def test_the_offset_sample_is_capped_at_ten(monkeypatch):
    content = {"alice/s/a.csv": b"\xe9," * 50}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["invalidUtf8Sequences"] == 50  # the COUNT is not capped
    assert len(out["sampleOffsets"]) == config.DQ_OFFSET_SAMPLE


def test_the_offset_sample_stays_capped_across_many_files(monkeypatch):
    content = {f"alice/s/{i}.csv": b"\xe9\xe9\n" for i in range(20)}
    _setup(
        monkeypatch,
        [{"key": key, "size": len(body)} for key, body in content.items()],
        content=content,
    )

    out = v.handler(_event(), None)["encoding"]

    assert out["invalidUtf8Sequences"] == 40
    assert len(out["sampleOffsets"]) == config.DQ_OFFSET_SAMPLE


def test_offsets_stay_absolute_across_read_chunks(monkeypatch):
    """The offset must be the position IN THE FILE, not in the chunk it was found in.

    Nothing else pins the base arithmetic: a single-chunk fixture has base 0 everywhere, so
    zeroing the running base — or dropping the advance — passes a suite that only ever
    looks at small files. The field exists so an operator can go and look at the byte.
    """
    monkeypatch.setattr(config, "DQ_SCAN_READ_CHUNK_BYTES", 4)
    content = {"alice/s/a.csv": b"aaaaaaaa\xe9,zzz"}  # the bad byte is at offset 8
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 13}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["sampleOffsets"] == [{"key": "alice/s/a.csv", "offset": 8}]


def test_offsets_stay_absolute_inside_a_sampled_region(monkeypatch):
    """A ranged region starts partway into the file, and its offsets must say so."""
    _shrink(monkeypatch, total=8, min_sample=2)
    # share 8 -> head (0,4), then samples at (4,2) and (12,2). The bad byte sits at 12,
    # inside the LAST region — a region that does not start at zero.
    content = {"alice/s/a.csv": b"a" * 12 + b"\xe9" + b"a" * 7}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 20}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["sampleOffsets"] == [{"key": "alice/s/a.csv", "offset": 12}]


def test_the_offset_list_is_bounded_even_on_a_wholly_corrupt_file(monkeypatch):
    """MEMORY, not cosmetics. Retaining an offset per bad sequence is ~42 bytes each, and a
    mis-encoded 250 MB export holds tens of millions — over a gigabyte in a 1024 MB
    function, i.e. an OOM on precisely the file this check exists to diagnose. Avoiding the
    quadratic CPU path only to blow up on memory is the same bug in a different costume."""
    content = {"alice/s/a.csv": b"\xe9" * 20_000}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 20_000}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["invalidUtf8Sequences"] == 20_000  # the COUNT is exact
    assert len(v._found) <= config.DQ_OFFSET_SAMPLE  # the RETAINED offsets are not


def test_a_clean_multibyte_file_reports_nothing(monkeypatch):
    content = {"alice/s/a.csv": "id,name\n1,café ☕\n".encode()}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    assert v.handler(_event(), None)["encoding"]["invalidUtf8Sequences"] == 0


# ── Read boundaries must not invent findings ─────────────────────────────────


def test_a_character_split_across_read_chunks_is_not_counted(monkeypatch):
    """The regression this guards: findings proportional to file size on a clean file.

    Without the carry, a 3-byte character straddling a chunk boundary is counted TWICE —
    once as a truncated lead byte, once as a stray continuation — on a file that is
    perfectly valid UTF-8.
    """
    monkeypatch.setattr(config, "DQ_SCAN_READ_CHUNK_BYTES", 3)
    content = {"alice/s/a.csv": "aa☕bb".encode()}  # the 3-byte char starts at byte 2
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(content["alice/s/a.csv"])}], content=content)

    assert v.handler(_event(), None)["encoding"]["invalidUtf8Sequences"] == 0


def test_a_character_truncated_at_end_of_file_is_counted(monkeypatch):
    """At EOF a partial character is real corruption — a file cut off mid-character."""
    content = {"alice/s/a.csv": b"aa\xe2\x98"}  # a 3-byte char with its last byte missing
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 4}], content=content)

    assert v.handler(_event(), None)["encoding"]["invalidUtf8Sequences"] == 1


def test_a_character_truncated_at_a_region_edge_is_not_counted(monkeypatch):
    """Mid-file, a partial character at the edge of a sampled window is the WINDOW's edge.

    The rest of that character sits in bytes the budget did not buy. Counting it would
    invent a finding, and it would do so more often the more the source is sampled.
    """
    _shrink(monkeypatch, total=4, min_sample=64)
    content = {"alice/s/a.csv": "☕☕☕☕".encode()}  # 12 bytes; the 4-byte share cuts one
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 12}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "sampled"
    assert out["invalidUtf8Sequences"] == 0


@pytest.mark.parametrize(
    "buf,decodable,carry",
    [
        (b"abc", b"abc", b""),                      # all ASCII
        (b"a\xe2\x98\x95", b"a\xe2\x98\x95", b""),  # a complete 3-byte char
        (b"a\xe2\x98", b"a", b"\xe2\x98"),          # 3-byte char, one byte short
        (b"a\xc3", b"a", b"\xc3"),                  # 2-byte char, one byte short
        (b"a\xf0\x9f\x92", b"a", b"\xf0\x9f\x92"),  # 4-byte char, one byte short
    ],
)
def test_split_trailing_partial(buf, decodable, carry):
    assert v._split_trailing_partial(buf) == (decodable, carry)


# ── The two bounds ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("file_count", [1, 2, 100, 1000])
def test_bytes_read_never_exceed_the_total_budget(monkeypatch, file_count):
    """THE bound. A per-FILE budget passes a three-file fixture and fails this."""
    _shrink(monkeypatch)
    _setup(
        monkeypatch,
        [{"key": f"alice/s/{i}.csv", "size": 250 * GIB} for i in range(file_count)],
    )

    out = v.handler(_event(), None)["encoding"]

    assert out["bytesExamined"] <= config.DQ_SCAN_TOTAL_BYTES


def test_bytes_read_do_not_grow_with_file_size(monkeypatch):
    _shrink(monkeypatch)
    reads = []
    for size in (10 * GIB, 250 * GIB):
        _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": size}])
        reads.append(v.handler(_event(), None)["encoding"]["bytesExamined"])

    assert reads[0] == reads[1] <= config.DQ_SCAN_TOTAL_BYTES


def test_bytes_read_do_not_grow_with_file_count(monkeypatch):
    _shrink(monkeypatch)
    reads = []
    for count in (1, 1000):
        _setup(
            monkeypatch,
            [{"key": f"alice/s/{i}.csv", "size": 250 * GIB} for i in range(count)],
        )
        reads.append(v.handler(_event(), None)["encoding"]["bytesExamined"])

    assert max(reads) <= config.DQ_SCAN_TOTAL_BYTES


@pytest.mark.parametrize("file_count", [1, 2, 12, 100, 256, 1000])
def test_the_real_budget_bounds_bytes_and_requests(file_count):
    """The bounds at the SHIPPED constants — planning only, so it needs no I/O.

    The request bound is the one the byte budget does not give you: a flat
    1 + DQ_SCAN_SAMPLE_COUNT reads per file is 21,000 GetObjects on a 1000-file manifest,
    ~630 s of round trips against a 300 s function, while reading a legal 2 GiB.
    """
    share = config.DQ_SCAN_TOTAL_BYTES // file_count
    regions = [v._regions(250 * GIB, share) for _ in range(file_count)]

    planned_bytes = sum(length for file_regions in regions for _, length in file_regions)
    planned_gets = sum(len(file_regions) for file_regions in regions)

    assert planned_bytes <= config.DQ_SCAN_TOTAL_BYTES
    assert planned_gets <= 1000


def test_a_small_file_is_planned_as_one_whole_read():
    assert v._regions(500, 4096) == [(0, 500)]


def test_an_empty_file_is_planned_as_no_reads_at_all():
    assert v._regions(0, 4096) == []


def test_a_large_file_leads_with_a_head_window():
    regions = v._regions(250 * GIB, config.DQ_SCAN_TOTAL_BYTES)

    assert regions[0][0] == 0
    assert regions[0][1] == int(config.DQ_SCAN_TOTAL_BYTES * config.DQ_SCAN_HEAD_FRACTION)
    assert len(regions) == 1 + config.DQ_SCAN_SAMPLE_COUNT
    # Every sample starts AT OR AFTER the head window. Samples that restart from zero would
    # re-read bytes the head already covered — spending the budget twice on the same bytes
    # while reporting the coverage of a scan that had looked further.
    assert all(start >= regions[0][1] for start, _ in regions[1:])
    # Spread across the file, not clustered at the front — a corruption in the tail of a
    # 250 GB export is still reachable.
    assert regions[-1][0] > 200 * GIB


@pytest.mark.parametrize(
    "size",
    # 17 MiB against the 16 MiB share is the shape that matters: a file only just larger
    # than its share, where the samples have the least room to fit behind the head window.
    [4097, 5000, 10_000, 1_000_000, 17 * 1024**2, 33 * 1024**2, 250 * GIB],
)
@pytest.mark.parametrize(
    "share", [4096, 64 * 1024, 16 * 1024**2, 32 * 1024**2, config.DQ_SCAN_TOTAL_BYTES]
)
def test_planned_regions_never_read_past_the_end_of_the_file(size, share):
    """The invariant that makes clipping the final sample unnecessary (see _regions).

    A range that starts beyond EOF is a 416 from S3, and one that overruns it quietly
    reads fewer bytes than the plan claims — which would make bytesExamined disagree with
    the coverage percentage the report prints.
    """
    for start, length in v._regions(size, share):
        assert start + length <= size


def test_samples_are_dropped_when_the_share_cannot_afford_one():
    """The request-count floor: at 1000 files the whole share goes to the head window."""
    share = config.DQ_SCAN_TOTAL_BYTES // 1000

    assert len(v._regions(250 * GIB, share)) == 1


# ── Faults ───────────────────────────────────────────────────────────────────


def test_a_throttled_read_raises_transient_so_the_state_machine_retries(monkeypatch):
    """Every Athena query has already run by here — a SlowDown must not lose the check."""
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 10}], error=_FakeClientError("SlowDown"))

    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_fault_midway_through_the_transfer_is_also_mapped_to_transient(monkeypatch):
    """The bytes move during iter_chunks, not during get_object.

    A read timeout or reset connection arrives there, with no error code, and reaches Step
    Functions as its own class name — which the ByteScan Retry list does not name. One
    dropped connection across the ~1000 reads a 2 GiB budget spans would then fail the
    request permanently, after all three Athena queries had already been paid for.
    """
    content = {"alice/s/a.csv": b"a" * 64}
    _setup(
        monkeypatch,
        [{"key": "alice/s/a.csv", "size": 64}],
        content=content,
        mid_stream_error=_FakeClientError("RequestTimeout"),
    )
    monkeypatch.setattr(config, "DQ_SCAN_READ_CHUNK_BYTES", 8)

    with pytest.raises(TransientError):
        v.handler(_event(), None)


def test_a_range_past_a_shrunken_object_does_not_fail_the_whole_check(monkeypatch):
    """The manifest's size is a snapshot from inspect-source; the object can change.

    A 416 must cost that file some coverage, not cost the user their entire check — every
    Athena query has already run by this point.
    """
    _shrink(monkeypatch, total=8, min_sample=2)
    content = {"alice/s/a.csv": b"abcd"}  # the manifest claims 20 bytes; only 4 remain
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 20}], content=content)

    out = v.handler(_event(), None)["encoding"]

    assert out["coverage"] == "sampled"
    assert out["bytesExamined"] == 4


def test_a_denied_read_propagates_rather_than_being_retried(monkeypatch):
    """AccessDenied is not a hiccup — retrying it three times just delays the failure."""
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 10}], error=_FakeClientError("AccessDenied"))

    with pytest.raises(_FakeClientError):
        v.handler(_event(), None)


def test_the_request_object_is_threaded_through(monkeypatch):
    """RecordSuccess/RecordFailure hard-fail on an ABSENT JSONPath key (States.Runtime),
    which a Pass state cannot Catch — so dropping requestId/actor here would cost the user
    their notification entirely."""
    content = {"alice/s/a.csv": b"ok\n"}
    _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": 3}], content=content)

    out = v.handler(_event(), None)

    assert out["requestId"] == "req-1"
    assert out["actor"] == "alice"
    assert out["manifestKey"] == MANIFEST_KEY


# -- SPEC-132 FR-004: the highest-risk emitter in the plane ------------------------------


def test_it_narrates_offsets_and_never_the_bytes_at_them(monkeypatch, captured_events):
    """The verb's whole purpose is holding a user's raw bytes, and the natural debugging
    instinct is to log the sequence that failed to decode. That sequence IS the file, and
    `logs/` is retained forever. An offset and a key are enough to go and look.
    """
    bad = b"id,name\nx," + b"\xff\xfe" + b"payload-SECRET-BYTES\n"
    fake = _setup(monkeypatch, [{"key": "alice/s/a.csv", "size": len(bad)}], content={"alice/s/a.csv": bad})
    assert fake

    v.handler(_event(), None)

    scanned = captured_events.messages("scanned bytes")
    assert len(scanned) == 1
    fields = scanned[0]["fields"]
    assert fields["invalid"] >= 1, "the fixture must actually contain invalid UTF-8"
    assert fields["offsets"], "offsets are positions and ARE logged"
    assert fields["offset_keys"] == ["alice/s/a.csv"]
    assert all(isinstance(o, int) for o in fields["offsets"])

    dumped = json.dumps(captured_events.events)
    assert "SECRET-BYTES" not in dumped, "decoded file content reached a forever-retained store"
    assert "\\u00ff" not in dumped and "xff" not in dumped, "raw bytes reached the events"


def test_the_scan_is_one_span_however_many_files_and_regions(monkeypatch, captured_events):
    """FR-002: this verb iterates per file AND per region within a file, so a step one level
    down mints thousands of child spans for one invocation.
    """
    _shrink(monkeypatch, total=4096, min_sample=64)
    files = [{"key": f"alice/s/f{n}.csv", "size": 8192} for n in range(12)]
    _setup(monkeypatch, files)

    v.handler(_event(), None)

    assert len(captured_events.spans("scan")) == 1


def test_a_skipped_scan_says_why(monkeypatch, captured_events):
    _setup(monkeypatch, [{"key": "alice/s/a.parquet", "size": 10 * GIB}], fmt="parquet")

    v.handler(_event(fmt="parquet"), None)

    skipped = captured_events.messages("scan skipped")
    assert skipped and skipped[0]["fields"]["reason"] == v.SKIP_BINARY
    assert skipped[0]["fields"]["format"] == "parquet"
