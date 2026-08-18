"""Glue catalog reads shared by the control planes that read a live table.

The refresh path asks the catalog the same question table-share does: is this table a shape
I can faithfully reproduce? A view has no data files, a managed table's files are not the
portal's to re-read, and a catalog-partitioned table's partitions live in the catalog rather
than in the projection properties. Both callers must refuse all three, and the checks are
fiddly enough that two copies would drift. ``tscommon.glue`` re-exports ``clone_definition``,
so table-share's verbs and tests are untouched.

The shape reason codes are registered here rather than by a domain's import side effect,
because ``TerminalError`` validates its reason at the raise site and a table-builder Lambda
never imports tscommon. Without the registration, every shape refusal on the refresh path
would raise ``ValueError`` from inside the constructor and surface as a generic error — the
exact refusals this module exists to state clearly would be the ones it could not state.
Registration marks a code valid; the user-facing wording stays in each domain's table, and a
caller that speaks a different vocabulary maps the codes at its own call site.

Attributes:
  _EXCLUDED_PARAMETERS: Source-only parameters never carried into a clone — Hive
    bookkeeping, the implicit EXTERNAL flag that the recipient CREATE re-establishes, and
    the portal's own creation marker, which inherited would have a copy claim it was built
    by the call that built its source. Note ``portal.managed`` (a table property, dotted) is
    not ``portal-managed`` (the Lake Formation tag on databases, hyphenated).
  _SHAPE_REASONS: The refusals raised below, registered at import.
"""

from datetime import UTC
from typing import cast

from . import config, messages
from .errors import TerminalError

_EXCLUDED_PARAMETERS = frozenset({"transient_lastDdlTime", "EXTERNAL", "portal.managed"})

_SHAPE_REASONS = (
    "source_is_view",
    "source_not_external",
    "source_catalog_partitioned",
    "source_location_unsupported",
)
messages.register_reasons(_SHAPE_REASONS)


def _parse_location(location: str | None) -> dict:
    """Resolves a table LOCATION to a single listable prefix in a known bucket.

    It must parse as ``s3://bucket/prefix``, the bucket must be one of the two
    Lake-Formation-registered data buckets, and the prefix is normalised to a trailing
    slash. An object-level LOCATION simply lists empty and fails as an empty source
    downstream.

    Args:
      location: The raw LOCATION from the table's storage descriptor, or None when the
        descriptor declares none. Any non-string is refused the same way.

    Returns:
      ``{"bucket": …, "prefix": …}`` with the prefix slash-terminated.

    Raises:
      TerminalError: ``source_location_unsupported`` if the LOCATION does not parse or names
        a bucket outside the portal's data buckets.
    """
    if not isinstance(location, str) or not location.startswith("s3://"):
        raise TerminalError("source_location_unsupported", f"unresolvable LOCATION {location!r}")
    rest = location[len("s3://"):]
    bucket, _, prefix = rest.partition("/")
    if not bucket or not prefix:
        raise TerminalError("source_location_unsupported", f"unresolvable LOCATION {location!r}")
    if bucket not in (config.USER_SPACE_BUCKET, config.SHARED_SPACE_BUCKET):
        raise TerminalError(
            "source_location_unsupported",
            f"LOCATION bucket {bucket!r} is outside the portal's data buckets",
        )
    if not prefix.endswith("/"):
        prefix += "/"
    return {"bucket": bucket, "prefix": prefix}


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


def clone_definition(table: dict) -> tuple[dict, dict, bool]:
    """Validates a live table's shape and projects it into a reproducible definition.

    The refusal details are operator-facing and deliberately say nothing about sharing: two
    arcs read them now, and a refresh failure explaining that a table "can't be shared" sends
    its reader to the wrong control plane. The user-facing wording stays per-domain, where it
    can say either.

    Args:
      table: A Glue ``GetTable`` response's table dict.

    Returns:
      A ``(definition, location, partitioned)`` tuple — the projected definition, the parsed
      bucket and prefix, and whether the source declares partition keys.

    Raises:
      TerminalError: ``source_is_view`` for a view, which has no data files;
        ``source_not_external`` for a managed table, whose files are not the portal's to
        re-read; ``source_catalog_partitioned`` for partition keys without projection
        properties, where the clone would declare partitions with zero registered entries
        and return nothing; ``source_location_unsupported`` for an unresolvable LOCATION.
    """
    name = table.get("Name", "?")
    table_type = table.get("TableType", "")
    if table_type == "VIRTUAL_VIEW":
        raise TerminalError("source_is_view", f"{name}: a view has no data files")
    if table_type != "EXTERNAL_TABLE":
        raise TerminalError(
            "source_not_external",
            f"{name}: not a base external table (TableType {table_type or 'unset'!r})",
        )

    sd = table.get("StorageDescriptor") or {}
    location = _parse_location(sd.get("Location"))

    parameters = {
        k: v for k, v in (table.get("Parameters") or {}).items() if k not in _EXCLUDED_PARAMETERS
    }
    partition_keys = table.get("PartitionKeys") or []
    projection = parameters.get("projection.enabled", "").lower() == "true"
    if partition_keys and not projection:
        raise TerminalError(
            "source_catalog_partitioned",
            f"{name}: partition keys with no projection properties; only flat or "
            "partition-projection tables are supported (v1)",
        )

    def _columns(cols):
        """Projects Glue column dicts to the portal's lowercase-keyed shape.

        Args:
          cols: Glue column dicts.

        Returns:
          A list of ``{name, type}`` dicts, carrying ``comment`` only when set.

        Raises:
          None.
        """
        return [
            {"name": c.get("Name"), "type": c.get("Type"), **({"comment": c["Comment"]} if c.get("Comment") else {})}
            for c in cols
        ]

    serde = sd.get("SerdeInfo") or {}
    definition = {
        "columns": _columns(sd.get("Columns") or []),
        "partitionKeys": _columns(partition_keys),
        "serde": {
            "serializationLibrary": serde.get("SerializationLibrary"),
            "parameters": serde.get("Parameters") or {},
        },
        "inputFormat": sd.get("InputFormat"),
        "outputFormat": sd.get("OutputFormat"),
        "tableType": "EXTERNAL_TABLE",
        "tableProperties": parameters,
    }
    return definition, location, bool(partition_keys)
