import {ConfirmDialog} from '../../components/ConfirmDialog';
import type {ArchiveItem} from '../../types/archive.types';

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
  /** The enqueue's failure, already through `toUserMessage` — never raw AWS text (SPEC-106). */
  submitError: string | null;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * The archive confirmation (SPEC-172 FR-002).
 *
 * **This dialog carries more weight than a normal confirm, and its shape says so.** Archiving is
 * the only action in this portal that deletes the user's data and cannot be undone in the same
 * sitting: getting it back takes hours and is billed. So it names what goes, says plainly that
 * the data leaves this space, and says how long a restore takes — the last two being consequences
 * of decisions (SPEC-168 FR-002, SPEC-171 FR-001) that no button label could imply.
 *
 * **THE CONFIRM IS NOT THE FOCUSED CONTROL AND ENTER DOES NOT SUBMIT.** `ConfirmDialog` focuses
 * Cancel and is not a form, so both hold by construction rather than by discipline — and that is
 * why this is built on `ConfirmDialog` rather than on `FormDialog`, whose `submitOnEnterRef` is
 * exactly the affordance this dialog must not have. A keystroke should not delete a folder.
 *
 * Escape cancels through the depth-ordered registry (SPEC-155), and `busy` locks both buttons and
 * dismissal while the enqueue is in flight, so Escape cannot close a half-submitted request.
 */
export function ArchiveDialog({items, rootPrefix, busy, submitError, onConfirm, onCancel}: Props) {
  const count = items.length;
  const only = count === 1 ? items[0] : null;
  const folders = items.filter((item) => item.kind === 'folder').length;

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
      onConfirm={onConfirm}
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

      {/* The two facts the button cannot carry. Stated as consequences, in the order the user
          meets them: the data goes now, and getting it back is not quick. */}
      <p className="mt-3 text-sm font-medium text-text">
        {count === 1 ? 'This will be removed from this space' : 'These will be removed from this space'} and stored in
        long-term storage.
      </p>
      <p className="mt-1 text-sm text-text-2">
        You can restore an archive later using its id, but a restore takes <strong>several hours</strong> to complete.
      </p>

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
