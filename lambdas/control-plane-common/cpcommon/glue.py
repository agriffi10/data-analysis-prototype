"""Glue catalog reads shared by the control planes that read a LIVE table (SPEC-143).

``clone_definition`` moved here from ``tscommon.glue`` verbatim — signature, return
tuple, excluded parameters and reason codes unchanged — because the refresh path
(table-builder) asks the catalog the same question table-share does: *is this table a
shape I can faithfully reproduce?* A view has no data files, a managed table's files are
not the portal's to re-read, and a catalog-partitioned table's partitions live in the
catalog rather than in the projection properties. Both callers must refuse all three, and
the checks are fiddly enough that two copies would drift.

``tscommon.glue`` re-exports it, so table-share's verbs and tests are untouched.

WHY THE REASON CODES ARE REGISTERED HERE. ``TerminalError`` validates its reason against
``cpcommon.messages`` AT THE RAISE SITE, and these four codes were registered only by
``tscommon.messages``' import side effect. A table-builder Lambda attaches cpcommon +
tbcommon and never imports tscommon — so without the registration below, every shape
refusal on the refresh path would raise ``ValueError`` from inside the TerminalError
constructor and surface as the generic ``unexpected_error``, i.e. the exact refusals this
module exists to state clearly would be the ones it could not state. Registration marks a
code VALID; the user-facing WORDING stays in each domain's own table (tscommon's for a
share, tbcommon's for the mapped refresh codes — the refresh path maps these to its own
vocabulary at its call site, SPEC-143 FR-004).
"""

from . import config, messages
from .errors import TerminalError

# Source-only parameters never carried into the clone: Hive bookkeeping, the implicit
# EXTERNAL flag (the recipient CREATE re-establishes it), and the portal's own creation
# marker — inheriting it would have a copy claim it was built by the call that built its
# SOURCE (SPEC-143 FR-007).
#
# NOTE 'portal.managed' (a table TBLPROPERTY, dotted) is NOT 'portal-managed' (the Lake
# Formation tag on DATABASES, hyphenated — infra/modules/analytics/lakeformation.tf).
# Unrelated jobs, one character apart.
_EXCLUDED_PARAMETERS = frozenset({"transient_lastDdlTime", "EXTERNAL", "portal.managed"})

# Shape refusals raised below. Registered at import so they are valid TerminalError
# reasons in ANY control plane that imports this module — see the module docstring.
_SHAPE_REASONS = (
    "source_is_view",
    "source_not_external",
    "source_catalog_partitioned",
    "source_location_unsupported",
)
messages.register_reasons(_SHAPE_REASONS)


def _parse_location(location: str) -> dict:
    """Resolve the table LOCATION to a single listable prefix in a known bucket.

    The rule (architecture §12, nailed here): it must parse as s3://bucket/prefix, the
    bucket must be one of the two LF-registered data buckets, and the prefix is normalized
    to a trailing slash (an object-level LOCATION simply lists empty and fails as
    source_empty downstream).
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


def clone_definition(table: dict) -> tuple[dict, dict, bool]:
    """Validate the source shape and return (tableDefinition, location, partitioned).

    Rejections are whole-request terminal failures: views (no data files), managed/
    non-external tables, and catalog-partitioned sources (partition keys without
    projection props — the clone would declare partitions with zero registered entries and
    return nothing; copying partition metadata is deferred).

    The four reason codes read from table-share's vocabulary because that is where they
    were written and table-share's behaviour is unchanged by the move. A caller that
    speaks a different vocabulary MAPS them at its own call site (the refresh path's
    ``cannot_refresh_*``, SPEC-143 FR-004) rather than parameterising them here: the stems
    differ, so no prefix substitution produces both sets.
    """
    name = table.get("Name", "?")
    table_type = table.get("TableType", "")
    # The DETAILS are operator-facing and deliberately say nothing about sharing: two arcs
    # read them now, and a refresh failure in logs/service=table-builder/ explaining that a
    # table "can't be shared" sends its reader to the wrong control plane. The USER-facing
    # wording stays per-domain (tscommon/tbcommon messages.py), where it can say either.
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
