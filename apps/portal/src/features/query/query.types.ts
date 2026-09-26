// Types for the query workspace. The execution, result-page, Glue and space types
// it also uses live in `features/catalog/`, and the saved-query types in
// `features/saved-queries/`.

import type {QueryState, QueryStatus} from '../catalog/catalog.types';
import type {SavedQueryLink} from '../saved-queries/savedQueries.types';

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
  /** Set when the run originated from a tab linked to a saved query (the
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

/** One statement parsed out of an editor buffer. */
export type ParsedStatement = {
  /** 0-based position in the batch. */
  index: number;
  /** The individual statement text (trimmed). */
  sql: string;
  /** Source offsets of the trimmed statement in the buffer, for cursor mapping. */
  range: {start: number; end: number};
};

/** The three run scopes. */
export type RunScope = 'statement' | 'script-single' | 'script-tabs';

/** One result set produced by a batch statement — drives a result tab. */
export type ResultTab = {
  /** Which ParsedStatement produced it. */
  statementIndex: number;
  /** Its Athena execution. */
  executionId: string;
  /** Tab label (1-based index + short statement hint). */
  label: string;
  /**
   * This statement's terminal status, captured at finalize. It carries the result
   * object Save-results copies from, and the scanned/duration figures the status bar
   * prints beside the row count — all three describe the DISPLAYED statement, so a
   * flip between tabs moves them together instead of stranding them on whichever
   * statement ran last.
   */
  status: QueryStatus;
};

/** The saved query a mobile run IS, by its key and name — recorded in history in place of the tab's link. */
export type MobileSavedRef = {key: string; name: string};

/**
 * Which surface the mobile (`< tablet`) browse-first workspace is showing —
 * local UI state, never persisted.
 */
export type MobileQueryView =
  {kind: 'home'} | {kind: 'results'; sql: string; title: string; savedQuery?: MobileSavedRef};

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
  /** Set when opened from a saved query (replaces `savedQueryId`). */
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
