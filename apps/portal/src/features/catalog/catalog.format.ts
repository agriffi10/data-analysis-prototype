// Display formatters for catalog data.

const ATHENA_TO_GLUE_TYPE: Record<string, string> = {
  varchar: 'string',
  integer: 'int',
  real: 'float',
  varbinary: 'binary'
};

/**
 * Maps Athena's Presto/Trino engine type names (`varchar`, `integer`, …) back
 * to the Hive/Glue DDL names the schema rail shows (`string`, `int`), so a
 * column reads the same in the results header as in the catalog. Unrecognized
 * types (including parameterized/complex ones like `decimal(10,2)`) pass
 * through unchanged.
 */
export function normalizeColumnType(type: string): string {
  return ATHENA_TO_GLUE_TYPE[type.trim().toLowerCase()] ?? type;
}
