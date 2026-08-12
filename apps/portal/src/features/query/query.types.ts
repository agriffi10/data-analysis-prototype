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
  /** Set when the run originated from a tab linked to a saved query (SPEC-173: the
   * file's KEY, which is its identity, replacing the retired store's id). Recorded but
   * never rendered — `savedQueryName` is what the history row shows. */
  savedQueryKey?: string;
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
  /** Set when opened from a saved query (SPEC-173, replaces `savedQueryId`). */
  savedQuery?: SavedQueryLink;
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

/**
 * A space a saved query (or a saved result) can live in: the user's own space, or a
 * shared space they are an active member of. Replaces SPEC-049's `DestinationSpace`,
 * so the query feature has ONE definition of what a space is.
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

/**
 * One `.sql` object in a space's `saved_queries/` folder (SPEC-173).
 *
 * The key IS the identity and the filename IS the name — there is no id and no record,
 * because a `.sql` file cannot carry one without a sidecar this feature deliberately
 * does not have.
 */
export type SavedQuery = {
  spaceId: string;
  bucket: string;
  /** `{rootPrefix}saved_queries/{name}.sql` */
  key: string;
  /** The filename without its `.sql` suffix. */
  name: string;
  /** S3 LastModified, ISO 8601. */
  updatedAt: string;
  /** Object size in bytes. */
  size: number;
};

/** One `ListObjectsV2` page of a space's saved queries, in S3's own (lexicographic) order. */
export type SavedQueryPage = {
  queries: SavedQuery[];
  isTruncated: boolean;
  nextContinuationToken?: string;
};

/** What a tab remembers about the saved query it was opened from. */
export type SavedQueryLink = {
  spaceId: string;
  bucket: string;
  key: string;
  name: string;
};
