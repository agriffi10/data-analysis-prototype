import {useId, useState} from 'react';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import {Input} from '../../components/Input';
import type {ArchiveItem} from '../../types/archive.types';
import {ARCHIVE_NAME_MAX_CHARS, archiveNameRefusal, normalizeArchiveName} from './archiveName';

const MAX_NAMES = 5;

/** The display name for one selected item — the last segment of a key or a folder prefix. */
function displayName(item: ArchiveItem): string {
  return item.key.replace(/\/$/, '').split('/').pop() ?? item.key;
}

/** The item's path relative to the space root, for the single-folder heading. */
function relativeToRoot(key: string, rootPrefix: string): string {
  return key.startsWith(rootPrefix) ? key.slice(rootPrefix.length) : key;
}

type Props = {
  items: ArchiveItem[];
  /** The space root, so a folder is named by its path within the space rather than its key. */
  rootPrefix: string;
  busy: boolean;
  /** The enqueue's failure, already through `toUserMessage` — never raw AWS text. */
  submitError: string | null;
  /** Called with the archive's name, normalised; an empty string means the user gave none. */
  onConfirm: (name: string) => void;
  onCancel: () => void;
};

/**
 * The archive confirmation.
 *
 * **This dialog carries more weight than a normal confirm, and its shape says so.** Archiving is
 * the only action in this portal that deletes the user's data and cannot be undone in the same
 * sitting: getting it back takes hours and is billed. So it names what goes, says plainly that
 * the data leaves this space, and says how long a restore takes — the last two being consequences
 * of decisions that no button label could imply.
 *
 * **THE CONFIRM IS NOT THE FOCUSED CONTROL AND ENTER DOES NOT SUBMIT.** `ConfirmDialog` focuses
 * Cancel and is not a form, so both hold by construction rather than by discipline — and that is
 * why this is built on `ConfirmDialog` rather than on `FormDialog`, whose `submitOnEnterRef` is
 * exactly the affordance this dialog must not have. A keystroke should not delete a folder.
 *
 * **The Name field keeps that true, and it is why the field sits in a `ConfirmDialog` rather than
 * a form.** The field is inside no `<form>`, so Enter in it has no implicit submission to trigger;
 * moving this dialog to `FormDialog`, or wrapping the field in a form, would hand the Name field
 * the one affordance this dialog must never have. The name is checked on **Archive**, not as the
 * user types, and a refused one keeps the dialog open with the reason on the field.
 *
 * **What it says is what the outside reviewers asked for**: where the data goes, where a restore
 * puts it, what stops a restore, how long one takes, what the storage costs, and how to find the
 * archive again. The remedy for a restore that is refused is "move or rename" — never a deletion,
 * because the files in the way can be the only copy.
 *
 * Escape cancels through the depth-ordered registry, and `busy` locks both buttons and
 * dismissal while the enqueue is in flight, so Escape cannot close a half-submitted request.
 */
export function ArchiveDialog({items, rootPrefix, busy, submitError, onConfirm, onCancel}: Props) {
  const count = items.length;
  const only = count === 1 ? items[0] : null;
  const folders = items.filter((item) => item.kind === 'folder').length;
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const hintId = useId();

  const confirm = () => {
    const refusal = archiveNameRefusal(name);
    setNameError(refusal);
    if (refusal === null) onConfirm(normalizeArchiveName(name));
  };

  let heading: string;
  if (only?.kind === 'folder') {
    heading = `Archive the folder “${relativeToRoot(only.key, rootPrefix)}” and everything inside it?`;
  } else if (only) {
    heading = `Archive “${displayName(only)}”?`;
  } else {
    heading = `Archive ${count} items?`;
  }

  return (
    <ConfirmDialog
      title={heading}
      ariaLabel="Confirm archive"
      confirmLabel="Archive"
      busyLabel="Starting…"
      busy={busy}
      confirmVariant="danger"
      tone="danger"
      onConfirm={confirm}
      onCancel={onCancel}>
      {count > 1 && (
        <ul className="mt-3 max-h-36 overflow-auto rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text">
          {items.slice(0, MAX_NAMES).map((item) => (
            <li
              key={item.key}
              className="truncate py-0.5">
              {displayName(item)}
              {item.kind === 'folder' && '/'}
            </li>
          ))}
          {count > MAX_NAMES && <li className="py-0.5 text-text-3">…and {count - MAX_NAMES} more</li>}
        </ul>
      )}

      {folders > 0 && (
        <p className="mt-3 text-sm text-text-2">
          {folders === 1 && count === 1
            ? 'All files and subfolders it contains will be archived.'
            : 'Selected folders are archived along with all of their contents.'}
        </p>
      )}

      {/* The facts no button label can carry, in the order the user meets them: where the data
          goes now, then what getting it back involves. */}
      <p className="mt-3 text-sm font-medium text-text">
        {count === 1 ? 'This moves' : 'These move'} out of this space into separate long-term archive storage, where{' '}
        {count === 1 ? 'it can’t be opened until it is' : 'they can’t be opened until they are'} restored.
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-text-2">
        <li>A restore puts every file back in this space, in the same folder and under the same name it has now.</li>
        <li>
          A restore overwrites nothing: if any of those files exists again, nothing is restored until you move or rename
          what is in the way.
        </li>
        <li>
          A restore takes <strong>several hours</strong>.
        </li>
        <li>Long-term storage is charged for at least 90 days, even if you restore sooner.</li>
      </ul>

      <div className="mt-4">
        <Input
          label="Name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={nameError}
          maxLength={ARCHIVE_NAME_MAX_CHARS}
          aria-describedby={hintId}
          autoComplete="off"
          placeholder="e.g. Q1 reports"
          disabled={busy}
        />
        <p
          id={hintId}
          className="mt-1 text-xs text-text-3">
          To find this archive later, choose <span className="font-medium">Restore Archived Data</span> in this space
          and pick it from the list by this name.
        </p>
      </div>

      {submitError && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger-soft bg-danger-soft p-3 text-sm text-danger">
          {submitError}
        </p>
      )}
    </ConfirmDialog>
  );
}
