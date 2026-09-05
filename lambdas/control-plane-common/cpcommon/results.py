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
"""

from .app_managed import athena_results_prefix


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
    base = f"s3://{bucket}/{athena_results_prefix(f'{database}/')}{actor}/"
    return f"{base}{sub}" if sub else base
