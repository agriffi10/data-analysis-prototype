"""Where the table-builder's Athena statements write their results.

Extracted so the create and refresh paths use the same construction rather than a second one
derived from prose. The two verbs run DDL against the same databases under the same role, and
a results prefix that differed between them is the kind of divergence that only shows up as a
Lake Formation denial on whichever path is exercised less.
"""


def results_location(space: dict, actor: str) -> str:
    """Builds the Athena results prefix for one actor in either kind of space.

    A personal space resolves to the user's own prefix; a shared space resolves under the
    space's database root, consistent with the shared-results routing.

    Args:
      space: The space dict, carrying ``bucket`` and ``database``.
      actor: The verified username the results belong to.

    Returns:
      An ``s3://`` prefix ending in a slash.

    Raises:
      KeyError: If the space is missing ``bucket`` or ``database``.
    """
    return f"s3://{space['bucket']}/{space['database']}/athenaresults/{actor}/"
