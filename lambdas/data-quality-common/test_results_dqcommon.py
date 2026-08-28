"""The temp-table DDL output prefix, asserted against the literal it produced before the merge.

The risk is not a crash: a prefix built one character differently is inside a tree the Lake
Formation grant does not cover, and it surfaces as a denial on whichever path is exercised less.
So these are byte comparisons against the pre-consolidation f-strings rather than a round-trip
through the builder, which would agree with itself no matter what it built.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dqcommon import results


def test_the_temp_table_ddl_output_is_unchanged():
    """Was ``f"s3://{bucket}/{report_prefix.rstrip('/')}/ddl/"`` in create, and the same with an
    empty-prefix fallback in drop. Both callers had already trimmed, so the shapes agreed."""
    assert results.ddl_output("user-bkt", "alice/reports/req-1") == (
        "s3://user-bkt/alice/reports/req-1/ddl/"
    )
    assert results.ddl_output("user-bkt", "alice/reports/req-1/") == (
        "s3://user-bkt/alice/reports/req-1/ddl/"
    )


def test_an_absent_report_prefix_gives_the_bucket_root():
    """Drop's fallback, now shared. Create had no fallback and would have built `s3:///ddl/`
    from an empty prefix.

    Unreachable there, but NOT because the field is required — `events.require` only rejects
    a value that is blank after stripping, so `"/"` would pass it and rstrip to empty. The real
    guarantee is that `dq_validate_authorize._validate_destination` is the only writer of
    `reportPrefix` and builds it as `f"{space_root}/{REPORTS_PREFIX}/{request_id}/"`, which
    always contains a literal segment. The shared builder resolves the case to the location
    drop already used rather than to a broken URI."""
    assert results.ddl_output("user-bkt", "") == "s3://user-bkt/"
