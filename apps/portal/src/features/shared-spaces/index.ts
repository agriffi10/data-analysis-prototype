// Shared-spaces feature (SPEC-051: create; SPEC-052: list + refresh + tab).
export { enqueueSharedSpaceRequest, readSharedConnectionsCache } from './sharedSpaces.service';
export type { EnqueueInput } from './sharedSpaces.service';
export { useCreateSharedConnection } from './useCreateSharedConnection';
export { useManageMembers } from './useManageMembers';
export { CreateSharedConnectionDialog } from './CreateSharedConnectionDialog';
export { ManageMembersDrawer } from './ManageMembersDrawer';
export { AddMembersDialog } from './AddMembersDialog';
export { parseMemberInput } from './memberInput';
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
