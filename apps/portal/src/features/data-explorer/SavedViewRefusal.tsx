import {ConfirmDialog} from '../../components/ConfirmDialog';
import type {SavedViewRefusal as Refusal} from './useOpenSavedView';

type Props = {
  refusal: Refusal;
  onOpenInQuery: () => void;
  onClose: () => void;
};

/**
 * Why a saved query did not reopen as a view, with the one way forward: its SQL, in Query.
 *
 * Nothing is partly restored. The SQL handed over is the file's without its view line, and it
 * does not run until the user runs it there.
 */
export function SavedViewRefusal({refusal, onOpenInQuery, onClose}: Props) {
  return (
    <ConfirmDialog
      title="This view can’t be opened here"
      ariaLabel="Saved view can’t be opened"
      confirmLabel="Open in Query"
      cancelLabel="Close"
      confirmVariant="primary"
      onConfirm={onOpenInQuery}
      onCancel={onClose}>
      <p className="mt-3 text-sm text-text-2">{refusal.message}</p>
    </ConfirmDialog>
  );
}
