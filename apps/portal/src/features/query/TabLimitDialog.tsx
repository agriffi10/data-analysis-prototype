import {ConfirmDialog} from '../../components/ConfirmDialog';
import {QUERY_TABS_MAX} from './query.constants';

type Props = {
  onDismiss: () => void;
};

// SPEC-041 FR-008: purely informational alert shown when a tab-open is attempted
// at QUERY_TABS_MAX. Single dismiss button; the attempted action is not
// completed. Thin wrapper over the shared ConfirmDialog (dismiss-only mode).
export function TabLimitDialog({onDismiss}: Props) {
  return (
    <ConfirmDialog
      title="You’ve reached the tab limit"
      ariaLabel="Query tab limit reached"
      confirmLabel="Got it"
      dismissOnly
      onConfirm={onDismiss}
      onCancel={onDismiss}>
      <p className="mt-3 text-sm text-text-2">
        You have the maximum of {QUERY_TABS_MAX} query tabs open. Close a tab before opening another.
      </p>
    </ConfirmDialog>
  );
}
