// Table-builder feature: the two surfaces that enqueue a table build — the file browser's
// "Create table from this folder", where the folder in view IS the answer, and the Data
// Explorer's, where a folder has to be chosen first — the only browser touch-points of the
// async control plane
// The browser only enqueues a request; the pipeline creates the
// table and notifies the actor of the outcome.
export {CreateTableButton} from './CreateTableButton';
export {CreateTableDialog} from './CreateTableDialog';
export {CreateTableFromSpaceDialog} from './CreateTableFromSpaceDialog';
export type {BuildableSpace, ChosenFolder} from './CreateTableFromSpaceDialog';
export {createTableRefusal, CREATE_TABLE_AT_ROOT_REFUSAL} from './createTableRefusal';
export {useCreateTableFromSpace, suggestedNameFor} from './useCreateTableFromSpace';
export {useCatalogCatchUp, armCatalogCatchUp, drainCatalogCatchUp} from './useCatalogCatchUp';
export {PartitionKeysField} from './PartitionKeysField';
export {RefreshTableDialog} from './RefreshTableDialog';
export {enqueueTableBuild, enqueueTableRefresh, suggestTableName, isValidTableName} from './tableBuild.service';
export {useTableRefresh} from './useTableRefresh';
export {parseTableLocation} from './tableRefresh.location';
export {parseRefreshLink, MAX_LINKED_COLUMNS} from './tableRefresh.link';
export type {TableRefreshRequest, TableRefreshTarget, PendingRemoval} from './tableRefresh.types';
export {buildPartitionKeys, buildPartitionKey, validateDraftKey, emptyDraftKey, parseValues} from './partitionKeys';
export type {DraftPartitionKey, PartitionKeyErrors, PartitionType, PartitionKeysResult} from './partitionKeys';
export type {PartitionKey, TableBuildRequest, TableBuildSpace, TableBuildMode} from './tableBuild.types';
