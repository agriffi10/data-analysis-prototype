// Shared types for the query-engine data layer.

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
  /** Each row aligned to columns; the Athena header row is stripped. */
  rows: string[][];
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

export type QueryHistoryEntry = {
  queryExecutionId: string;
  sql: string;
  database: string;
  /** ISO timestamp. */
  submittedAt: string;
  /** Filled in once the execution is terminal. */
  status?: QueryState;
  dataScannedBytes?: number;
  durationMs?: number;
  /** Set when the run originated from a tab linked to a saved query. */
  savedQueryId?: string;
  savedQueryName?: string;
};

export type QueryHistory = {
  version: 1;
  /** Newest-first, capped at QUERY_HISTORY_MAX. */
  entries: QueryHistoryEntry[];
};

/** One statement parsed out of an editor buffer (SPEC-078 FR-001). */
export type ParsedStatement = {
  /** 0-based position in the batch. */
  index: number;
  /** The individual statement text (trimmed). */
  sql: string;
  /** Source offsets of the trimmed statement in the buffer (FR-006 cursor mapping). */
  range: {start: number; end: number};
};

/** The three run scopes (SPEC-078 FR-005). */
export type RunScope = 'statement' | 'script-single' | 'script-tabs';

/** One result set produced by a batch statement — drives a result tab (SPEC-078 FR-007). */
export type ResultTab = {
  /** Which ParsedStatement produced it. */
  statementIndex: number;
  /** Its Athena execution. */
  executionId: string;
  /** Tab label (1-based index + short statement hint). */
  label: string;
  /** The execution's result object, captured at finalize so Save-results works per tab. */
  outputLocation?: string;
};

/**
 * Which surface the mobile (`< tablet`) browse-first workspace is showing —
 * local UI state, never persisted (SPEC-100 FR-004/006).
 */
export type MobileQueryView = {kind: 'home'} | {kind: 'results'; sql: string; title: string};

/** Which list the mobile home is showing; kept beside the view so Back returns to it. */
export type MobileHomeTab = 'saved' | 'history';

/** One tab of the multi-tab editor — an independent query window. */
export type QueryTab = {
  /** Stable unique id (crypto.randomUUID()); not the label. */
  id: string;
  /** "Query N" for blank tabs, or a feature-supplied name. */
  label: string;
  /** This tab's editor text (the persisted, durable field). */
  sql: string;
  /** Set when opened from a saved query. */
  savedQueryId?: string;
};

export type QueryTabsState = {
  version: 1;
  /** Display order = creation order; always length >= 1. */
  tabs: QueryTab[];
  /** Must reference an existing tab. */
  activeTabId: string;
  /** Monotonic per-session counter for blank "Query N" tabs only. */
  nextQueryNumber: number;
};

/** User-named SQL kept for re-running, persisted per-user in the same S3 JSON-store pattern as history. */
export type SavedQuery = {
  id: string;
  /** User-supplied; collisions are warn-and-confirm. */
  name: string;
  sql: string;
  /** = username for now (single DB); kept for forward-compat. */
  database: string;
  /** ISO timestamp. */
  createdAt: string;
  /** ISO timestamp. */
  updatedAt: string;
};

export type SavedQueriesStore = {
  version: 1;
  queries: SavedQuery[];
};
