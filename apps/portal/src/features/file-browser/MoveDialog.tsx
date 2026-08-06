import {DestinationPicker} from './DestinationPicker';
import {Modal} from '../../components/Modal';
import type {SelectableItem} from './selectionContext';
import type {FileSpaceTarget} from './useFileSpace';

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being moved
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent — not a valid destination
  markerKey?: string;
  isBusy?: boolean;
  destinations?: FileSpaceTarget[]; // connections the move can target (feedback 2026-06-30)
  onMove: (destPrefix: string, destBucket: string) => void;
  onCancel: () => void;
};

// SPEC-019 FR-003: destination-folder picker for Move. Refactored in SPEC-039
// FR-006 to be a thin modal shell over the shared `DestinationPicker` (no behavior
// change to move). Move forbids the items' current parent as a destination (a
// no-op), so `allowCurrentParent` is left off.
export function MoveDialog({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  markerKey,
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
      className="flex max-w-lg flex-col px-5 pb-4 pt-5">
      <h2 className="text-md font-semibold text-text">
        Move {items.length} {items.length === 1 ? 'item' : 'items'}
      </h2>

      <DestinationPicker
        bucket={bucket}
        items={items}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        currentPrefix={currentPrefix}
        markerKey={markerKey}
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
