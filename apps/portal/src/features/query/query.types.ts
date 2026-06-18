// SPEC-034 Data Model. Shared types for the query-engine data layer consumed by
// the SPEC-035 workspace UI and SPEC-036 history panel.

export type QueryState =
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLED';

export type QueryStatus = {
  queryExecutionId: string;
  state: QueryState;
  stateChangeReason?: string;
  dataScannedBytes?: number;
  engineExecutionTimeMillis?: number;
  outputLocation?: string; // s3://.../{username}/athenaresults/<id>.csv, on SUCCEEDED
};

export type QueryColumn = { name: string; type: string };

export type QueryResultPage = {
  columns: QueryColumn[];
  rows: string[][]; // each row aligned to columns; the Athena header row is stripped
  nextToken?: string;
};

export type GlueColumn = { name: string; type: string };
export type GlueTableSummary = {
  name: string;
  columns: GlueColumn[];
  tableType?: string; // e.g. EXTERNAL_TABLE
  location?: string; // s3 location backing the table
};

export type QueryHistoryEntry = {
  queryExecutionId: string;
  sql: string;
  database: string;
  submittedAt: string; // ISO
  status?: QueryState; // filled in once terminal
  dataScannedBytes?: number;
  durationMs?: number;
};

export type QueryHistory = {
  version: 1;
  entries: QueryHistoryEntry[]; // newest-first, capped at QUERY_HISTORY_MAX
};
