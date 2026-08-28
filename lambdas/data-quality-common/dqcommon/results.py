"""Where this plane's DDL statements write their output.

The per-query results prefix is ``cpcommon.results`` — three planes route output the same way,
and a prefix built one character differently is a Lake Formation grant that does not apply.
What is here is data-quality's own second shape: the temp-table verbs run DDL, which returns no
rows but still needs a location, and theirs goes beside the request's report rather than into an
``athenaresults`` folder. No other plane creates temp tables.
"""


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
