"""Where a control plane's Athena statements write their output.

``tbcommon/results.py`` said why this must exist exactly once, and was then copied twice
anyway:

    a results prefix that differed between them is the kind of divergence that only shows up
    as a Lake Formation denial on whichever path is exercised less.

That is the whole risk. The workgroup has one static result location, so every plane routes
its own output per query; the prefix is inside a user's or a space's own tree, which means it
is covered by the same Lake Formation grant as the data — and a prefix built one character
differently is a grant that does not apply, discovered on the least-travelled path.

The three copies were not identical, and the differences are parameters rather than accidents:
the table-builder and table-share prefixes end at the actor and carry a trailing slash, while
data-quality routes a whole request under a fixed ``data-quality`` actor segment and appends
the request id. ``sub`` is that difference.

``ddl_output`` is a second, unrelated shape kept in the same module because it answers the same
question for the temp-table verbs: their DDL writes beside the report rather than into an
``athenaresults`` folder.
"""


def results_location(bucket: str, database: str, actor: str, *, sub: str | None = None) -> str:
    """Builds the Athena results prefix for one actor under one database root.

    Args:
      bucket: The bucket the space lives in.
      database: The space's root segment — its Glue database for a personal or shared space,
        which is also its prefix.
      actor: The verified username the results belong to, or a plane's own fixed segment when
        the output is per request rather than per user.
      sub: A final segment appended without a trailing slash. Its presence is what separates
        the per-request layout from the per-actor one; omitting it ends the prefix at the
        actor, with the trailing slash Athena expects for a folder.

    Returns:
      An ``s3://`` prefix, ending in a slash unless ``sub`` was supplied.

    Raises:
      None.
    """
    base = f"s3://{bucket}/{database}/athenaresults/{actor}/"
    return f"{base}{sub}" if sub else base


def ddl_output(bucket: str, report_prefix: str) -> str:
    """Builds the output prefix for DDL run beside a request's report.

    A DDL statement returns no rows, but the workgroup still requires a location. Putting it
    under the report keeps the artefacts of one request together and inside the tree the
    request is already authorized for.

    Args:
      bucket: The bucket the report lives in.
      report_prefix: The request's report prefix. Trailing slashes are trimmed, so a caller
        that has already trimmed and one that has not agree.

    Returns:
      An ``s3://`` prefix ending in a slash. With no report prefix, the bucket root — a
      location that exists rather than the ``s3:///ddl/`` a bare interpolation would build.

    Raises:
      None.
    """
    trimmed = (report_prefix or "").rstrip("/")
    return f"s3://{bucket}/{trimmed}/ddl/" if trimmed else f"s3://{bucket}/"
