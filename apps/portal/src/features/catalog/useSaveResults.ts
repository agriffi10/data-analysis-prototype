import {useState} from 'react';
import {useNavigate} from 'react-router';
import {useQueryClient} from '@tanstack/react-query';
import {copyObject, objectExists} from '../file-browser/fileBrowser.service';
import {invalidateListing} from '../file-browser';
import {parseS3Url} from '../../lib/s3Url';
import {spaceFor} from '../../lib/objectSpace';
import {toUserText} from '../../lib/errorMessages';
import {enqueueResultsConversion} from './resultsConversion.service';
import {RESULTS_FORMATS} from './catalog.format';
import type {ToastApi} from '../../components/toastContext';
import type {QuerySpace, ResultsFormat} from './catalog.types';

/**
 * A pending overwrite confirm when the chosen destination key already exists.
 * carries source + dest buckets so the retry repeats the same
 * (possibly cross-bucket) copy, and the format so it re-submits down the same
 * of the two paths.
 */
export type OverwritePrompt = {
  sourceBucket: string;
  sourceKey: string;
  destBucket: string;
  destPrefix: string;
  filename: string;
  format: ResultsFormat;
};

/**
 * The prompt to store for a destination that turned out to be taken.
 *
 * Written field by field rather than spread, so the caller's `overwrite` flag — which is an
 * argument to one attempt, not a property of the pending request — cannot ride into the state
 * that drives the next one.
 */
function pendingOverwrite(args: OverwritePrompt & {overwrite: boolean}): OverwritePrompt {
  return {
    sourceBucket: args.sourceBucket,
    sourceKey: args.sourceKey,
    destBucket: args.destBucket,
    destPrefix: args.destPrefix,
    filename: args.filename,
    format: args.format
  };
}

/**
 * What the save dialog opens with.
 *
 * A fresh open is the suggested name, as CSV, at the first space's root. After the overwrite
 * question is cancelled it is the name, format and folder that question was about: the dialog is
 * unmounted while the question is up, so without this it would come back at its defaults. The
 * name carries the extension the question showed, which is harmless — the dialog's normalizer
 * swaps a known extension, so choosing another format still saves under the right one.
 */
export type SaveResultsInitial = {
  name: string;
  format: ResultsFormat;
  /** The folder to open at, with its bucket. Absent on a fresh open. */
  destination?: {bucket: string; prefix: string};
};

export type UseSaveResultsResult = {
  /** The destinations offered by the picker; the dialog is suppressed when empty. */
  spaces: QuerySpace[];
  open: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  /** A copy is in flight; drives both the dialog's and the overwrite prompt's busy state. */
  busy: boolean;
  /** What the dialog's fields open with. */
  initial: SaveResultsInitial;
  overwritePrompt: OverwritePrompt | null;
  /** Save the currently displayed result into the chosen destination, in the chosen format. */
  save: (args: {destBucket: string; destPrefix: string; filename: string; format: ResultsFormat}) => void;
  confirmOverwrite: () => void;
  cancelOverwrite: () => void;
};

type Params = {
  /**
   * The destinations to offer, already gated.
   *
   * A PARAMETER rather than a `useQuerySpaces()` call inside the hook, on the space selector's
   * precedent, and for the reason `useSaveQuery` has the same shape. The hook read
   * the unfiltered list, so with `sharedWorkspaces` off this dialog went on offering a
   * colleague's space as a WRITE target after every other shared-workspace surface had gone
   * — and a flag may not be applied inside a hook that answers a question about access,
   * so the filter belongs at the view either way. Both call sites now
   * hand it a list they have gated.
   */
  spaces: QuerySpace[];
  username: string;
  /** The S3 URL of the result being displayed, or undefined when there is none. */
  outputLocation: string | undefined;
  /**
   * The execution `outputLocation` belongs to, or null when there is none.
   *
   * A SEPARATE parameter rather than the id parsed back out of the results URL: the two would
   * then be one fact with two derivations, and the conversion plane reads the execution rather
   * than the object — it re-reads the results and its metadata from Athena, so handing it an id
   * that disagreed with the URL would convert a different result than the one on screen. Both
   * callers already hold the id the location was derived from.
   */
  executionId: string | null;
  /** The active tab's linked saved-query name, used for the default file name. */
  linkedSavedName: string | undefined;
  toast: ToastApi;
};

/**
 * copy the displayed query result out of `athenaresults/` and into
 * a space the user can browse.
 *
 * A server-side `CopyObject` captures ALL rows, independent of how many pages the
 * results table loaded. A destination collision returns to a warn-and-confirm
 * rather than overwriting, and the destination listing is invalidated
 * so the new file appears if the user browses there.
 */
export function useSaveResults({
  spaces,
  username,
  outputLocation,
  executionId,
  linkedSavedName,
  toast
}: Params): UseSaveResultsResult {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [overwritePrompt, setOverwritePrompt] = useState<OverwritePrompt | null>(null);
  const [declined, setDeclined] = useState<OverwritePrompt | null>(null);

  // Default file name — the saved query's name when the tab is linked,
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

  const initial: SaveResultsInitial = declined
    ? {
        name: declined.filename,
        format: declined.format,
        destination: {bucket: declined.destBucket, prefix: declined.destPrefix}
      }
    : {name: defaultName, format: 'csv'};

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
          setOverwritePrompt(pendingOverwrite(args));
          return;
        }
        toast.push({variant: 'danger', message: `Couldn’t save results. ${toUserText(result.error)}`});
        return;
      }
      setOpen(false);
      setOverwritePrompt(null);
      void invalidateListing(queryClient, args.destBucket, args.destPrefix);
      // The deep link names its space, as the rail's "View source files" does: an absent
      // `?space=` resolves to the personal space, whose root refuses a shared prefix, so a shared
      // save's link would open the user's own files at their root. The id is the one `?space=`
      // takes — 'personal', or the shared-space name — and the prefix picks between spaces that
      // share a bucket. A destination no longer in `spaces` gets no link, because Files would
      // fall back to the personal space for it too.
      const destSpace = spaces.find((s) => s.bucket === args.destBucket && args.destPrefix.startsWith(s.rootPrefix));
      toast.push({
        variant: 'success',
        message: `Saved to ${args.destPrefix}${args.filename}`,
        ...(destSpace && {
          action: {
            label: 'View in Files',
            onClick: () => {
              toast.dismiss();
              navigate(
                `/files?space=${encodeURIComponent(destSpace.id)}&prefix=${encodeURIComponent(args.destPrefix)}`
              );
            }
          }
        })
      });
    })();
  };

  /**
   * Hand the conversion to the plane, after asking about a name already taken.
   *
   * The pre-flight is a COURTESY, not the guard: the plane's write is conditional and stays the
   * authority, so a name taken between this probe and that write comes back as a
   * `destination_occupied` notification rather than silently overwriting. What the probe buys is
   * the question being asked while the user is still looking at the dialog, instead of minutes
   * later in their inbox.
   */
  const doConvert = (args: OverwritePrompt & {overwrite: boolean}) => {
    if (!executionId || args.format === 'csv') return;
    // The plane's destination prefix is RELATIVE TO THE SPACE ROOT — it builds the key as
    // `{root}{prefix}{filename}`, so passing the full in-space prefix the picker deals in would
    // write `alice/alice/reports/…`. Nothing refuses that: the containment check only proves the
    // key starts with the root, which a doubled root does.
    const format = args.format;
    const space = spaceFor(args.destBucket, args.destPrefix);
    // The root is derived from the very string being sliced, and that is what makes the slice
    // TOTAL rather than conditional: `spaceFor` reads the name as `destPrefix.split('/')[0]`, so
    // `${name}/` is a prefix of `destPrefix` for every value that contains a slash — which every
    // folder prefix does, since the picker only ever hands out `rootPrefix` or a slash-terminated
    // descendant of it. Looking the root up in `spaces` instead needed a fallback for a
    // destination not in the list, and the only fallback available was the absolute prefix, which
    // is exactly the doubled-root key this slice exists to prevent.
    //
    // There is deliberately no guard here. An earlier revision refused a `destPrefix` that did not
    // start with its own first segment; a review planted its deletion and the whole suite stayed
    // green, because no reachable input can fail that test. A refusal that cannot fire reads as a
    // fence to everyone downstream while denying nobody, and it did not even cover the one shape
    // that could slip past it — a leading slash, which satisfies it and yields a doubled slash.
    const relativePrefix = args.destPrefix.slice(space.name.length + 1);

    setBusy(true);
    void (async () => {
      if (!args.overwrite) {
        const probe = await objectExists({bucket: args.destBucket, key: `${args.destPrefix}${args.filename}`});
        // A 403 counts as OCCUPIED. The space may hold a file this actor cannot see, and the
        // plane's conditional write will refuse it — so the honest question to ask now is the
        // overwrite one, not a failure the user can do nothing with.
        const occupied = probe.success ? probe.data : probe.error.code === 'AccessDenied';
        if (!probe.success && !occupied) {
          setBusy(false);
          toast.push({variant: 'danger', message: `Couldn’t save results. ${toUserText(probe.error)}`});
          return;
        }
        if (occupied) {
          setBusy(false);
          setOpen(false);
          setOverwritePrompt(pendingOverwrite(args));
          return;
        }
      }

      const result = await enqueueResultsConversion({
        requestId: crypto.randomUUID(),
        queryExecutionId: executionId,
        format,
        destination: {space, prefix: relativePrefix, filename: args.filename},
        onConflict: args.overwrite ? 'overwrite' : 'refuse',
        submittedAt: new Date().toISOString()
      });
      setBusy(false);
      if (!result.success) {
        toast.push({variant: 'danger', message: `Couldn’t save results. ${toUserText(result.error)}`});
        return;
      }
      setOpen(false);
      setOverwritePrompt(null);
      // NOTHING is invalidated: the plane has written nothing yet. The notification is the
      // completion channel, and the toast says so rather than implying the file is there.
      toast.push({
        variant: 'success',
        message: `Converting to ${RESULTS_FORMATS[format].label} — you’ll get a notification when ${args.filename} is ready.`
      });
    })();
  };

  const save = (args: {destBucket: string; destPrefix: string; filename: string; format: ResultsFormat}) => {
    // Save the DISPLAYED result (the active result tab's execution),
    // not necessarily the batch's last statement.
    if (!outputLocation) return;
    const parsed = parseS3Url(outputLocation);
    if (!parsed) {
      toast.push({variant: 'danger', message: 'Couldn’t read the query result location.'});
      return;
    }
    const pending = {...args, sourceBucket: parsed.bucket, sourceKey: parsed.key};
    // CSV is the copy this dialog has always done, unchanged; the other three go to the plane.
    if (args.format === 'csv') doSaveCopy({...pending, overwrite: false});
    else doConvert({...pending, overwrite: false});
  };

  return {
    spaces,
    open,
    openDialog: () => {
      setDeclined(null);
      setOpen(true);
    },
    closeDialog: () => setOpen(false),
    busy,
    initial,
    overwritePrompt,
    save,
    confirmOverwrite: () => {
      // Routed on the format the prompt was raised for, not on the dialog's current state —
      // the dialog is closed while the prompt is up, so its `format` is not readable from here
      // and re-deriving it would be a second source for one fact.
      if (!overwritePrompt) return;
      if (overwritePrompt.format === 'csv') doSaveCopy({...overwritePrompt, overwrite: true});
      else doConvert({...overwritePrompt, overwrite: true});
    },
    cancelOverwrite: () => {
      // Back to the dialog with the name editable, reopened where the question was asked.
      setDeclined(overwritePrompt);
      setOverwritePrompt(null);
      setOpen(true);
    }
  };
}
