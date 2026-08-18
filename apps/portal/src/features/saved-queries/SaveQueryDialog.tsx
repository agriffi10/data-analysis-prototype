import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {SavedQuerySpaceSelect} from './SavedQuerySpaceSelect';
import {isLinkedSavedQuery, validateSavedQueryName} from './savedQueries.service';
import type {SavedQueryLink} from './savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';

/** What the dialog reports on submit. `overwrite` is decided by the host, not here. */
export type SaveQueryRequest = {
  space: QuerySpace;
  name: string;
};

type Props = {
  /** '' for a new save; the linked file's name on re-save (pre-filled and selected). */
  initialName: string;
  /** Every space the user may write into, personal first (the list). */
  spaces: QuerySpace[];
  /** The space the control opens on — the tab's own, else the remembered one. */
  initialSpace: QuerySpace | null;
  /** The active tab's link, if any. Named so the user knows what a re-save replaces. */
  linked?: SavedQueryLink;
  /** Inline message from the host: a mapped write failure. */
  error?: string | null;
  /** A write is in flight: locks submit and dismissal. */
  busy: boolean;
  onSave: (request: SaveQueryRequest) => void;
  onCancel: () => void;
};

/**
 * Name-and-destination prompt for saving the active tab's SQL as a `.sql` file.
 *
 * EVERY save asks, a linked tab's included — a change from the silent write-back
 * to the query it was opened from. A user about to overwrite a file should be told which
 * file, in which space, before it happens.
 *
 * the destination is a CHOICE, defaulted to the tab's own space when it
 * is linked and to the remembered one otherwise — one memory of "the space I am working
 * in", shared with the load surface rather than a second that can disagree with it.
 *
 * The collision is not detected here: SPEC-043 scanned the in-memory list
 * case-insensitively, which stopped being sound once the list is paginated and the target
 * space may not be the one on screen. `writeSavedQuery` HEADs the exact key and the host
 * turns its `Collision` failure into the replace confirm.
 */
export function SaveQueryDialog({initialName, spaces, initialSpace, linked, error, busy, onSave, onCancel}: Props) {
  const [name, setName] = useState(initialName);
  const [spaceId, setSpaceId] = useState(initialSpace?.id ?? spaces[0]?.id ?? '');
  // Validation runs on SUBMIT (FR-002 AC5), not as a disabled condition: a refusal the
  // user cannot reach is dead code an "it's disabled" test passes straight over
  // (SPEC-167). Cleared as they type, so the message never outlives the value it judged.
  const [submitError, setSubmitError] = useState<string | null>(null);
  // …and the same is true of the HOST's message, which this cannot clear because it does
  // not own it. An `AccessDenied` for one destination, still pinned to the field after the
  // user has picked another, describes a choice they have already abandoned.
  const [hostErrorStale, setHostErrorStale] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0] ?? null;

  // FR-007: no space to write into at all — the user-space bucket is unconfigured. The
  // dialog OPENS and explains itself rather than the toolbar rendering a disabled button
  // with nothing to say. There is genuinely nothing to submit, so submit is unavailable
  // and the banner is the whole content.
  if (spaces.length === 0 || !space) {
    return (
      <FormDialog
        title="Save query"
        ariaLabel="Save query"
        submitLabel="Save"
        submitDisabled
        onSubmit={onCancel}
        onCancel={onCancel}>
        <p className="mt-3 text-sm text-text-2">
          There’s nowhere to save this query. Your files aren’t available right now, so there is no space to write it
          into. Copy the SQL somewhere safe and try again later.
        </p>
      </FormDialog>
    );
  }

  // Whether submitting as typed re-saves the file this tab was opened from — the same
  // key, so the host writes it without a second confirm (FR-004). The predicate is the
  // service's, shared with the host, so the sentence and the write cannot disagree.
  const replacesLinked = isLinkedSavedQuery(linked, space, name);

  return (
    <FormDialog
      title="Save query"
      ariaLabel="Save query"
      submitLabel="Save"
      busy={busy}
      busyLabel="Saving…"
      autoFocusRef={inputRef}
      autoFocusSelect
      onSubmit={() => {
        const trimmed = name.trim();
        const nameError = validateSavedQueryName(trimmed);
        if (nameError) {
          setSubmitError(nameError);
          return;
        }
        setSubmitError(null);
        setHostErrorStale(false);
        onSave({space, name: trimmed});
      }}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <div className="mt-3 space-y-3">
        <SavedQuerySpaceSelect
          spaces={spaces}
          space={space}
          onSelectSpace={(id) => {
            setSpaceId(id);
            setHostErrorStale(true);
          }}
        />
        <Input
          ref={inputRef}
          id="saved-query-name"
          label="Name"
          required
          aria-required="true"
          value={name}
          error={submitError ?? (hostErrorStale ? undefined : (error ?? undefined))}
          placeholder="e.g. Monthly revenue"
          onChange={(e) => {
            setName(e.target.value);
            setSubmitError(null);
            setHostErrorStale(true);
          }}
        />
        <p className="text-sm text-text-3">
          Saved as a <code>.sql</code> file in {space.label} → <code>saved_queries</code>
          {replacesLinked ? ', replacing the file this tab was opened from' : ''}. Everyone with access to that space
          can open it.
        </p>
      </div>
    </FormDialog>
  );
}
