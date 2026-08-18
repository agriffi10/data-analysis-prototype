import {useState} from 'react';
import {toUserText} from '../../lib/errorMessages';
import {toServiceError} from '../../lib/serviceResult';
import {
  ensureSavedQueriesFolder,
  isLinkedSavedQuery,
  validateSavedQueryName,
  writeSavedQuery
} from './savedQueries.service';
import type {ToastApi} from '../../components/toastContext';
import type {SavedQuery, SavedQueryLink} from './savedQueries.types';
import type {QuerySpace} from '../catalog/catalog.types';
import type {SaveQueryRequest} from './SaveQueryDialog';

/**
 * What is being saved: the body, and the file it would replace in place.
 *
 * this was the Query workspace's `QueryTab`, which is a shape no other
 * caller can produce. Two fields is what the flow actually reads, so the collision-and-
 * confirm path the Query workspace got right is reusable rather than reimplemented.
 */
export type SaveQueryPayload = {
  /** The buffer written to the `.sql` object. */
  sql: string;
  /** Set when the buffer came from a saved query — what an unchanged re-save replaces. */
  link?: SavedQueryLink;
};

/** The pending Replace confirm: the key that already exists, and where. */
export type SaveQueryCollision = {space: QuerySpace; name: string};

export type UseSaveQueryResult = {
  /** The destinations the dialog offers, personal first. Empty drives FR-007's banner. */
  spaces: QuerySpace[];
  /** The payload's link, if any — what an unchanged re-save replaces. */
  linked: SavedQueryLink | undefined;
  open: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  busy: boolean;
  /** Inline message for the dialog's field — a mapped write failure, never raw AWS text. */
  error: string | null;
  /** Set when the write returned `Collision`; drives the Replace confirm. */
  collision: SaveQueryCollision | null;
  /** What the dialog opens with: the last submitted name, else the linked query's. */
  initialName: string;
  /** What the space control opens on: the link's own space, else the remembered one. */
  initialSpace: QuerySpace | null;
  save: (request: SaveQueryRequest) => void;
  confirmReplace: () => void;
  cancelReplace: () => void;
};

type Params = {
  /** Every space the user may write into, personal first — already view-gated. */
  spaces: QuerySpace[];
  /** The space remembered by `useSavedQuerySpace`, for an unlinked buffer. */
  defaultSpace: QuerySpace | null;
  payload: SaveQueryPayload;
  /**
   * The write landed. The body is handed back beside the file because the caller's dirty
   * marker is cleared against the bytes that were WRITTEN, not against whatever the buffer
   * holds by the time the async write returns.
   */
  onSaved: (query: SavedQuery, sql: string) => void;
  toast: ToastApi;
};

/**
 * The whole save path for a saved query: the prompt, the destination, the write, the
 * collision round-trip and the toast.
 *
 * EVERY save prompts — a linked buffer's included — so there is exactly one way a `.sql`
 * file is written and it always passes through the dialog. The one thing a linked
 * re-save skips is the SECOND confirm: when the chosen space and name resolve to the key
 * the buffer is already linked to, the file being replaced is the one whose name the user
 * is looking at, and asking again would be asking about the thing just answered.
 *
 * @param params.spaces - Writable destinations, personal first.
 * @param params.defaultSpace - The remembered space, for an unlinked buffer.
 * @param params.payload - The body being saved, and the file it would replace in place.
 * @param params.onSaved - Called with the written file and the body that was written.
 * @param params.toast - Where the success message goes; failures render inline instead.
 * @returns The dialog's open state, its inputs, and the three submit paths.
 */
export function useSaveQuery({spaces, defaultSpace, payload, onSaved, toast}: Params): UseSaveQueryResult {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collision, setCollision] = useState<SaveQueryCollision | null>(null);
  // What the user last submitted. A trip through the Replace confirm unmounts the dialog,
  // so without this it would come back with an empty field and the default destination —
  // discarding both halves of what they just chose.
  const [pending, setPending] = useState<SaveQueryRequest | null>(null);

  const linked = payload.link;
  // FR-001: a linked buffer opens on ITS OWN space, even when the remembered one differs;
  // a link whose space is no longer offered (membership revoked) falls back through the
  // remembered one to personal, exactly as `useSavedQuerySpace` does for a stored id.
  const linkedSpace = linked ? (spaces.find((s) => s.id === linked.spaceId) ?? null) : null;

  const write = (request: SaveQueryRequest, overwrite: boolean) => {
    const {space, name} = request;
    setPending(request);

    const nameError = validateSavedQueryName(name);
    if (nameError) {
      // FR-002 AC3: the message, the dialog still open, and NO request — the dialog
      // validates on submit too, so this is the guard for every other caller.
      setError(nameError);
      setOpen(true);
      setCollision(null);
      return;
    }

    const sql = payload.sql;
    setBusy(true);
    setError(null);
    void (async () => {
      // Best effort, and deliberately not awaited for its verdict: a failure here does not
      // block the write, because the `PutObject` below creates the prefix on its own.
      await ensureSavedQueriesFolder(space).catch(() => undefined);

      // The service does not throw by contract. A breach of it must not strand the dialog:
      // `busy` locks BOTH buttons and `Modal`'s dismissal, so a write that neither resolves
      // nor clears the flag leaves the buffer with no way out at all.
      const result = await writeSavedQuery({space, name, sql, overwrite}).catch((err: unknown) =>
        toServiceError(err, 'Failed to save query')
      );
      setBusy(false);
      if (!result.success) {
        if (result.error.code === 'Collision') {
          setOpen(false);
          setCollision({space, name});
          return;
        }
        // Clear the confirm too: it was raised by the FIRST attempt's collision, and
        // leaving it up after the replace itself failed offers a retry of a step that has
        // already happened. FR-006: the dialog stays open with the name and the space the
        // user chose, so another destination is one control away.
        setCollision(null);
        setOpen(true);
        setError(toUserText(result.error));
        return;
      }
      const query = result.data;
      onSaved(query, sql);
      setOpen(false);
      setCollision(null);
      setPending(null);
      setError(null);
      toast.push({variant: 'success', message: `Saved “${query.name}” to ${space.label}.`});
    })();
  };

  return {
    spaces,
    linked,
    open,
    openDialog: () => {
      setError(null);
      setPending(null);
      setOpen(true);
    },
    closeDialog: () => {
      setOpen(false);
      setError(null);
      setPending(null);
    },
    busy,
    error,
    collision,
    initialName: pending?.name ?? linked?.name ?? '',
    initialSpace: pending?.space ?? linkedSpace ?? defaultSpace,
    // FR-004: the in-place re-save writes through, because the file it replaces is the one
    // the user is looking at the name of. Any other key takes FR-003's HEAD-and-confirm.
    save: (request) => write(request, isLinkedSavedQuery(linked, request.space, request.name)),
    confirmReplace: () => {
      if (collision) write({space: collision.space, name: collision.name}, true);
    },
    cancelReplace: () => {
      setCollision(null);
      setOpen(true); // back to the dialog, with the name and space still chosen
    }
  };
}
