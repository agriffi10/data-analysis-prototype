import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { invalidateListing } from '../../lib/queryClient';
import {
  copyObject,
  copyFolder,
  objectExists,
  uploadPercent,
  validateFolderName,
} from './fileBrowser.service';
import type { SelectableItem } from './selectionContext';

// Aggregated outcome of a (possibly multi-item, recursive) copy: how many objects
// S3 duplicated, and any per-item/per-key failures (SPEC-039 FR-004).
export type CopySummary = {
  copiedCount: number;
  errors: { item: string; message: string }[];
};

// A copy into a different folder hit existing destination objects (FR-005). One
// confirmation covers the whole batch: Overwrite all (re-run just the collided
// items) or cancel.
type CopyCollision = {
  count: number;
  onOverwriteAll: () => void;
  onCancel: () => void;
};

// A same-folder copy (FR-003): the source name necessarily collides, so the app
// proposes an auto-numbered name the user can edit before the copy runs.
type SameFolderPrompt = {
  kind: 'file' | 'folder';
  proposedName: string; // the editable, pre-filled non-colliding name
  validate: (name: string) => string | null; // create-folder/rename rules
  onConfirm: (name: string) => void;
  onCancel: () => void;
};

export type UseCopyResult = {
  isBusy: boolean;
  progress: number | null; // 0..100 while a folder operation runs, else null
  error: string | null;
  summary: CopySummary | null;
  copyCollision: CopyCollision | null;
  sameFolderPrompt: SameFolderPrompt | null;
  copyItems: (items: SelectableItem[], destPrefix: string) => void;
  dismissError: () => void;
  dismissSummary: () => void;
  cancelCollision: () => void;
};

// Leaf (last segment) of a file key: `a/b/c.txt` → `c.txt`.
function leafName(key: string): string {
  const i = key.lastIndexOf('/');
  return i === -1 ? key : key.slice(i + 1);
}

// Parent prefix + leaf name of a folder prefix: `a/b/photos/` → `{ parent: 'a/b/', leaf: 'photos' }`.
function folderParts(prefix: string): { parent: string; leaf: string } {
  const trimmed = prefix.replace(/\/$/, '');
  const i = trimmed.lastIndexOf('/');
  return i === -1
    ? { parent: '', leaf: trimmed }
    : { parent: trimmed.slice(0, i + 1), leaf: trimmed.slice(i + 1) };
}

// Insert a ` (N)` suffix into a file name before its extension, or onto a folder
// leaf (FR-003): `report.pdf` → `report (1).pdf`; `docs` → `docs (1)`. A leading
// dot (dotfile, no real extension) is treated as having no extension.
function numberedName(name: string, n: number, isFile: boolean): string {
  if (!isFile) return `${name} (${n})`;
  const dot = name.lastIndexOf('.');
  if (dot <= 0) return `${name} (${n})`;
  return `${name.slice(0, dot)} (${n})${name.slice(dot)}`;
}

type Acc = { copied: number; errors: CopySummary['errors'] };

// SPEC-039 Phase 2: orchestrates copy (single + multi-select) on top of the
// copyObject/copyFolder service primitives. Mirrors useMove, but copy is additive
// (no source delete) so ONLY the destination prefix is invalidated — the source
// listing is unchanged. Adds the same-folder auto-number flow (FR-003) when the
// chosen destination is the items' current parent. Never throws.
export function useCopy(
  bucket: string,
  sourcePrefix: string,
  username?: string,
): UseCopyResult {
  const queryClient = useQueryClient();
  const [isBusy, setIsBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<CopySummary | null>(null);
  const [copyCollision, setCopyCollision] = useState<CopyCollision | null>(null);
  const [sameFolderPrompt, setSameFolderPrompt] =
    useState<SameFolderPrompt | null>(null);

  async function invalidateDest(destPrefix: string) {
    await invalidateListing(queryClient, bucket, destPrefix);
  }

  // ── Same-folder copy (FR-003) ──────────────────────────────────────────────
  // Find the first ` (N)` name that doesn't already exist at the destination,
  // HEAD-checking each candidate. `baseName` is the source's leaf; `destPrefix`
  // is the folder it will sit in. For a folder, the dest key is `{name}/`.
  async function firstFreeName(
    baseName: string,
    destPrefix: string,
    isFile: boolean,
  ): Promise<string | null> {
    for (let n = 1; n < 1000; n += 1) {
      const candidate = numberedName(baseName, n, isFile);
      const key = isFile ? `${destPrefix}${candidate}` : `${destPrefix}${candidate}/`;
      const exists = await objectExists({ bucket, key });
      if (!exists.success) return null; // surface the error to the caller
      if (!exists.data) return candidate;
    }
    return null;
  }

  // Runs a same-folder copy of a single item to an explicit (already-validated,
  // non-colliding) name within `destPrefix`. Folder copies recurse.
  async function runSameFolderCopy(
    item: SelectableItem,
    destPrefix: string,
    name: string,
  ) {
    setIsBusy(true);
    setError(null);
    setSummary(null);

    let outcome:
      | { ok: true; copied: number; errors: CopySummary['errors'] }
      | { ok: false; message: string };

    if (item.type === 'file') {
      const r = await copyObject({
        bucket,
        sourceKey: item.key,
        destKey: `${destPrefix}${name}`,
        username: username!,
        // The name was HEAD-checked free (or the user picked it), but a genuine
        // collision still gets a clear failure rather than a silent clobber.
        overwrite: false,
      });
      outcome = r.success
        ? { ok: true, copied: 1, errors: [] }
        : { ok: false, message: r.error.message };
    } else {
      const r = await copyFolder({
        bucket,
        sourcePrefix: item.prefix,
        destPrefix: `${destPrefix}${name}/`,
        username: username!,
        onProgress: (p, t) => setProgress(uploadPercent(p, t)),
      });
      outcome = r.success
        ? {
            ok: true,
            copied: r.data.copied.length,
            errors: r.data.errors.map((e) => ({
              item: e.key,
              message: e.message,
            })),
          }
        : { ok: false, message: r.error.message };
    }

    setProgress(null);

    if (!outcome.ok) {
      setError(outcome.message);
      setIsBusy(false);
      return;
    }

    await invalidateDest(destPrefix);
    setSummary({ copiedCount: outcome.copied, errors: outcome.errors });
    setIsBusy(false);
  }

  // Opens the editable same-folder prompt with a freshly-computed non-colliding
  // name (FR-003). Single item only (the destination is its own parent).
  async function startSameFolderCopy(item: SelectableItem, destPrefix: string) {
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

    setSameFolderPrompt({
      kind: item.type,
      proposedName: proposed,
      validate: validateFolderName,
      onConfirm: (name) => {
        setSameFolderPrompt(null);
        void runSameFolderCopy(item, destPrefix, name.trim());
      },
      onCancel: () => {
        setSameFolderPrompt(null);
      },
    });
  }

  // ── Copy to a different folder ─────────────────────────────────────────────
  async function runCopy(
    items: SelectableItem[],
    destPrefix: string,
    overwrite: boolean,
    acc: Acc,
  ) {
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
          username: username!,
          overwrite,
        });
        if (r.success) acc.copied += 1;
        else if (r.error.code === 'Collision') collided.push(item);
        else acc.errors.push({ item: item.key, message: r.error.message });
      } else {
        const { leaf } = folderParts(item.prefix);
        const r = await copyFolder({
          bucket,
          sourcePrefix: item.prefix,
          destPrefix: `${destPrefix}${leaf}/`,
          username: username!,
          overwrite,
          onProgress: (p, t) => setProgress(uploadPercent(p, t)),
        });
        if (r.success) {
          acc.copied += r.data.copied.length;
          acc.errors.push(
            ...r.data.errors.map((e) => ({ item: e.key, message: e.message })),
          );
        } else if (r.error.code === 'Collision') {
          collided.push(item);
        } else {
          acc.errors.push({ item: item.prefix, message: r.error.message });
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
          void runCopy(collided, destPrefix, true, acc);
        },
        onCancel: () => {
          setCopyCollision(null);
          void finalizeCopy(acc, destPrefix);
        },
      });
      return;
    }

    await finalizeCopy(acc, destPrefix);
  }

  async function finalizeCopy(acc: Acc, destPrefix: string) {
    // Copy is additive: only the DESTINATION listing changed (FR-004).
    await invalidateDest(destPrefix);
    setSummary({ copiedCount: acc.copied, errors: acc.errors });
    setIsBusy(false);
  }

  // Entry point. If the chosen destination is the items' current parent, this is
  // a same-folder copy (FR-003) — only valid for a single item (the auto-number
  // prompt is per-item). Otherwise it's an ordinary copy to a different folder.
  function copyItems(items: SelectableItem[], destPrefix: string) {
    if (!username) {
      setError('You must be signed in to copy files.');
      return;
    }
    if (items.length === 0) return;

    if (destPrefix === sourcePrefix) {
      // Same-folder copy (FR-003): place the item beside itself under an
      // editable auto-numbered name. The auto-number prompt is per-item, so this
      // path is single-item by design — same-folder copy is offered for one
      // selected item; copying many items in place is not a v1 flow.
      void startSameFolderCopy(items[0], destPrefix);
      return;
    }

    void runCopy(items, destPrefix, false, { copied: 0, errors: [] });
  }

  return {
    isBusy,
    progress,
    error,
    summary,
    copyCollision,
    sameFolderPrompt,
    copyItems,
    dismissError: () => setError(null),
    dismissSummary: () => setSummary(null),
    cancelCollision: () => {
      setCopyCollision(null);
      setSameFolderPrompt(null);
      setIsBusy(false);
    },
  };
}
