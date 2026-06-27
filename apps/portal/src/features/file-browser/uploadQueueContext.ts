import {createContext, useContext} from 'react';
import type {UploadItem, UploadStatus} from './upload.types';
import {TERMINAL_STATUSES} from './upload.types';

// SPEC-020: the upload-queue store. Like selectionContext (SPEC-018), the pure
// reducer + context + hook live in this non-component module so the reducer is
// unit-testable and UploadQueueProvider.tsx exports only its component
// (react-refresh requires component files to export components only).

export type UploadQueueContextValue = {
  items: UploadItem[];
  // Enqueue files for upload into the current folder; oversize files are added as
  // a `failed` item with the limit message rather than entering the active queue.
  enqueue: (files: File[]) => void;
  // Cancel an item: aborts an in-flight upload (→ cancelled) or drops a queued /
  // collision item that never wrote anything (FR-002).
  cancel: (id: string) => void;
  // Remove a terminal item from the queue.
  dismiss: (id: string) => void;
  // Collision resolution (SPEC-016 warn-and-confirm): re-queue with overwrite, or
  // re-queue under a new leaf name.
  resolveOverwrite: (id: string) => void;
  resolveRename: (id: string, newName: string) => void;
  // Remove every terminal (done / failed / cancelled) item at once.
  clearFinished: () => void;
};

export const UploadQueueContext = createContext<UploadQueueContextValue | null>(null);

// Consume the upload queue. Throws outside a provider so a missing provider is a
// loud development error, not a silent no-op (matches useSelection).
export function useUploadQueue(): UploadQueueContextValue {
  const ctx = useContext(UploadQueueContext);
  if (ctx === null) {
    throw new Error('useUploadQueue must be used within an UploadQueueProvider');
  }
  return ctx;
}

// The leaf-stripped prefix of a destination key: `alice/docs/a.txt` → `alice/docs/`,
// `a.txt` → ``. Used to target listing invalidation and to rebuild the key on
// rename without threading the prefix through the queue.
export function keyPrefix(key: string): string {
  const i = key.lastIndexOf('/');
  return i === -1 ? '' : key.slice(0, i + 1);
}

// ── Reducer (FR-001) ──────────────────────────────────────────────────────────

// A file the provider has prepared for enqueue: the destination key is computed
// (prefix + name) and oversize files arrive pre-marked `failed`. The reducer
// assigns the stable id from its monotonic `seq` counter (deterministic — no
// Math.random in shared code, per FR-001).
export type NewUploadEntry = {
  file: File;
  key: string;
  status: Extract<UploadStatus, 'queued' | 'failed'>;
  error?: string;
};

export type UploadQueueState = {
  items: UploadItem[];
  seq: number; // monotonic id source
};

export type UploadQueueAction =
  | {type: 'enqueue'; entries: NewUploadEntry[]}
  | {type: 'start'; id: string}
  | {type: 'progress'; id: string; loaded: number; total: number}
  | {type: 'succeed'; id: string}
  | {type: 'fail'; id: string; error: string}
  | {type: 'collision'; id: string}
  | {type: 'cancelled'; id: string}
  | {type: 'remove'; id: string}
  | {type: 'retryOverwrite'; id: string}
  | {type: 'retryRename'; id: string; newName: string}
  | {type: 'clearFinished'};

export const initialUploadQueueState: UploadQueueState = {items: [], seq: 0};

// Map the one matching item through `fn`, returning a fresh array (never mutates).
function patch(items: UploadItem[], id: string, fn: (item: UploadItem) => UploadItem): UploadItem[] {
  return items.map((item) => (item.id === id ? fn(item) : item));
}

export function uploadQueueReducer(state: UploadQueueState, action: UploadQueueAction): UploadQueueState {
  switch (action.type) {
    case 'enqueue': {
      let seq = state.seq;
      const added: UploadItem[] = action.entries.map((e) => ({
        id: `${seq++}-${e.file.name}`,
        file: e.file,
        key: e.key,
        status: e.status,
        loaded: 0,
        total: e.file.size,
        overwrite: false,
        error: e.error
      }));
      return {items: [...state.items, ...added], seq};
    }
    case 'start':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'uploading',
          loaded: 0,
          error: undefined
        }))
      };
    case 'progress':
      return {
        ...state,
        // Ignore stray progress for an item that's no longer uploading (e.g. a
        // late event after cancel) so a cancelled bar can't tick forward.
        items: patch(state.items, action.id, (it) =>
          it.status === 'uploading' ? {...it, loaded: action.loaded, total: action.total} : it
        )
      };
    case 'succeed':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'done',
          loaded: it.total
        }))
      };
    case 'fail':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'failed',
          error: action.error
        }))
      };
    case 'collision':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'collision'
        }))
      };
    case 'cancelled':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'cancelled'
        }))
      };
    case 'remove':
      return {...state, items: state.items.filter((it) => it.id !== action.id)};
    case 'retryOverwrite':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'queued',
          overwrite: true,
          loaded: 0,
          error: undefined
        }))
      };
    case 'retryRename':
      return {
        ...state,
        items: patch(state.items, action.id, (it) => ({
          ...it,
          status: 'queued',
          overwrite: false,
          loaded: 0,
          error: undefined,
          key: keyPrefix(it.key) + action.newName
        }))
      };
    case 'clearFinished':
      return {
        ...state,
        items: state.items.filter((it) => !TERMINAL_STATUSES.has(it.status))
      };
    default:
      return state;
  }
}
