import {RefreshIconButton} from '../../components/RefreshIconButton';

/**
 * Refresh-connections control. The actual work — force a credential/token refresh
 * so newly-granted membership tags are stamped, then re-read the per-user cache —
 * lives in `useConnections().refresh`; this is just the affordance. Disabled and
 * spinning while in flight; a failed refresh is non-destructive.
 *
 * this used to draw its own two-path refresh glyph. It now shares the
 * app's one refresh icon, which is a deliberate (small) visual change.
 */
export function RefreshConnectionsButton({refreshing, onRefresh}: {refreshing: boolean; onRefresh: () => void}) {
  return (
    <RefreshIconButton
      label="Refresh connections"
      busy={refreshing}
      size="md"
      onClick={onRefresh}
    />
  );
}
