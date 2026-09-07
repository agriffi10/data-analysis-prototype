// Display formatters for catalog data.

import type {ResultsFormat} from './catalog.types';

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

/**
 * What each saveable format is called, and what it is called on disk.
 *
 * ONE map, read by the format `<select>`'s option text, by the toast that names what is being
 * converted, and by the extension rule below. Split across those three and the label a user
 * picks drifts from the label they are then told about.
 */
export const RESULTS_FORMATS: Record<ResultsFormat, {label: string; extension: string}> = {
  csv: {label: 'CSV', extension: '.csv'},
  parquet: {label: 'Parquet', extension: '.parquet'},
  json: {label: 'JSON', extension: '.json'},
  xlsx: {label: 'Excel', extension: '.xlsx'}
};

const KNOWN_EXTENSIONS = Object.values(RESULTS_FORMATS).map((f) => f.extension);

/**
 * Normalizes a Save-results file name for the chosen format.
 *
 * Appends the format's extension unless the user already typed it (case-insensitive), never
 * doubling it — and REPLACES another format's extension rather than stacking onto it, because
 * the format is a control the user can change after typing a name. Typing `report.csv` and
 * then choosing Parquet yields `report.parquet`, not `report.csv.parquet`.
 *
 * Only the four extensions this surface writes are replaced. A name whose own suffix happens to
 * look like an extension (`sales.2026`, `v1.2`) is left alone and the format's own extension is
 * appended, since guessing which trailing dot-segment was meant as a file type is how a name the
 * user chose quietly loses part of itself.
 */
export function normalizeResultsName(name: string, format: ResultsFormat): string {
  const trimmed = name.trim();
  const {extension} = RESULTS_FORMATS[format];
  if (trimmed.toLowerCase().endsWith(extension)) return trimmed;
  const typed = KNOWN_EXTENSIONS.find((ext) => trimmed.toLowerCase().endsWith(ext));
  return typed ? `${trimmed.slice(0, -typed.length)}${extension}` : `${trimmed}${extension}`;
}
