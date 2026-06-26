// Shared-spaces feature (SPEC-051: create; extended by SPEC-052+).
export { enqueueSharedSpaceRequest } from './sharedSpaces.service';
export type { EnqueueInput } from './sharedSpaces.service';
export { useCreateSharedConnection } from './useCreateSharedConnection';
export { CreateSharedConnectionDialog } from './CreateSharedConnectionDialog';
export type {
  SharedConnectionEntry,
  SharedConnectionsCache,
  SharedConnectionRole,
  SharedConnectionStatus,
  SharedSpaceAction,
  SharedSpaceRequest,
} from './sharedSpaces.types';
