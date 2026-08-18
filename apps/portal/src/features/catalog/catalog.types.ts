// Shared types for the catalog data layer — what both the Query workspace and the
// Data Explorer mean by an execution, a result page, a Glue table and a space.

export type QueryState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export type QueryStatus = {
  queryExecutionId: string;
  state: QueryState;
  stateChangeReason?: string;
  dataScannedBytes?: number;
  engineExecutionTimeMillis?: number;
  /** s3://.../{username}/athenaresults/<id>.csv, present on SUCCEEDED. */
  outputLocation?: string;
};

export type QueryColumn = {name: string; type: string};

export type QueryResultPage = {
  columns: QueryColumn[];
  /**
   * Each row aligned to columns; the Athena header row is stripped.
   *
   * A cell is `null` where Athena reported **SQL NULL** and `''` where it reported an
   * empty string — a distinction that used to be flattened here and cannot be recovered
   * downstream. Surfaces that have nothing to say about it render both as
   * blank; the Data Explorer's Value panel is required to tell them apart.
   */
  rows: (string | null)[][];
  nextToken?: string;
};

export type GlueColumn = {name: string; type: string};
export type GlueTableSummary = {
  name: string;
  columns: GlueColumn[];
  /** e.g. EXTERNAL_TABLE or VIRTUAL_VIEW. */
  tableType?: string;
  /** S3 location backing the table. */
  location?: string;
};

/**
 * One accessible database's schema, as `useAllSchemas` returns it and as the query
 * editor's completion provider consumes it. Declared here rather than in
 * `features/query/sqlCompletions.ts` because the hook that produces it is a catalog
 * module and may not import from a leaf feature.
 */
export type DatabaseSchema = {database: string; tables: GlueTableSummary[]};

/**
 * A space a saved query (or a saved result) can live in: the user's own space, or a
 * shared space they are an active member of. Replaces SPEC-049's `DestinationSpace`,
 * so the catalog layer has ONE definition of what a space is.
 */
export type QuerySpace = {
  /** 'personal' for the user's own space; the shared-space name otherwise. */
  id: string;
  /** Display label: 'My files', or the space name. */
  label: string;
  bucket: string;
  /** The space root, trailing slash: `alice/` or `project_alpha/`. */
  rootPrefix: string;
  /** Label for the root row in a folder picker. */
  rootLabel: string;
};
