import type {SharedConnectionStatus} from './sharedSpaces.types';

// SPEC-052: human labels for a shared connection's lifecycle status. Used by the
// Connections tab badge and the disabled-entry hint in the Query schema rail /
// Files list. Status is always conveyed as text + icon, never color-only (a11y).
const STATUS_LABELS: Record<SharedConnectionStatus, string> = {
  provisioning: 'Provisioning…',
  active: 'Active',
  failed: 'Failed',
  leaving: 'Leaving…'
};

export function connectionStatusLabel(status: SharedConnectionStatus): string {
  return STATUS_LABELS[status];
}
