// The `.sql` store, extracted from `features/query/` by SPEC-177 so
// the Query workspace and the Data Explorer can both save and load a saved query without
// either importing the other. The space a query lives in is a `QuerySpace` from
// `features/catalog/`; the Query workspace's own rail panel (`SavedQueriesPanel`) stays
// where it is — it is a workspace surface, not part of the store.
export {
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery,
  writeSavedQuery,
  deleteSavedQuery,
  savedQueriesPrefix,
  savedQueryKey,
  savedQueryName,
  validateSavedQueryName,
  isLinkedSavedQuery
} from './savedQueries.service';
export {useSavedQueries} from './useSavedQueries';
export type {UseSavedQueriesResult} from './useSavedQueries';
export {useSavedQuerySpace} from './useSavedQuerySpace';
export type {UseSavedQuerySpaceResult} from './useSavedQuerySpace';
export {useSavedQueriesPager} from './useSavedQueriesPager';
export type {SavedQueriesPagerState} from './useSavedQueriesPager';
export {useSaveQuery} from './useSaveQuery';
export type {UseSaveQueryResult, SaveQueryCollision} from './useSaveQuery';
export {readSavedQuerySpaceId, writeSavedQuerySpaceId} from './savedQuerySpace';
export {SaveQueryDialog} from './SaveQueryDialog';
export type {SaveQueryRequest} from './SaveQueryDialog';
export {SavedQuerySpaceSelect} from './SavedQuerySpaceSelect';
export {savedQueryKeys} from './savedQueryKeys';
export {SAVED_QUERIES_PAGE_SIZE, QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX} from './savedQueries.constants';
export type {SavedQuery, SavedQueryPage, SavedQueryLink} from './savedQueries.types';
