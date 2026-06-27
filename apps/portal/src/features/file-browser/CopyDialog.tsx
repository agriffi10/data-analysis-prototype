import {useEffect, useRef, useState} from 'react';
import {DestinationPicker} from './DestinationPicker';
import type {SelectableItem} from './selectionContext';
import {Button} from '../../components/Button';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';

// The same-folder editable-name prompt shape, surfaced by useCopy (FR-003).
type SameFolderPrompt = {
  kind: 'file' | 'folder';
  proposedName: string;
  validate: (name: string) => string | null;
  onConfirm: (name: string) => void;
  onCancel: () => void;
};

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being copied
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent — valid (→ auto-number)
  markerKey?: string;
  isBusy?: boolean;
  // When set, the copy is into the items' current parent (FR-003): the picker is
  // replaced by an editable, pre-filled non-colliding name field.
  sameFolderPrompt?: SameFolderPrompt | null;
  onCopy: (destPrefix: string) => void;
  onCancel: () => void;
};

// The editable-name view for a same-folder copy (FR-003). Pre-filled with the
// proposed `{name} (N)`; validated with the create-folder/rename rules; the user
// can override before confirming.
function SameFolderNameField({prompt}: {prompt: SameFolderPrompt}) {
  const [name, setName] = useState(prompt.proposedName);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const validationError = prompt.validate(name);
  const canConfirm = validationError === null;

  return (
    <>
      <p className="mt-2 text-sm text-text-2">Copying into the same folder. The copy will be named:</p>
      <div className="mt-3">
        <Input
          id="copy-name-input"
          ref={inputRef}
          label="Name for the copy"
          required
          aria-required="true"
          value={name}
          error={validationError}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && canConfirm) prompt.onConfirm(name);
          }}
        />
      </div>
      <div className="-mx-5 -mb-4 mt-4 flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
        <Button
          variant="ghost"
          onClick={prompt.onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={() => prompt.onConfirm(name)}
          disabled={!canConfirm}>
          Copy
        </Button>
      </div>
    </>
  );
}

// SPEC-039 FR-004/FR-006: destination-folder picker for Copy — a thin modal shell
// over the shared `DestinationPicker` (parallels MoveDialog). Unlike Move, Copy
// allows the items' current parent as a destination (`allowCurrentParent`): that
// triggers the same-folder auto-number flow (FR-003), which replaces the picker
// with an editable name field.
export function CopyDialog({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  markerKey,
  isBusy = false,
  sameFolderPrompt,
  onCopy,
  onCancel
}: Props) {
  return (
    <Modal
      ariaLabel="Copy to folder"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className="flex max-w-lg flex-col px-5 pb-4 pt-5">
      <h2 className="text-md font-semibold text-text">
        Copy {items.length} {items.length === 1 ? 'item' : 'items'}
      </h2>

      {sameFolderPrompt ? (
        <SameFolderNameField prompt={sameFolderPrompt} />
      ) : (
        <DestinationPicker
          bucket={bucket}
          items={items}
          rootPrefix={rootPrefix}
          rootLabel={rootLabel}
          currentPrefix={currentPrefix}
          markerKey={markerKey}
          isBusy={isBusy}
          allowCurrentParent
          confirmLabel="Copy here"
          busyLabel="Copying…"
          selfMessage="You can't copy a folder into itself."
          onConfirm={onCopy}
          onCancel={onCancel}
        />
      )}
    </Modal>
  );
}
