import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import type {ArchiveSpace} from '../../types/archive.types';
import {ArchiveList} from './ArchiveList';
import {isArchiveId} from './archiveId';
import {useArchiveList} from './useArchive';

type Props = {
  /** The space being restored into — the one the user is browsing, never the archive's. */
  space: ArchiveSpace;
  /** Where the restore will land, as the dialog names it. */
  spaceLabel: string;
  busy?: boolean;
  /** An enqueue failure to surface inline; the dialog stays open so the choice is not lost. */
  submitError?: string | null;
  onSubmit: (archiveId: string) => void;
  onCancel: () => void;
};

const LINK_BUTTON =
  'mt-3 inline-flex min-h-6 items-center text-sm font-medium text-accent-text underline underline-offset-2 hover:decoration-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent';

/**
 * The Restore Archived Data modal: pick one of the space's archives from a list.
 *
 * **The list is the way in, and a typed id is the way round it.** Every archive that finished has
 * a receipt folder, so the list shows it — named when the space's index knows it, by its id when
 * not. The one archive the list cannot show is one whose receipt failed to write, and that
 * failure's notification tells the user to keep the id, so the id field stays one link away
 * rather than going.
 *
 * **Focus and Enter differ by mode, deliberately.** In list mode focus lands on the list's heading
 * — on open and on every return from id mode — because `FormDialog`'s fallback would otherwise
 * focus the first radio, where arrow keys make a choice the user never made. Enter does nothing
 * there: the form submits only from its designated field, and the heading is not one. In id mode
 * the field takes focus and Enter submits from it, as it did when the field was the whole dialog.
 *
 * **Nothing is selected at first, and Restore says so rather than being disabled.** A disabled
 * control is not a refusal, and the user needs to be told what is missing.
 *
 * **It restores into the space the user is browsing, and says which one.** The space comes from
 * the route, never from the archive — an archive belonging to another space is then simply not
 * found, rather than an oracle for what exists elsewhere.
 */
export function RestoreArchiveDialog({space, spaceLabel, busy = false, submitError, onSubmit, onCancel}: Props) {
  const [mode, setMode] = useState<'list' | 'id'>('list');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [unselected, setUnselected] = useState(false);
  const [value, setValue] = useState('');
  const [attempted, setAttempted] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const list = useArchiveList(space, true);

  const trimmed = value.trim();
  // Shown on submit, never as you type: an id is invalid for every keystroke but the last, and a
  // field that turns red on the first character is a field that is wrong about the user.
  const idError =
    attempted && !isArchiveId(trimmed)
      ? 'That doesn’t look like an archive id. Ids look like 3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93.'
      : null;

  // Rows already in hand win over a failed refetch: every opening re-reads the list, and a
  // transient fault then must not take away the archives the user was about to pick from.
  const status = list.data ? 'ready' : list.isError ? 'error' : 'loading';

  return (
    <FormDialog
      title="Restore archived data"
      ariaLabel="Restore archived data"
      submitLabel="Restore"
      busyLabel="Starting…"
      busy={busy}
      scrollBody
      className="max-w-lg"
      autoFocusRef={mode === 'list' ? headingRef : inputRef}
      onSubmit={() => {
        if (mode === 'id') {
          setAttempted(true);
          if (isArchiveId(trimmed)) onSubmit(trimmed);
          return;
        }
        setUnselected(selectedId === null);
        if (selectedId !== null) onSubmit(selectedId);
      }}
      onCancel={onCancel}>
      <p className="mt-3 text-sm text-text-2">
        Everything in the archive is restored to <span className="font-medium text-text">{spaceLabel}</span>, back where
        it came from.
      </p>

      {mode === 'list' ? (
        <div className="mt-4">
          <h3
            ref={headingRef}
            tabIndex={-1}
            className="text-sm font-medium text-text focus-visible:outline-none">
            Choose an archive
          </h3>
          <ArchiveList
            status={status}
            listings={list.data ?? []}
            selectedId={selectedId}
            onSelect={(archiveId) => {
              setSelectedId(archiveId);
              setUnselected(false);
            }}
            showArchivedBy={space.kind === 'shared'}
            onRetry={() => void list.refetch()}
          />
          {unselected && (
            <p
              role="alert"
              className="mt-2 text-sm text-danger">
              Choose an archive to restore.
            </p>
          )}
          <button
            type="button"
            className={LINK_BUTTON}
            onClick={() => setMode('id')}>
            Restore by archive id instead
          </button>
        </div>
      ) : (
        <div className="mt-4">
          <Input
            ref={inputRef}
            label="Archive id"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            error={idError}
            placeholder="3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93"
            autoComplete="off"
            spellCheck={false}
          />
          <p className="mt-2 text-xs text-text-3">
            You’ll find the id under <span className="font-medium">system_settings</span> →{' '}
            <span className="font-medium">archive</span> in your files — each archive has a folder named after its id,
            holding a receipt you can download.
          </p>
          <button
            type="button"
            className={LINK_BUTTON}
            onClick={() => {
              setMode('list');
              setAttempted(false);
            }}>
            Back to the list
          </button>
        </div>
      )}

      <p className="mt-4 text-sm text-text-2">
        Restoring takes <strong>several hours</strong>, because archived files are kept in long-term storage. You’ll get
        a notification when it starts and another when it finishes.
      </p>

      {submitError && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger-soft bg-danger-soft p-3 text-sm text-danger">
          {submitError}
        </p>
      )}
    </FormDialog>
  );
}
