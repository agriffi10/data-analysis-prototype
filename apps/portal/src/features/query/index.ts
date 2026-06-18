// SPEC-034 query-engine data layer — barrel for the SPEC-035 workspace UI and
// SPEC-036 history panel.
export {
  runQuery,
  getQueryStatus,
  getQueryResults,
  getResultCsvUrl,
  stopQuery,
  isTerminalState,
} from './query.service';
export { getDatabase, listTables } from './glue.service';
export {
  getQueryHistory,
  appendQueryHistory,
  updateQueryHistoryEntry,
} from './queryHistory.service';
export { useQueryExecution } from './useQueryExecution';
export { useQueryResults } from './useQueryResults';
export { useSchema, invalidateSchema } from './useSchema';
export type { SchemaData } from './useSchema';
export { useQueryHistory } from './useQueryHistory';
export type { UseQueryHistoryResult } from './useQueryHistory';
export { queryKeys } from './queryKeys';
export {
  POLL_INTERVAL_MS,
  MAX_POLL_DURATION_MS,
  DEFAULT_MAX_ROWS,
  QUERY_HISTORY_MAX,
} from './query.constants';
export type {
  QueryState,
  QueryStatus,
  QueryColumn,
  QueryResultPage,
  GlueColumn,
  GlueTableSummary,
  QueryHistoryEntry,
  QueryHistory,
} from './query.types';
