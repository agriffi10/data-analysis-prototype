"""Where the table-builder's Athena statements write their results.

The construction is ``cpcommon.results``. This module's own docstring
warned that a divergent results prefix "only shows up as a Lake Formation denial on whichever
path is exercised less", and two more copies were written anyway — so what is left here is the
table-builder's shape of the call, not a second construction.
"""

from cpcommon import results


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
    return results.results_location(space["bucket"], space["database"], actor)
