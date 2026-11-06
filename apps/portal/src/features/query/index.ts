// The Glue reader, the Athena execution/results layer, the space list and the
// column-width store are `features/catalog/`, and the `.sql` store is
// `features/saved-queries/` — consumers import them from there, not through
// this barrel.
export {getQueryHistory, appendQueryHistory, updateQueryHistoryEntry} from './queryHistory.service';
export {useResultsPageSize, clampPageSize} from './useResultsPageSize';
export type {UseResultsPageSizeResult} from './useResultsPageSize';
export {useEditorSplit, clampEditorHeight, clampFraction, splitBounds} from './useEditorSplit';
export type {UseEditorSplitResult} from './useEditorSplit';
export {EditorSplitDivider} from './EditorSplitDivider';
export {useQueryHistory} from './useQueryHistory';
export {QueryRunsProvider} from './QueryRunsProvider';
export type {UseQueryHistoryResult} from './useQueryHistory';
export {useQueryTabs} from './useQueryTabs';
export type {UseQueryTabsResult, OpenTabOpts} from './useQueryTabs';
export {queryKeys} from './queryKeys';
export {
  DEFAULT_RESULTS_PAGE_SIZE,
  MIN_RESULTS_PAGE_SIZE,
  MAX_RESULTS_PAGE_SIZE,
  QUERY_HISTORY_MAX,
  QUERY_TABS_MAX,
  QUERY_HISTORY_PAGE_SIZE,
  DEFAULT_SQL,
  DEFAULT_EDITOR_FRACTION,
  EDITOR_SPLIT_KEY_STEP,
  EDITOR_SPLIT_DIVIDER_HEIGHT,
  MIN_EDITOR_FRACTION,
  MAX_EDITOR_FRACTION,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT
} from './query.constants';
export type {QueryHistoryEntry, QueryHistory, QueryTab, QueryTabsState} from './query.types';
