// The Data Explorer's engine (SPEC-178): the exploration model, the one SQL builder, the
// execution cache and the tab state. NO visible surface ships here — SPEC-179 mounts the
// first of them.
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
export {EXPLORATION_TABS_MAX, SQL_SOURCE_ALIAS} from './dataExplorer.constants';
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
