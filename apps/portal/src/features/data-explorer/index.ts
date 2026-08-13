// The Data Explorer (SPEC-178's engine, SPEC-179's shell): the exploration model, the one
// SQL builder, the execution cache, the tab state, and the surfaces that mount them.
//
// The Glue reader, the Athena execution/results layer and the space list are
// `features/catalog/` (SPEC-176) and the `.sql` store is `features/saved-queries/`
// (SPEC-177) — this feature composes both and may not import `features/query/`.
export {renderExplorationSql, ExplorationRenderError, aggregateAlias} from './renderExplorationSql';
export {
  newExploration,
  newExplorationId,
  emptyExplorationQuery,
  emptyExplorationPresentation,
  explorationSourceLabel
} from './exploration';
export {useExploration} from './useExploration';
export type {UseExplorationResult} from './useExploration';
export {useExplorationTabs} from './useExplorationTabs';
export type {UseExplorationTabsResult, OpenExplorationOpts} from './useExplorationTabs';
export {tabBytesScanned} from './explorationTabs';
export {explorerKeys} from './explorerKeys';
export {EXPLORATION_PAGE_SIZE, EXPLORATION_TABS_MAX, SQL_SOURCE_ALIAS} from './dataExplorer.constants';
export {DataExplorerWorkspace} from './DataExplorerWorkspace';
export {SourcePicker} from './SourcePicker';
export {ExplorationTabStrip} from './ExplorationTabStrip';
export {ExplorationResultsTable} from './ExplorationResultsTable';
export {useExploreDeepLink} from './useExploreDeepLink';
export {resolveExploreParams, spaceDatabase} from './exploreSources';
export type {ExploreParams, ExploreResolution, ExploreTarget} from './exploreSources';
export type {
  Exploration,
  ExplorationSource,
  ExplorationQuery,
  ExplorationPresentation,
  ExplorationTab,
  ExplorationTabsState,
  ColumnFilter,
  FilterOperator,
  FilterValueKind,
  SortEntry,
  Grouping,
  GroupingAggregate,
  AggregateFunction,
  ExecutionCost
} from './dataExplorer.types';
