// Shared-spaces feature (SPEC-051: create; SPEC-052: list + refresh + tab).
export {
  enqueueSharedSpaceRequest,
  readSharedConnectionsCache,
} from './sharedSpaces.service';
export type { EnqueueInput } from './sharedSpaces.service';
export { useCreateSharedConnection } from './useCreateSharedConnection';
export { CreateSharedConnectionDialog } from './CreateSharedConnectionDialog';
export { ConnectionsPage } from './ConnectionsPage';
export { connectionStatusLabel } from './connectionStatus';
export type {
  SharedConnectionEntry,
  SharedConnectionsCache,
  SharedConnectionRole,
  SharedConnectionStatus,
  SharedSpaceAction,
  SharedSpaceRequest,
} from './sharedSpaces.types';
