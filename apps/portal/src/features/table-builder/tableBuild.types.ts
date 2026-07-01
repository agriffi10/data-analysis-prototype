// SPEC-071 Data Model — the request the browser enqueues to the table-builder
// control plane (SPEC-066/067). The browser only SENDS this; validation,
// inspection, inference, and DDL execution all happen server-side.

// A user-declared partition key (never auto-detected — decided 2026-06-30). Order
// in `TableBuildRequest.partitionKeys` is granularity, coarsest first (e.g. year,
// month, day). Each carries the Athena partition-projection config its type needs.
export type PartitionKey =
  | {name: string; type: 'integer'; range: [number, number]; digits?: number}
  | {name: string; type: 'date'; range: [string, string]; format: string; interval?: number; intervalUnit?: string}
  | {name: string; type: 'string'; values: string[]}; // → Athena projection enum

export type TableBuildRequest = {
  // Derived from the active FileSpaceTarget (SPEC-057) + current folder prefix:
  //   kind/bucket/database come from the space; prefix = the folder being viewed.
  // The server computes the table `location` from bucket+prefix (SPEC-067).
  space: {kind: 'personal' | 'shared'; bucket: string; prefix: string; database: string};
  tableName: string;
  partitionKeys: PartitionKey[]; // [] = flat (unpartitioned)
};
