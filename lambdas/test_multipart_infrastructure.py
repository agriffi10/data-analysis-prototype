"""Two bucket settings that stop being incidental the day multipart ships.

Both already hold, and neither was put there for this feature — which is the reason to assert
them. An `expose_headers` list is the kind of thing a later tidy-up shortens, and a lifecycle
rule is the kind of thing a cost review deletes; each reads as hygiene right up until it is the
only thing holding a feature up.

**These are TEXT assertions over Terraform source.** They prove what the configuration says and
never what AWS applied — the live checks own that half.

Attributes:
  USER_SPACE: The data module's bucket configuration.
  SHARED_SPACE: The shared-space storage module's bucket configuration.
"""

import pathlib

from tf_blocks import blocks

_INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"

USER_SPACE = _INFRA / "modules" / "data" / "s3.tf"
SHARED_SPACE = _INFRA / "modules" / "shared-space-storage" / "main.tf"


def _cors_blocks() -> dict[str, str]:
    """Collects every CORS configuration across both buckets.

    Args:
      None.

    Returns:
      A qualified name per configuration, mapped to its body.

    Raises:
      None.
    """
    found = {}
    for path in (USER_SPACE, SHARED_SPACE):
        text = path.read_text()
        for name, body in blocks(text, "aws_s3_bucket_cors_configuration").items():
            found[f"{path.parent.name}.{name}"] = body
    return found


def _lifecycle_blocks() -> dict[str, str]:
    """Collects every lifecycle configuration across both buckets.

    Args:
      None.

    Returns:
      A qualified name per configuration, mapped to its body.

    Raises:
      None.
    """
    found = {}
    for path in (USER_SPACE, SHARED_SPACE):
        text = path.read_text()
        for name, body in blocks(text, "aws_s3_bucket_lifecycle_configuration").items():
            found[f"{path.parent.name}.{name}"] = body
    return found


def test_both_buckets_expose_the_etag_header_to_the_browser() -> None:
    """Without ``ETag`` exposed, a multipart upload cannot be completed AT ALL.

    And the failure names none of this: ``xhr.getResponseHeader('ETag')`` returns **null** rather
    than throwing, so the browser assembles a complete request full of nulls and S3 rejects it
    with an error about the parts. A reader would look at the part loop, not at a CORS list.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either bucket stops exposing it.
    """
    found = _cors_blocks()

    assert len(found) == 2, f"expected one CORS configuration per bucket, found {sorted(found)}"
    missing = sorted(name for name, body in found.items() if '"ETag"' not in body)
    assert missing == [], "a browser cannot read a part's ETag on these buckets"


def test_both_buckets_reap_the_parts_of_an_upload_nobody_finished() -> None:
    """The only sweep there is, and it is a bucket guarantee rather than this feature's.

    A closed tab, a crash or a dead network leaves an upload unaborted and nothing in the browser
    will ever abort it — so the parts sit in the bucket, billed, until this rule reaps them. That
    is what lets the cancel path be honest about what it does not guarantee.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either bucket stops reaping incomplete uploads.
    """
    found = _lifecycle_blocks()

    assert len(found) == 2, f"expected one lifecycle configuration per bucket, found {sorted(found)}"
    missing = sorted(
        name
        for name, body in found.items()
        if "abort_incomplete_multipart_upload" not in body
        or "days_after_initiation" not in body
    )
    assert missing == [], "orphaned upload parts would accumulate, billed, for ever"


def test_no_portal_policy_lets_a_user_enumerate_in_progress_uploads() -> None:
    """``s3:ListBucketMultipartUploads`` does not support ``s3:prefix``, so it is ungranted.

    It cannot be scoped to one user's own prefix, so granting it to the shared portal role would
    let any signed-in user enumerate every other user's in-progress uploads — keys included. This
    forbids any design that sweeps, reports or reconciles uploads across users, and the reason is
    recorded here because the grant looks harmless beside the two multipart actions that ARE
    granted.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a portal-role policy acquires the action.
    """
    policies = sorted(_INFRA.rglob("*portal-role*.json.tftpl"))

    assert policies, "the sweep found no portal-role policies, so an empty population would pass"
    offenders = sorted(
        str(path.relative_to(_INFRA))
        for path in policies
        if "ListBucketMultipartUploads" in path.read_text()
    )
    assert offenders == [], "a user could enumerate another user's in-progress uploads"
