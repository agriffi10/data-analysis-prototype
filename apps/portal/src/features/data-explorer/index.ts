// The Data Explorer (the engine's shell): the exploration model, the one
// SQL builder, the execution cache, the tab state, and the surfaces that mount them.
//
// The Glue reader, the Athena execution/results layer and the space list are
// `features/catalog/` and the `.sql` store is `features/saved-queries/`
// (SPEC-177) — this feature composes both and may not import `features/query/`.
export {
  renderExplorationSql,
  ExplorationRenderError,
  aggregateAlias,
  groupingOrderingViolation,
  isBareNumeric
} from './renderExplorationSql';
export {
  newExploration,
  newExplorationId,
  emptyExplorationQuery,
  emptyFormattingState,
  emptyExplorationPresentation,
  emptyGrouping,
  emptyQueryHistory,
  explorationSourceLabel
} from './exploration';
export {
  FILTER_OPERATORS,
  FILTER_OPERATOR_LABELS,
  clearFilter,
  clearSort,
  filterOf,
  filterValueKind,
  groupingApplyRefusal,
  isEmptyQuery,
  moveSortPriority,
  moveSortRefusal,
  operatorTakesValue,
  sameQuery,
  setFilter,
  setGrouping,
  setSort,
  sortOf
} from './explorationQueryOps';
export {calcResults, calcScopeText, percentageColumnName, percentageOfTotal, selectedCellValues} from './calc';
export {
  bandsOf,
  colourValue,
  computePageFormatting,
  gradientShade,
  isRuleApplicable,
  ruleRefusal,
  transformCell,
  typeColour,
  GRADIENT_COLUMN_REFUSAL,
  GRADIENT_RANGE_REFUSAL,
  NO_COLOUR_REFUSAL,
  PATTERN_REFUSAL,
  PATTERN_TOO_LONG_REFUSAL,
  STRIPE_BACKGROUND
} from './formatting';
export type {CellFormat, FormattingColumn, PageFormatting, TransformedValue} from './formatting';
export {useExploration} from './useExploration';
export type {UseExplorationResult} from './useExploration';
export {useExplorationQuery} from './useExplorationQuery';
export type {UseExplorationQueryResult} from './useExplorationQuery';
export {useExplorationTabs} from './useExplorationTabs';
export type {UseExplorationTabsResult, OpenExplorationOpts} from './useExplorationTabs';
export {tabBytesScanned} from './explorationTabs';
export {explorerKeys} from './explorerKeys';
export {
  CALC_DEFAULT_FUNCTIONS,
  CALC_FUNCTIONS,
  COLOUR_OPERATORS,
  COLOUR_OPERATOR_LABELS,
  FORMATTING_BACKGROUNDS,
  FORMATTING_COLOUR_LABELS,
  FORMATTING_FOREGROUNDS,
  FORMATTING_TOKEN_HEX,
  CALC_FUNCTION_LABELS,
  CALC_NO_VALUE,
  EXPLORATION_PAGE_SIZE,
  EXPLORATION_TABS_MAX,
  EXPLORER_FILTER_HISTORY_MAX,
  ROW_NUMBER_COLUMN_WIDTH,
  SQL_SOURCE_ALIAS,
  TEXT_VIEW_MAX_COLUMN_CHARS
} from './dataExplorer.constants';
export {DataExplorerWorkspace} from './DataExplorerWorkspace';
export {SourcePicker} from './SourcePicker';
export {ExplorationTabStrip} from './ExplorationTabStrip';
export {ExplorationResultsRegion} from './ExplorationResultsRegion';
export {SaveExplorationDialog} from './SaveExplorationDialog';
export type {SaveExplorationDialogProps} from './SaveExplorationDialog';
export {ExplorationGrid} from './ExplorationGrid';
export {ExplorationGridHeader} from './ExplorationGridHeader';
export {ExplorationRecordView} from './ExplorationRecordView';
export {ExplorationTextView} from './ExplorationTextView';
export {PresentationSwitch} from './PresentationSwitch';
export {ValuePanel} from './ValuePanel';
export {ColumnsPanel} from './ColumnsPanel';
export {RowColoursDialog} from './RowColoursDialog';
export type {RowColoursDialogProps, RowColoursSettings} from './RowColoursDialog';
export {StripingControl} from './StripingControl';
export {TransformersDialog} from './TransformersDialog';
export type {TransformersDialogProps} from './TransformersDialog';
export {CalcPanel} from './CalcPanel';
export {GroupingPanel} from './GroupingPanel';
export {GeneratedSqlDisclosure} from './GeneratedSqlDisclosure';
export {ColumnFilterMenu} from './ColumnFilterMenu';
export type {ColumnQueryActions} from './ColumnFilterMenu';
export {FilterValueDialog} from './FilterValueDialog';
export {ExpressionBar} from './ExpressionBar';
export {OrderFilterDialog} from './OrderFilterDialog';
export type {OrderFilterSettings} from './OrderFilterDialog';
export {FilterHistoryControls} from './FilterHistoryControls';
export {CostIndicator} from './CostIndicator';
export {CellValue} from './CellValue';
export {cellText, EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
export {useColumnGeometry, LAST_COLUMN_REFUSAL} from './useColumnGeometry';
export type {GridColumn, UseColumnGeometryResult} from './useColumnGeometry';
export {useCellSelection} from './useCellSelection';
export type {UseCellSelectionResult} from './useCellSelection';
export {useSourceColumns} from './useSourceColumns';
export {useExploreDeepLink} from './useExploreDeepLink';
export {resolveExploreParams, spaceDatabase} from './exploreSources';
export type {ExploreParams, ExploreResolution, ExploreTarget} from './exploreSources';
export type {
  Exploration,
  ExplorationSource,
  ExplorationQuery,
  ExplorationPresentation,
  GridPresentation,
  CellRef,
  CellRange,
  CellSelection,
  ExplorationTab,
  ExplorationTabsState,
  ColumnFilter,
  ColourOperator,
  ColourRule,
  ColourScope,
  ColourToken,
  FormattingState,
  SurfaceToken,
  Transformer,
  FilterOperator,
  FilterValueKind,
  SortEntry,
  QueryHistoryCursor,
  Grouping,
  GroupingAggregate,
  AggregateFunction,
  CalcFunction,
  CalcPanelState,
  CalcResult,
  ExecutionCost
} from './dataExplorer.types';
