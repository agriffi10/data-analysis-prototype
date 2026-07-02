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

export type TableBuildRequest = {
  /**
   * Derived from the active file-space target + current folder prefix:
   * kind/bucket/database come from the space; prefix = the folder being viewed.
   * The server computes the table `location` from bucket+prefix.
   */
  space: {kind: 'personal' | 'shared'; bucket: string; prefix: string; database: string};
  tableName: string;
  /** [] = flat (unpartitioned). */
  partitionKeys: PartitionKey[];
};
