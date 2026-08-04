// Table-builder feature (SPEC-071): the file-browser "Create table from this
// folder" surface — the only browser touch-point of the async control plane
// (SPEC-066→070). The browser only enqueues a request; the pipeline creates the
// table and notifies the actor of the outcome (SPEC-072).
export {CreateTableButton} from './CreateTableButton';
export {CreateTableDialog} from './CreateTableDialog';
export {PartitionKeysField} from './PartitionKeysField';
export {enqueueTableBuild, suggestTableName, isValidTableName} from './tableBuild.service';
export {buildPartitionKeys, buildPartitionKey, validateDraftKey, emptyDraftKey, parseValues} from './partitionKeys';
export type {DraftPartitionKey, PartitionKeyErrors, PartitionType, PartitionKeysResult} from './partitionKeys';
export type {PartitionKey, TableBuildRequest, TableBuildSpace, TableBuildMode} from './tableBuild.types';
