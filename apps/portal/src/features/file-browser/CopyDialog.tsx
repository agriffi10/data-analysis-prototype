import {useRef, useState} from 'react';
import {DestinationPicker} from './DestinationPicker';
import type {SelectableItem} from './selectionContext';
// The probe's data plus the answers the dispatcher supplies. Imported rather than restated: the
// confirm is a submission point, so a structural copy here could drift from what actually runs.
import type {SameFolderPromptControls} from './useFileBrowserDialogs';
import type {FileSpaceTarget} from './useFileSpace';
import {Banner} from '../../components/Banner';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {Modal} from '../../components/Modal';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';

type Props = {
  bucket: string;
  items: SelectableItem[]; // the items being copied
  rootPrefix: string; // navigation floor (user's space root)
  rootLabel?: string; // label for the root crumb (hides the username segment)
  currentPrefix: string; // the items' current parent — valid (→ auto-number)
  isBusy?: boolean;
  destinations?: FileSpaceTarget[]; // connections the copy can target (feedback 2026-06-30)
  // When set, the copy is into the items' current parent: the picker is
  // replaced by an editable, pre-filled non-colliding name field.
  sameFolderPrompt?: SameFolderPromptControls | null;
  // Why the same-folder name lookup failed. Shown here, not on the page, because the dialog is
  // still open over the page and modal: anything behind it is under the scrim and unannounced.
  error?: string | null;
  onDismissError?: () => void;
  onCopy: (destPrefix: string, destBucket: string) => void;
  onCancel: () => void;
};

// The editable-name view for a same-folder copy. Pre-filled with the
// proposed `{name} (N)`; validated with the create-folder/rename rules; the user
// can override before confirming. Its own dialog rather than a branch inside the
// picker's shell, because the two have nothing in common below the title — and it
// is the branch that IS a name prompt, so it takes the shared chrome.
function SameFolderCopyDialog({prompt, itemCount}: {prompt: SameFolderPromptControls; itemCount: number}) {
  const [name, setName] = useState(prompt.proposedName);
  const inputRef = useRef<HTMLInputElement>(null);

  const validationError = prompt.validate(name);

  return (
    <FormDialog
      title={`Copy ${itemCount} ${itemCount === 1 ? 'item' : 'items'}`}
      ariaLabel="Copy to folder"
      submitLabel="Copy"
      submitDisabled={validationError !== null}
      autoFocusRef={inputRef}
      autoFocusSelect
      className="max-w-lg"
      onSubmit={() => prompt.onConfirm(name)}
      onCancel={prompt.onCancel}>
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
        />
      </div>
    </FormDialog>
  );
}

/**
 * Destination-folder picker for Copy — a thin modal shell
 * over the shared `DestinationPicker` (parallels MoveDialog). Unlike Move, Copy
 * allows the items' current parent as a destination (`allowCurrentParent`): that
 * triggers the same-folder auto-number flow, which replaces the picker
 * with an editable name field.
 *
 * Only for a SINGLE item: the auto-number prompt names one copy, so a selection of
 * several is refused at the current folder, with the reason, rather than copying the
 * first item and dropping the rest.
 *
 * @example
 * <CopyDialog bucket={bucket} items={selected} rootPrefix="alice/" currentPrefix="alice/docs/" destinations={destinations} onCopy={copy} onCancel={close} />
 */
export function CopyDialog({
  bucket,
  items,
  rootPrefix,
  rootLabel,
  currentPrefix,
  isBusy = false,
  destinations,
  sameFolderPrompt,
  error,
  onDismissError,
  onCopy,
  onCancel
}: Props) {
  if (sameFolderPrompt) {
    return (
      <SameFolderCopyDialog
        prompt={sameFolderPrompt}
        itemCount={items.length}
      />
    );
  }

  return (
    // NOT `FormDialog`: the footer here belongs to `DestinationPicker`, which owns the
    // confirm's label, its enabled-ness and the selected prefix it acts on, and is shared
    // with `MoveDialog`. Hoisting that state into two parents to reach the shared chrome
    // would cost more than the chrome saves. The panel therefore carries the body padding
    // and the picker's footer bleeds back out with `-mx-5 -mb-4` — the one remaining
    // variant, and this is its reason.
    <Modal
      ariaLabel="Copy to folder"
      dismissible={!isBusy}
      onDismiss={onCancel}
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>
        Copy {items.length} {items.length === 1 ? 'item' : 'items'}
      </h2>

      {error && (
        <Banner
          variant="danger"
          onDismiss={onDismissError}
          className="mt-3">
          {error}
        </Banner>
      )}

      <DestinationPicker
        bucket={bucket}
        items={items}
        rootPrefix={rootPrefix}
        rootLabel={rootLabel}
        currentPrefix={currentPrefix}
        isBusy={isBusy}
        destinations={destinations}
        allowCurrentParent={items.length === 1}
        currentParentMessage="Copy several items into a different folder."
        autoFocus
        confirmLabel="Copy here"
        busyLabel="Copying…"
        selfMessage="You can’t copy a folder into itself."
        onConfirm={onCopy}
        onCancel={onCancel}
      />
    </Modal>
  );
}
