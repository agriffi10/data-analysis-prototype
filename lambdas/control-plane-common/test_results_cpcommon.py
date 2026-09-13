"""The proof that an execution's output is the caller's own, which the API and a plane share."""

import pytest
from cpcommon import results

BUCKET = "dat-prod-user-space"
OWNED = f"s3://{BUCKET}/alice/system_settings/athenaresults/e-1.csv"


def test_an_owned_location_names_its_key_inside_the_bucket():
    """The key is what a reader of the object needs, so the proof hands it back rather than a bool."""
    assert results.owned_results_key(OWNED, BUCKET, "alice") == (
        "alice/system_settings/athenaresults/e-1.csv"
    )


@pytest.mark.parametrize(
    "location",
    [
        f"s3://{BUCKET}/bob/system_settings/athenaresults/e-1.csv",
        f"s3://{BUCKET}/alice/system_settings/athenaresults/../../bob/e-1.csv",
        f"s3://{BUCKET}/alice-2/system_settings/athenaresults/e-1.csv",
        "s3://other-bucket/alice/system_settings/athenaresults/e-1.csv",
        f"s3://{BUCKET}/bob/s3://{BUCKET}/alice/system_settings/athenaresults/e-1.csv",
        None,
        42,
        f"s3://{BUCKET}/alice/system_settings/athenaresults/./e-1.csv",
        f"s3://{BUCKET}/alice/athenaresults/e-1.csv",
        "s3://dat-prod-athena-admin/fallback-results/e-1.csv",
    ],
    ids=[
        "another user's prefix",
        "a dot segment that climbs out",
        "a username that merely starts the same",
        "the right path in another bucket",
        "the caller's prefix inside someone else's key",
        "no location recorded",
        "a location that is not a string",
        "a single-dot segment",
        "the results folder before it moved under system_settings",
        "the workgroup's own fallback location",
    ],
)
def test_anything_else_is_not_the_callers(location):
    """Each is refused alike, so a caller can answer an unknown execution and a foreign one the same."""
    assert results.owned_results_key(location, BUCKET, "alice") is None
