import {useCallback, useEffect, useMemo, useReducer, useRef, type ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {invalidateListing} from './invalidateListing';
import {toUserText} from '../../lib/errorMessages';
import {uploadFile} from './fileBrowser.service';
import {MAX_UPLOAD_BYTES} from './fileBrowser.types';
import {UPLOAD_CONCURRENCY, type UploadItem} from './upload.types';
import {
  UploadQueueContext,
  uploadQueueReducer,
  initialUploadQueueState,
  keyPrefix,
  type NewUploadEntry,
  type UploadDestination,
  type UploadQueueContextValue
} from './uploadQueueContext';

// Drives the upload queue. The
// pure reducer (uploadQueueContext) owns the item list; this provider runs the
// side effects — a concurrency gate that starts queued items via the uploader's
// `uploadFile`, wires progress + cancel, and invalidates the listing as each
// upload finishes.
//
// The provider is mounted once at the authenticated app shell (ProtectedLayout),
// so the queue is SESSION-scoped: uploads keep running across folder navigation,
// connection (bucket) switches, route changes, and drawer open/close — they are
// only aborted when the session ends (the provider unmounts on sign-out). Each
// item therefore carries its own destination bucket + key, captured at enqueue
// time, so navigating elsewhere mid-upload never re-targets an in-flight upload.
export function UploadQueueProvider({children}: {children: ReactNode}) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(uploadQueueReducer, initialUploadQueueState);

  // Latest items for the cancel callback — read in the callback without making it
  // churn on every change. Synced in an effect (not during render) so the stable
  // callback always sees the last commit.
  const itemsRef = useRef(state.items);
  useEffect(() => {
    itemsRef.current = state.items;
  }, [state.items]);

  // Per-item AbortControllers (cancel) and a launched-id guard so StrictMode's
  // double effect invocation can't start the same upload twice.
  const controllers = useRef<Map<string, AbortController>>(new Map());
  const launched = useRef<Set<string>>(new Set());

  const launch = useCallback(
    async (item: UploadItem) => {
      const controller = new AbortController();
      controllers.current.set(item.id, controller);
      dispatch({type: 'start', id: item.id});

      const result = await uploadFile({
        bucket: item.bucket,
        key: item.key,
        body: item.file,
        contentType: item.file.type || 'application/octet-stream',
        overwrite: item.overwrite,
        onProgress: (loaded, total) => dispatch({type: 'progress', id: item.id, loaded, total}),
        signal: controller.signal
      });

      controllers.current.delete(item.id);
      launched.current.delete(item.id);

      if (result.success) {
        dispatch({type: 'succeed', id: item.id});
        // Invalidate the destination folder so the finished file appears there,
        // whether or not the user is still viewing it (FR-001).
        await invalidateListing(queryClient, item.bucket, keyPrefix(item.key));
      } else if (result.error.code === 'Cancelled') {
        dispatch({type: 'cancelled', id: item.id});
      } else if (result.error.code === 'Collision') {
        dispatch({type: 'collision', id: item.id});
      } else {
        // Map to friendly text here (the code is in scope) so UploadList never
        // renders the raw AWS message.
        dispatch({type: 'fail', id: item.id, error: toUserText(result.error)});
      }
    },
    [queryClient]
  );

  // Concurrency gate: whenever the queue changes, fill open slots with the next
  // queued items, up to UPLOAD_CONCURRENCY in flight (FR-001). Idempotent under
  // StrictMode via the `launched` guard.
  useEffect(() => {
    const inFlight = state.items.filter((i) => i.status === 'uploading').length;
    let slots = UPLOAD_CONCURRENCY - inFlight;
    if (slots <= 0) return;
    for (const item of state.items) {
      if (slots <= 0) break;
      if (item.status === 'queued' && !launched.current.has(item.id)) {
        launched.current.add(item.id);
        slots -= 1;
        void launch(item);
      }
    }
  }, [state.items, launch]);

  // Abort everything in flight when the provider unmounts. Mounted at the app
  // shell, that happens only when the session ends (sign-out) — so in-flight
  // uploads survive navigation and run for the whole session, and lib-storage
  // aborts the multipart uploads on sign-out rather than leaking orphaned parts.
  useEffect(() => {
    const map = controllers.current;
    return () => {
      for (const controller of map.values()) controller.abort();
    };
  }, []);

  const enqueue = useCallback((files: File[], dest: UploadDestination) => {
    const entries: NewUploadEntry[] = files.map((file) => {
      const key = dest.prefix + file.name;
      if (file.size > MAX_UPLOAD_BYTES) {
        return {
          file,
          bucket: dest.bucket,
          key,
          status: 'failed',
          error: 'This file exceeds the maximum upload size.'
        };
      }
      return {file, bucket: dest.bucket, key, status: 'queued'};
    });
    if (entries.length > 0) dispatch({type: 'enqueue', entries});
  }, []);

  const cancel = useCallback((id: string) => {
    const item = itemsRef.current.find((i) => i.id === id);
    if (!item) return;
    if (item.status === 'uploading') {
      // Abort the in-flight upload; `launch` resolves to the Cancelled branch and
      // transitions the item, so no listed object remains (FR-002).
      controllers.current.get(id)?.abort();
    } else {
      // Queued or awaiting a collision decision — nothing was written; drop it.
      launched.current.delete(id);
      dispatch({type: 'remove', id});
    }
  }, []);

  const dismiss = useCallback((id: string) => dispatch({type: 'remove', id}), []);
  const resolveOverwrite = useCallback((id: string) => dispatch({type: 'retryOverwrite', id}), []);
  const resolveRename = useCallback((id: string, newName: string) => dispatch({type: 'retryRename', id, newName}), []);
  const clearFinished = useCallback(() => dispatch({type: 'clearFinished'}), []);

  const value = useMemo<UploadQueueContextValue>(
    () => ({
      items: state.items,
      enqueue,
      cancel,
      dismiss,
      resolveOverwrite,
      resolveRename,
      clearFinished
    }),
    [state.items, enqueue, cancel, dismiss, resolveOverwrite, resolveRename, clearFinished]
  );

  return <UploadQueueContext.Provider value={value}>{children}</UploadQueueContext.Provider>;
}
