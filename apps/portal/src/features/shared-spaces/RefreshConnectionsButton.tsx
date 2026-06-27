import { IconButton } from '../../components/IconButton';
import { cx } from '../../lib/cx';

// SPEC-052 FR-003: Refresh-connections control (mirrors the SPEC-046 history
// refresh button). The work — force a credential/token refresh so newly-granted
// `shared_space_k` tags are stamped, then re-read the per-user cache — lives in
// `useConnections().refresh`; this is just the affordance. Disabled + spinning
// while in flight; a failed refresh is non-destructive (the list stays put).
export function RefreshConnectionsButton({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  return (
    <IconButton label="Refresh connections" disabled={refreshing} onClick={onRefresh}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className={cx('h-4 w-4', refreshing && 'animate-spin')}
      >
        <path d="M21 12a9 9 0 1 1-2.64-6.36" />
        <path d="M21 3v6h-6" />
      </svg>
    </IconButton>
  );
}
