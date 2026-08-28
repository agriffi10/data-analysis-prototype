"""Each plane's results prefix, asserted against the literal it produced before the merge.

SPEC-156 FR-003. The risk this FR names is not a crash: a prefix built one character
differently is inside a tree the Lake Formation grant does not cover, and it surfaces as a
denial on whichever path is exercised less. So the test is a byte comparison against the
pre-consolidation f-strings, transcribed here per plane, rather than a round-trip through the
builder that would agree with itself no matter what it built.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import results


def test_the_table_builder_prefix_is_unchanged():
    """Was ``f"s3://{space['bucket']}/{space['database']}/athenaresults/{actor}/"``.

    Distinct database and actor even though a personal space makes them equal, so this
    assertion can fail on a swapped argument by itself rather than leaning on its siblings.
    """
    assert results.results_location("user-bkt", "alice_db", "alice") == (
        "s3://user-bkt/alice_db/athenaresults/alice/"
    )
    assert results.results_location("user-bkt", "alice", "alice") == (
        "s3://user-bkt/alice/athenaresults/alice/"
    )


def test_the_table_builder_shared_space_prefix_is_unchanged():
    """The same construction with a shared space's bucket and database — the path SPEC-156's
    source comment says is the less-travelled one."""
    assert results.results_location("shared-bkt", "team_space", "alice") == (
        "s3://shared-bkt/team_space/athenaresults/alice/"
    )


def test_the_table_share_prefix_is_unchanged():
    """Was ``f"s3://{recipient['destBucket']}/{recipient['database']}/athenaresults/{actor}/"``.

    Identical to the table-builder's modulo the key names, which is why one builder can serve
    both: the sender's username under the RECIPIENT's database.
    """
    assert results.results_location("user-bkt", "bob", "alice") == (
        "s3://user-bkt/bob/athenaresults/alice/"
    )


def test_the_data_quality_prefix_is_unchanged_and_has_no_trailing_slash():
    """Was ``f"s3://{bucket}/{space_root}/athenaresults/data-quality/{request_id}"``.

    The genuinely different shape: a fixed plane segment where the others put the actor, the
    request id appended, and NO trailing slash. That difference is `sub`, kept as a parameter
    rather than normalised away.
    """
    assert results.results_location("user-bkt", "alice", "data-quality", sub="req-123") == (
        "s3://user-bkt/alice/athenaresults/data-quality/req-123"
    )


def test_no_plane_builds_an_athenaresults_prefix_by_hand():
    """The comment that was ignored twice, made executable.

    `tbcommon/results.py` explained why this must exist once; two more copies were written
    anyway. A grep is what stops a fourth.

    A tripwire, not a proof: hoisting the folder name to a module constant evades it. It
    catches the copy-paste, which is how the three copies actually arose.

    Matched per LINE and on `s3://` too, because naming the folder is not building a prefix:
    `s3_listing._IGNORED_SUBTREES` and `dqcommon.config`'s reserved list both name
    `athenaresults` in order to EXCLUDE it from a source listing, which is what keeps a check's
    own output from being read back as its input.
    """
    import pathlib

    lambdas = pathlib.Path(__file__).resolve().parent.parent
    owner = lambdas / "control-plane-common" / "cpcommon" / "results.py"
    offenders = sorted(
        f"{path.relative_to(lambdas)}:{number}"
        for path in lambdas.rglob("*.py")
        if "__pycache__" not in str(path)
        and path != owner
        and not path.name.startswith("test_")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "athenaresults" in line and "s3://" in line
    )
    assert not offenders, f"a results prefix was rebuilt by hand at {offenders}"
