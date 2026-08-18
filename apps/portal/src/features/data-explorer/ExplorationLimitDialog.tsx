import {ConfirmDialog} from '../../components/ConfirmDialog';
import {EXPLORATION_TABS_MAX} from './dataExplorer.constants';

type Props = {
  onDismiss: () => void;
};

/**
 * The refusal `openTab` returns as `null`, said out loud.
 *
 * Dismiss-only: nothing was opened and there is nothing to confirm. It exists because the
 * `+` stays enabled at the cap — a disabled control would leave the user guessing, where
 * this names the limit and the one action that clears it.
 */
export function ExplorationLimitDialog({onDismiss}: Props) {
  return (
    <ConfirmDialog
      title="You’ve reached the exploration limit"
      ariaLabel="Exploration limit reached"
      confirmLabel="Got it"
      dismissOnly
      onConfirm={onDismiss}
      onCancel={onDismiss}>
      <p className="mt-3 text-sm text-text-2">
        You have the maximum of {EXPLORATION_TABS_MAX} explorations open. Close one before opening another.
      </p>
    </ConfirmDialog>
  );
}
