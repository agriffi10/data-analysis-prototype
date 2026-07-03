"""Pure CREATE EXTERNAL TABLE DDL generation for the table builder.

Assembles the CREATE EXTERNAL TABLE IF NOT EXISTS statement from the resolved data
columns + user-declared partition keys, with the per-format storage clause and — when
partitioned — the Athena partition-projection TBLPROPERTIES, so the table is
queryable with no MSCK REPAIR. Format rules: Parquet → STORED AS PARQUET; CSV →
OpenCSVSerde (all-string) + skip.header.line.count=1; JSON → OpenX JsonSerDe.
"""

# Hive type for each declared partition-key projection type.
_PARTITION_HIVE = {"integer": "int", "date": "date", "string": "string"}

# OpenCSVSerde escapeChar is a single backslash; written as '\\' in DDL (two chars).
_CSV_SERDE = (
    "ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde' "
    "WITH SERDEPROPERTIES ('separatorChar'=',', 'quoteChar'='\"', 'escapeChar'='\\\\') "
    "STORED AS TEXTFILE"
)
_JSON_SERDE = "ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe' STORED AS TEXTFILE"
_PARQUET_STORED = "STORED AS PARQUET"


def _q(identifier):
    """Backtick-quote a catalog identifier (db / table / column)."""
    return f"`{identifier}`"


def _storage_clause(fmt):
    if fmt == "parquet":
        return _PARQUET_STORED
    if fmt == "csv":
        return _CSV_SERDE
    if fmt == "json":
        return _JSON_SERDE
    raise ValueError(f"unknown format {fmt!r}")


def _projection_props(key):
    """Athena projection.* TBLPROPERTIES for one declared partition key."""
    name = key["name"]
    ptype = key["type"]
    props = []
    if ptype == "integer":
        lo, hi = key["range"]
        props.append((f"projection.{name}.type", "integer"))
        props.append((f"projection.{name}.range", f"{lo},{hi}"))
        if key.get("digits") is not None:
            props.append((f"projection.{name}.digits", str(key["digits"])))
    elif ptype == "date":
        lo, hi = key["range"]
        props.append((f"projection.{name}.type", "date"))
        props.append((f"projection.{name}.range", f"{lo},{hi}"))
        props.append((f"projection.{name}.format", key["format"]))
        if key.get("interval") is not None:
            props.append((f"projection.{name}.interval", str(key["interval"])))
        if key.get("interval.unit") is not None:
            props.append((f"projection.{name}.interval.unit", str(key["interval.unit"])))
    elif ptype == "string":
        props.append((f"projection.{name}.type", "enum"))
        props.append((f"projection.{name}.values", ",".join(key["values"])))
    else:
        raise ValueError(f"unknown partition type {ptype!r} for {name!r}")
    return props


def _tblproperties(fmt, partition_keys):
    """Ordered (k, v) TBLPROPERTIES: format props, then projection props."""
    props = []
    if fmt == "csv":
        props.append(("skip.header.line.count", "1"))
    if partition_keys:
        props.append(("projection.enabled", "true"))
        for key in partition_keys:
            props.extend(_projection_props(key))
    return props


def build_create_table_ddl(
    database: str,
    table_name: str,
    columns: list[dict],
    partition_keys: list[dict],
    fmt: str,
    location: str,
) -> str:
    """Build a valid CREATE EXTERNAL TABLE IF NOT EXISTS statement (string).

    ``columns`` is the ordered [{name, type}] (Hive types) data body;
    ``partition_keys`` are the user-declared keys ([] = flat). A data column that
    collides with a partition-key name is dropped from the body (the partition key
    wins) so the DDL stays valid.
    """
    part_names = {k["name"] for k in partition_keys}
    body = ", ".join(
        f"{_q(c['name'])} {c['type']}" for c in columns if c["name"] not in part_names
    )

    stmt = f"CREATE EXTERNAL TABLE IF NOT EXISTS {_q(database)}.{_q(table_name)} ({body})"

    if partition_keys:
        part_cols = ", ".join(
            f"{_q(k['name'])} {_PARTITION_HIVE[k['type']]}" for k in partition_keys
        )
        stmt += f" PARTITIONED BY ({part_cols})"

    stmt += f" {_storage_clause(fmt)} LOCATION '{location}'"

    props = _tblproperties(fmt, partition_keys)
    if props:
        rendered = ", ".join(f"'{k}'='{v}'" for k, v in props)
        stmt += f" TBLPROPERTIES ({rendered})"

    return stmt
