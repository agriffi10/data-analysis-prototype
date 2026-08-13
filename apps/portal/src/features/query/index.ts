// The Glue reader, the Athena execution/results layer, the space list and the
// column-width store are `features/catalog/` (SPEC-176) — consumers import them from
// there, not through this barrel.
export {getQueryHistory, appendQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
export {
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery,
  writeSavedQuery,
  deleteSavedQuery,
  savedQueriesPrefix,
  savedQueryKey,
  savedQueryName,
  validateSavedQueryName
} from './savedQueries.service';
export {useResultsPageSize, clampPageSize} from './useResultsPageSize';
export type {UseResultsPageSizeResult} from './useResultsPageSize';
export {useEditorLayout} from './useEditorLayout';
export type {UseEditorLayoutResult} from './useEditorLayout';
export {useQueryHistory} from './useQueryHistory';
export type {UseQueryHistoryResult} from './useQueryHistory';
export {useQueryTabs} from './useQueryTabs';
export type {UseQueryTabsResult, OpenTabOpts} from './useQueryTabs';
export {useSavedQueries} from './useSavedQueries';
export type {UseSavedQueriesResult} from './useSavedQueries';
export {useSavedQuerySpace} from './useSavedQuerySpace';
export type {UseSavedQuerySpaceResult} from './useSavedQuerySpace';
export {useSavedQueriesPager} from './useSavedQueriesPager';
export type {SavedQueriesPagerState} from './useSavedQueriesPager';
export {readSavedQuerySpaceId, writeSavedQuerySpaceId} from './savedQuerySpace';
export {queryKeys} from './queryKeys';
export {
  DEFAULT_RESULTS_PAGE_SIZE,
  MIN_RESULTS_PAGE_SIZE,
  MAX_RESULTS_PAGE_SIZE,
  QUERY_HISTORY_MAX,
  QUERY_TABS_MAX,
  QUERY_HISTORY_PAGE_SIZE,
  SAVED_QUERIES_PAGE_SIZE,
  QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX,
  DEFAULT_SQL,
  DEFAULT_LAYOUT_PRESET,
  LAYOUT_PRESET_EDITOR_FRACTION,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT
} from './query.constants';
export type {EditorLayoutPreset} from './query.constants';
export type {
  QueryHistoryEntry,
  QueryHistory,
  QueryTab,
  QueryTabsState,
  SavedQuery,
  SavedQueryPage,
  SavedQueryLink
} from './query.types';
