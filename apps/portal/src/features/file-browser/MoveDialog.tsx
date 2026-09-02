import {DestinationPicker} from './DestinationPicker';
import {Modal} from '../../components/Modal';
import type {SelectableItem} from './selectionContext';
import type {FileSpaceTarget} from './useFileSpace';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being moved
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent — not a valid destination
  isBusy?: boolean;
  destinations?: FileSpaceTarget[]; // connections the move can target (feedback 2026-06-30)
  onMove: (destPrefix: string, destBucket: string) => void;
  onCancel: () => void;
};

/**
 * Destination-folder picker for Move. Shares its shell with Copy:
 * a thin modal shell over the shared `DestinationPicker` (no behavior
 * change to move). Move forbids the items' current parent as a destination (a
 * no-op), so `allowCurrentParent` is left off.
 */
export function MoveDialog({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  isBusy = false,
  destinations,
  onMove,
  onCancel
}: Props) {
  return (
    <Modal
      ariaLabel="Move to folder"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>
        Move {items.length} {items.length === 1 ? 'item' : 'items'}
      </h2>

      <DestinationPicker
        bucket={bucket}
        items={items}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        currentPrefix={currentPrefix}
        isBusy={isBusy}
        destinations={destinations}
        autoFocus
        confirmLabel="Move here"
        busyLabel="Moving…"
        selfMessage="You can't move a folder into itself."
        onConfirm={onMove}
        onCancel={onCancel}
      />
    </Modal>
  );
}
