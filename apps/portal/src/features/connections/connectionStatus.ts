import type {SharedConnectionStatus} from '../shared-spaces/sharedSpaces.types';

// Status is always conveyed as text + icon, never color-only.
const STATUS_LABELS: Record<SharedConnectionStatus, string> = {
  provisioning: 'Provisioning…',
  active: 'Active',
  failed: 'Failed',
  leaving: 'Leaving…',
  deleting: 'Deleting…'
};

/** Human label for a shared connection's lifecycle status. */
export function connectionStatusLabel(status: SharedConnectionStatus): string {
  return STATUS_LABELS[status];
}
