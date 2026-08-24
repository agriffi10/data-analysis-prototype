import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {copyObject, copyFolder, objectExists, uploadPercent, validateFolderName} from './fileBrowser.service';
import {leafName, folderParts} from './fileBrowser.paths';
import type {SelectableItem} from './selectionContext';
import type {BulkOperationState} from './fileBrowser.types';

/**
 * Aggregated outcome of a (possibly multi-item, recursive) copy: how many
 * objects S3 duplicated, and any per-item/per-key failures.
 */
export type CopySummary = NonNullable<BulkOperationState['summary']>;

// A copy into a different folder hit existing destination objects. One
// confirmation covers the whole batch: Overwrite all (re-run just the collided
// items) or cancel.
type CopyCollision = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

/**
 * A same-folder copy: the source name necessarily collides, so the app proposes an auto-numbered
 * name the user can edit before the copy runs.
 *
 * DATA ONLY — no `onConfirm`, no `onCancel`. The probe's result is the `targetName` of whichever
 * request follows, and only the dispatcher knows whether that is the synchronous copy (a single
 * file) or an enqueued one (a single folder). Owning the callbacks here would have meant deciding
 * that before the probe had resolved, which is the one ordering this flow cannot take.
 */
export type SameFolderPrompt = {
  kind: 'file' | 'folder';
  /** The editable, pre-filled non-colliding name. */
  proposedName: string;
  /** Create-folder/rename rules. */
  validate: (name: string) => string | null;
};

export type UseCopyResult = BulkOperationState & {
  sameFolderPrompt: SameFolderPrompt | null;
  /**
   * HEAD-probes for the first free `{name} (N)` and opens the prompt. Single item only — the
   * destination is its own parent, and the prompt names one thing.
   */
  startSameFolderCopy: (item: SelectableItem, destPrefix: string) => void;
  /** Runs the synchronous same-folder copy under an already-chosen, already-validated name. */
  runSameFolderCopy: (item: SelectableItem, destPrefix: string, name: string) => void;
  clearSameFolderPrompt: () => void;
  /**
   * Copies into a DIFFERENT folder. `destBucket` defaults to the source bucket; pass a different
   * connection's bucket to copy across connections.
   *
   * There is no same-folder branch here: the probe runs once, at
   * {@link UseCopyResult.startSameFolderCopy}, before the routing decision that needs its answer.
   * A second branch would probe again — up to 999 sequential `HeadObject` calls — and could
   * propose a different name from the one the user just confirmed.
   */
  copyItems: (items: SelectableItem[], destPrefix: string, destBucket?: string) => void;
  cancelCollision: () => void;
};

// Insert a ` (N)` suffix into a file name before its extension, or onto a folder
// leaf: `report.pdf` → `report (1).pdf`; `docs` → `docs (1)`. A leading dot
// (dotfile, no real extension) is treated as having no extension.
function numberedName(name: string, n: number, isFile: boolean): string {
  if (!isFile) return `${name} (${n})`;
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return `${name} (${n})`;
  return `${name.slice(0, dot)} (${n})${name.slice(dot)}`;
}

type Acc = {copied: number; errors: CopySummary['errors']};

/**
 * Orchestrates copy (single + multi-select) on top of the copyObject/copyFolder
 * service primitives. Mirrors useMove, but copy is additive (no source delete)
 * so ONLY the destination prefix is invalidated — the source listing is
 * unchanged. Supplies the same-folder auto-number probe and the copy that follows it as separate
 * steps, because the caller decides between them on the probe's own answer. Never throws.
 *
 * It takes no source prefix. It used to, only to recognise "the destination is where these items
 * already are" — a question the caller now has to answer BEFORE it calls anything here, since the
 * probed name is what the routing decision is made with.
 */
export function useCopy(bucket: string, username?: string): UseCopyResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<CopySummary | null>(null);
  const [copyCollision, setCopyCollision] = useState<CopyCollision | null>(null);
  const [sameFolderPrompt, setSameFolderPrompt] = useState<SameFolderPrompt | null>(null);

  async function invalidateDest(destPrefix: string, destBucket: string) {
    await invalidateListing(queryClient, destBucket, destPrefix);
  }

  // ── Same-folder copy ───────────────────────────────────────────────────────
  // Find the first ` (N)` name that doesn't already exist at the destination,
  // HEAD-checking each candidate. `baseName` is the source's leaf; `destPrefix`
  // is the folder it will sit in. For a folder, the dest key is `{name}/`.
  async function firstFreeName(baseName: string, destPrefix: string, isFile: boolean): Promise<string | null> {
    for (let n = 1; n < 1000; n += 1) {
      const candidate = numberedName(baseName, n, isFile);
      const key = isFile ? `${destPrefix}${candidate}` : `${destPrefix}${candidate}/`;
      const exists = await objectExists({bucket, key});
      if (!exists.success) return null; // surface the error to the caller
      if (!exists.data) return candidate;
    }
    return null;
  }

  // Runs a same-folder copy of a single item to an explicit (already-validated,
  // non-colliding) name within `destPrefix`. Folder copies recurse.
  async function runSameFolderCopy(item: SelectableItem, destPrefix: string, name: string) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    let outcome:
      | {ok: true; copied: number; errors: CopySummary['errors']}
      | {ok: false; code?: string; message: string};

    if (item.type === 'file') {
      const r = await copyObject({
        bucket,
        sourceKey: item.key,
        destKey: `${destPrefix}${name}`,
        username,
        // The name was HEAD-checked free (or the user picked it), but a genuine
        // collision still gets a clear failure rather than a silent clobber.
        overwrite: false
      });
      outcome = r.success
        ? {ok: true, copied: 1, errors: []}
        : {ok: false, code: r.error.code, message: r.error.message};
    } else {
      const r = await copyFolder({
        bucket,
        sourcePrefix: item.prefix,
        destPrefix: `${destPrefix}${name}/`,
        username,
        onProgress: (p, t) => setProgress(uploadPercent(p, t))
      });
      outcome = r.success
        ? {
            ok: true,
            copied: r.data.copied.length,
            errors: r.data.errors.map((e) => ({
              key: e.key,
              message: e.message,
              code: e.code
            }))
          }
        : {ok: false, code: r.error.code, message: r.error.message};
    }

    setProgress(null);

    if (!outcome.ok) {
      setError(toUserText({code: outcome.code, message: outcome.message}));
      setIsBusy(false);
      return;
    }

    // Same-folder copy is always within the source bucket.
    await invalidateDest(destPrefix, bucket);
    setSummary({count: outcome.copied, errors: outcome.errors});
    setIsBusy(false);
  }

  // Opens the editable same-folder prompt with a freshly-computed non-colliding
  // name. Single item only (the destination is its own parent).
  async function startSameFolderCopy(item: SelectableItem, destPrefix: string) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    const isFile = item.type === 'file';
    const baseName = isFile ? leafName(item.key) : folderParts(item.prefix).leaf;
    const proposed = await firstFreeName(baseName, destPrefix, isFile);
    setIsBusy(false);

    if (proposed === null) {
      setError('Could not find an available name for the copy.');
      return;
    }

    setSameFolderPrompt({kind: item.type, proposedName: proposed, validate: validateFolderName});
  }

  // ── Copy to a different folder ─────────────────────────────────────────────
  async function runCopy(
    items: SelectableItem[],
    destPrefix: string,
    destBucket: string,
    overwrite: boolean,
    acc: Acc
  ) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    setIsBusy(true);
    setError(null);
    setSummary(null);

    const collided: SelectableItem[] = [];

    // Collision is checked before any write, so a collided item did nothing — it
    // can be safely re-run with overwrite after confirmation.
    for (const item of items) {
      if (item.type === 'file') {
        const r = await copyObject({
          bucket,
          sourceKey: item.key,
          destKey: destPrefix + leafName(item.key),
          username,
          destBucket,
          overwrite
        });
        if (r.success) acc.copied += 1;
        else if (r.error.code === 'Collision') collided.push(item);
        else acc.errors.push({key: item.key, message: r.error.message, code: r.error.code});
      } else {
        const {leaf} = folderParts(item.prefix);
        const r = await copyFolder({
          bucket,
          sourcePrefix: item.prefix,
          destPrefix: `${destPrefix}${leaf}/`,
          username,
          destBucket,
          overwrite,
          onProgress: (p, t) => setProgress(uploadPercent(p, t))
        });
        if (r.success) {
          acc.copied += r.data.copied.length;
          acc.errors.push(...r.data.errors.map((e) => ({key: e.key, message: e.message, code: e.code})));
        } else if (r.error.code === 'Collision') {
          collided.push(item);
        } else {
          acc.errors.push({key: item.prefix, message: r.error.message, code: r.error.code});
        }
      }
    }

    setProgress(null);

    if (collided.length > 0 && !overwrite) {
      setIsBusy(false);
      setCopyCollision({
        count: collided.length,
        onOverwriteAll: () => {
          setCopyCollision(null);
          void runCopy(collided, destPrefix, destBucket, true, acc);
        },
        onCancel: () => {
          setCopyCollision(null);
          void finalizeCopy(acc, destPrefix, destBucket);
        }
      });
      return;
    }

    await finalizeCopy(acc, destPrefix, destBucket);
  }

  async function finalizeCopy(acc: Acc, destPrefix: string, destBucket: string) {
    // Copy is additive: only the DESTINATION listing changed.
    await invalidateDest(destPrefix, destBucket);
    setSummary({count: acc.copied, errors: acc.errors});
    setIsBusy(false);
  }

  // Entry point for a copy into a DIFFERENT folder, possibly in another connection's bucket. The
  // same-folder case never arrives here: its destination is the items' own parent, so it needs
  // the auto-number probe FIRST — the caller runs that and then decides where the copy goes.
  function copyItems(items: SelectableItem[], destPrefix: string, destBucket: string = bucket) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    if (items.length === 0) return;

    void runCopy(items, destPrefix, destBucket, false, {copied: 0, errors: []});
  }

  return {
    isBusy,
    progress,
    error,
    summary,
    collision: copyCollision,
    sameFolderPrompt,
    startSameFolderCopy: (item, destPrefix) => void startSameFolderCopy(item, destPrefix),
    runSameFolderCopy: (item, destPrefix, name) => void runSameFolderCopy(item, destPrefix, name),
    clearSameFolderPrompt: () => setSameFolderPrompt(null),
    copyItems,
    dismissError: () => setError(null),
    dismissSummary: () => setSummary(null),
    cancelCollision: () => {
      setCopyCollision(null);
      setSameFolderPrompt(null);
      setIsBusy(false);
    }
  };
}
