"""Glue catalog reads for the table-builder plane.

The shape validation and definition capture live in ``cpcommon.glue`` — table-share asks the
catalog the same question — and are re-exported here unchanged, so every caller reaches the
catalog through one module rather than importing two that both take a ``GetTable`` response.
``parse_location`` comes with them: the create path's post-condition compares the LOCATION the
catalog reports against the one this run's DDL declared, and deciding "same folder" a second
way is how two copies of that rule would come to disagree.

``update_time`` is table-builder's own: it renders the stamp the freshness guard compares, and
no other plane has a freshness guard.
"""

from datetime import UTC
from typing import cast

from cpcommon.glue import clone_definition, parse_location

__all__ = ["clone_definition", "parse_location", "update_time"]


def update_time(table: dict) -> str | None:
    """Renders a Glue table's last-modified stamp as a comparable string.

    The freshness guard compares a stamp captured at the start of a refresh against one read
    immediately before the write, and the two reads happen in DIFFERENT Lambdas — so the
    rendering lives here rather than in each of them. Two copies that disagreed by a
    representation would abandon every refresh while blaming a writer that does not exist, and
    line coverage would not show it: boto3 returns a datetime, the suites mostly use strings, and
    only one of the two branches ever runs in production.

    Normalised to UTC before rendering because botocore's default parser localises to the
    runtime's zone, so the same instant renders with different offsets under different ``TZ``.
    Both Lambdas run under the same default today; relying on that is a dependency on
    configuration nobody declared.

    Args:
      table: A Glue ``GetTable`` response's table dict.

    Returns:
      The stamp as an ISO-8601 UTC string, or None when the table carries none. Absent is a
      legitimate answer, and callers must treat it as "no evidence" rather than as a change.

    Raises:
      None.
    """
    stamp = table.get("UpdateTime")
    if stamp is None:
        return None
    if hasattr(stamp, "astimezone"):
        return cast("str", stamp.astimezone(UTC).isoformat())
    return str(stamp) or None
