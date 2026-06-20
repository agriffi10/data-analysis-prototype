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
  // SPEC-043 FR-009: set when the run originated from a tab linked to a saved
  // query, so the history panel can show which saved query produced the result.
  savedQueryId?: string;
  savedQueryName?: string;
};

export type QueryHistory = {
  version: 1;
  entries: QueryHistoryEntry[]; // newest-first, capped at QUERY_HISTORY_MAX
};

// SPEC-041 multi-tab editor. Each tab is an independent query window.
export type QueryTab = {
  id: string; // stable unique id (crypto.randomUUID()); not the label
  label: string; // "Query N" for blank tabs, or a feature-supplied name (043/044)
  sql: string; // this tab's editor text (the persisted, durable field)
  savedQueryId?: string; // set when opened from a saved query (SPEC-043)
};

export type QueryTabsState = {
  version: 1;
  tabs: QueryTab[]; // display order = creation order; always length >= 1
  activeTabId: string; // must reference an existing tab
  nextQueryNumber: number; // monotonic per-session counter for blank "Query N" tabs only
};

// SPEC-043 saved queries — user-named SQL kept for re-running, persisted per-user
// in the same S3 JSON-store pattern as history.
export type SavedQuery = {
  id: string; // crypto.randomUUID()
  name: string; // user-supplied; collisions are warn-and-confirm (FR-003)
  sql: string;
  database: string; // = username for now (single DB); kept for forward-compat
  createdAt: string; // ISO
  updatedAt: string; // ISO
};

export type SavedQueriesStore = {
  version: 1;
  queries: SavedQuery[];
};
