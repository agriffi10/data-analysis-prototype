import {useMemo, useState} from 'react';
import {useNavigate} from 'react-router';
import {useQueryClient} from '@tanstack/react-query';
import {copyObject} from '../file-browser/fileBrowser.service';
import {invalidateListing} from '../file-browser';
import {parseS3Url} from '../../lib/s3Url';
import {toUserText} from '../../lib/errorMessages';
import {isConnectionUsable} from '../connections/connection.types';
import type {Connection} from '../connections/connection.types';
import type {ToastApi} from '../../components/toastContext';
import type {DestinationSpace} from './SaveResultsDialog';

/**
 * A pending overwrite confirm when the chosen destination key already exists.
 * SPEC-055: carries source + dest buckets so the retry repeats the same
 * (possibly cross-bucket) copy.
 */
export type OverwritePrompt = {
  sourceBucket: string;
  sourceKey: string;
  destBucket: string;
  destPrefix: string;
  filename: string;
};

export type UseSaveResultsResult = {
  /** The destinations offered by the picker; the dialog is suppressed when empty. */
  spaces: DestinationSpace[];
  open: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  /** A copy is in flight; drives both the dialog's and the overwrite prompt's busy state. */
  busy: boolean;
  /** Sanitized default file name for the picker. */
  defaultName: string;
  overwritePrompt: OverwritePrompt | null;
  /** Save the currently displayed result into the chosen destination. */
  save: (args: {destBucket: string; destPrefix: string; filename: string}) => void;
  confirmOverwrite: () => void;
  cancelOverwrite: () => void;
};

type Params = {
  username: string;
  userSpaceBucket: string | undefined;
  sharedSpaceBucket: string | undefined;
  connections: Connection[];
  /** The S3 URL of the result being displayed, or undefined when there is none. */
  outputLocation: string | undefined;
  /** The active tab's linked saved-query name, used for the default file name. */
  linkedSavedName: string | undefined;
  toast: ToastApi;
};

/**
 * SPEC-049/055: copy the displayed query result out of `athenaresults/` and into
 * a space the user can browse.
 *
 * A server-side `CopyObject` captures ALL rows, independent of how many pages the
 * results table loaded. A destination collision returns to a warn-and-confirm
 * (SPEC-039) rather than overwriting, and the destination listing is invalidated
 * so the new file appears if the user browses there.
 */
export function useSaveResults({
  username,
  userSpaceBucket,
  sharedSpaceBucket,
  connections,
  outputLocation,
  linkedSavedName,
  toast
}: Params): UseSaveResultsResult {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [overwritePrompt, setOverwritePrompt] = useState<OverwritePrompt | null>(null);

  // SPEC-055 FR-003: the spaces a result can be saved into — the user's own space
  // first, then every shared space they currently belong to (usable). The picker
  // excludes each space's protected `athenaresults/` folder.
  const spaces = useMemo<DestinationSpace[]>(() => {
    if (!userSpaceBucket) return [];
    const personal: DestinationSpace = {
      id: 'personal',
      label: 'My files',
      bucket: userSpaceBucket,
      rootPrefix: `${username}/`,
      rootLabel: 'My Files'
    };
    const shared: DestinationSpace[] = sharedSpaceBucket
      ? connections
          .filter((c) => c.kind === 'shared' && isConnectionUsable(c))
          .map((c) => ({
            id: c.database,
            label: c.database,
            bucket: sharedSpaceBucket,
            rootPrefix: `${c.database}/`,
            rootLabel: c.database
          }))
      : [];
    return [personal, ...shared];
  }, [userSpaceBucket, sharedSpaceBucket, username, connections]);

  // SPEC-049: default file name — the saved query's name when the tab is linked,
  // else a generic stamp; sanitized to the leaf-name rule (no slash/control chars).
  const defaultName = (() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, '0');
    const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
    const base = linkedSavedName
      ? // eslint-disable-next-line no-control-regex
        linkedSavedName.replace(/[/\x00-\x1f]/g, '-').trim()
      : 'query-results';
    return `${base}-${stamp}`;
  })();

  const doSaveCopy = (args: OverwritePrompt & {overwrite: boolean}) => {
    const destKey = `${args.destPrefix}${args.filename}`;
    setBusy(true);
    void (async () => {
      const result = await copyObject({
        bucket: args.sourceBucket,
        destBucket: args.destBucket,
        sourceKey: args.sourceKey,
        destKey,
        username,
        overwrite: args.overwrite
      });
      setBusy(false);
      if (!result.success) {
        if (result.error.code === 'Collision') {
          setOpen(false);
          setOverwritePrompt({
            sourceBucket: args.sourceBucket,
            sourceKey: args.sourceKey,
            destBucket: args.destBucket,
            destPrefix: args.destPrefix,
            filename: args.filename
          });
          return;
        }
        toast.push({variant: 'danger', message: `Couldn’t save results. ${toUserText(result.error)}`});
        return;
      }
      setOpen(false);
      setOverwritePrompt(null);
      void invalidateListing(queryClient, args.destBucket, args.destPrefix);
      // SPEC-055: the Files browser only renders the personal space until SPEC-057,
      // so the "View in Files" deep-link is offered only for a personal-space save.
      const isPersonalDest = args.destBucket === userSpaceBucket;
      toast.push({
        variant: 'success',
        message: `Saved to ${args.destPrefix}${args.filename}`,
        ...(isPersonalDest && {
          action: {
            label: 'View in Files',
            onClick: () => {
              toast.dismiss();
              navigate(`/files?prefix=${encodeURIComponent(args.destPrefix)}`);
            }
          }
        })
      });
    })();
  };

  const save = (args: {destBucket: string; destPrefix: string; filename: string}) => {
    // SPEC-078: save the DISPLAYED result (the active result tab's execution),
    // not necessarily the batch's last statement.
    if (!outputLocation) return;
    const parsed = parseS3Url(outputLocation);
    if (!parsed) {
      toast.push({variant: 'danger', message: 'Couldn’t read the query result location.'});
      return;
    }
    doSaveCopy({...args, sourceBucket: parsed.bucket, sourceKey: parsed.key, overwrite: false});
  };

  return {
    spaces,
    open,
    openDialog: () => setOpen(true),
    closeDialog: () => setOpen(false),
    busy,
    defaultName,
    overwritePrompt,
    save,
    confirmOverwrite: () => {
      if (overwritePrompt) doSaveCopy({...overwritePrompt, overwrite: true});
    },
    cancelOverwrite: () => {
      setOverwritePrompt(null);
      setOpen(true); // return to the dialog with the name editable
    }
  };
}
