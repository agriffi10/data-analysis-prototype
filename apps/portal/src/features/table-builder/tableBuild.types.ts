// The request the browser enqueues to the table-builder control plane. The browser
// only SENDS this; validation, inspection, inference, and DDL execution all happen
// server-side.

/**
 * A user-declared partition key (never auto-detected). Order in
 * `TableBuildRequest.partitionKeys` is granularity, coarsest first (e.g. year,
 * month, day). Each variant carries the Athena partition-projection config its
 * type needs; the string variant maps to a projection enum.
 */
export type PartitionKey =
  | {name: string; type: 'integer'; range: [number, number]; digits?: number}
  | {name: string; type: 'date'; range: [string, string]; format: string; interval?: number; intervalUnit?: string}
  | {name: string; type: 'string'; values: string[]};

/**
 * Derived from the active file-space target + current folder prefix:
 * kind/bucket/database come from the space; prefix = the folder being viewed.
 * The server computes the table `location` from bucket+prefix.
 *
 * Named (it was inline) so the refresh caller can build one from a Glue
 * table's location rather than from a folder the user is looking at.
 */
export type TableBuildSpace = {
  kind: 'personal' | 'shared';
  bucket: string;
  prefix: string;
  database: string;
};

/**
 * Which half of the pipeline the request selects. A create infers a schema and writes a
 * new table; a refresh re-inspects the folder a table already points at and updates it in
 * place. Optional on the request and absent means 'create', so every shipped producer is
 * unchanged.
 */
export type TableBuildMode = 'create' | 'refresh';

export type TableBuildRequest = {
  /** Absent ⇒ 'create'. */
  mode?: TableBuildMode;
  space: TableBuildSpace;
  tableName: string;
  /** [] = flat (unpartitioned), and required to be [] when `mode` is 'refresh': a
   * refresh reconstructs the table's existing keys rather than redeclaring them. */
  partitionKeys: PartitionKey[];
};
