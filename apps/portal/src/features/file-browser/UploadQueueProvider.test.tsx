import {renderHook, waitFor, act} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {createElement, type ReactNode} from 'react';
import {QueryClientProvider} from '@tanstack/react-query';
import {createTestQueryClient} from '../../test/renderWithProviders';
import {UploadQueueProvider} from './UploadQueueProvider';
import {useUploadQueue} from './uploadQueueContext';
import {uploadQueueReducer, initialUploadQueueState, type UploadQueueState} from './uploadQueueContext';
import {UPLOAD_CONCURRENCY, type UploadItem} from './upload.types';
import {uploadFile} from './fileBrowser.service';
import {apiRequest} from '../../lib/apiClient';
import {invalidateListing} from './invalidateListing';
import {maxUploadBytes} from './uploadLimits';

vi.mock('./fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof import('./fileBrowser.service')>()),
  uploadFile: vi.fn()
}));
// `importOriginal` rather than a factory listing exports: this suite renders a real tree, so it
// loads whatever the tree imports, and a factory goes red on a name it never used the moment one
// of those modules reaches for one more. That is not hypothetical — it happened to the data
// explorer's save suite in this same change.
vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));
vi.mock('./invalidateListing', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

const mockUpload = vi.mocked(uploadFile);
const mockInvalidate = vi.mocked(invalidateListing);

beforeEach(() => {
  vi.clearAllMocks();
});

// ─── Reducer (pure) ─────────────────────────────────────────────────────────

describe('uploadQueueReducer', () => {
  function item(over: Partial<UploadItem> = {}): UploadItem {
    return {
      id: '0-a.txt',
      file: new File(['x'], 'a.txt'),
      bucket: 'us',
      key: 'alice/a.txt',
      status: 'queued',
      loaded: 0,
      total: 1,
      overwrite: false,
      ...over
    };
  }

  function stateWith(items: UploadItem[], seq = items.length): UploadQueueState {
    return {items, seq};
  }

  it('enqueue appends items with monotonic, deterministic ids and advances seq', () => {
    const f1 = new File(['a'], 'a.txt');
    const f2 = new File(['bb'], 'b.txt');
    const next = uploadQueueReducer(initialUploadQueueState, {
      type: 'enqueue',
      entries: [
        {file: f1, bucket: 'us', key: 'alice/a.txt', status: 'queued'},
        {file: f2, bucket: 'us', key: 'alice/b.txt', status: 'queued'}
      ]
    });
    expect(next.items.map((i) => i.id)).toEqual(['0-a.txt', '1-b.txt']);
    expect(next.seq).toBe(2);
    expect(next.items[1].total).toBe(2); // file size
    // A second enqueue keeps ids unique by continuing the counter.
    const after = uploadQueueReducer(next, {
      type: 'enqueue',
      entries: [{file: f1, bucket: 'us', key: 'alice/a.txt', status: 'queued'}]
    });
    expect(after.items[2].id).toBe('2-a.txt');
  });

  it('drives an item queued → uploading → done, snapping loaded to total', () => {
    let s = stateWith([item()]);
    s = uploadQueueReducer(s, {type: 'start', id: '0-a.txt'});
    expect(s.items[0].status).toBe('uploading');
    s = uploadQueueReducer(s, {
      type: 'progress',
      id: '0-a.txt',
      loaded: 1,
      total: 1
    });
    expect(s.items[0].loaded).toBe(1);
    s = uploadQueueReducer(s, {type: 'succeed', id: '0-a.txt'});
    expect(s.items[0].status).toBe('done');
    expect(s.items[0].loaded).toBe(s.items[0].total);
  });

  it('ignores progress for an item that is no longer uploading', () => {
    const s = stateWith([item({status: 'cancelled', loaded: 0})]);
    const next = uploadQueueReducer(s, {
      type: 'progress',
      id: '0-a.txt',
      loaded: 99,
      total: 100
    });
    expect(next.items[0].loaded).toBe(0);
  });

  it('fail records the error; collision and cancelled set their status', () => {
    expect(
      uploadQueueReducer(stateWith([item({status: 'uploading'})]), {
        type: 'fail',
        id: '0-a.txt',
        error: 'Access Denied'
      }).items[0]
    ).toMatchObject({status: 'failed', error: 'Access Denied'});
    expect(
      uploadQueueReducer(stateWith([item({status: 'uploading'})]), {
        type: 'collision',
        id: '0-a.txt'
      }).items[0].status
    ).toBe('collision');
    expect(
      uploadQueueReducer(stateWith([item({status: 'uploading'})]), {
        type: 'cancelled',
        id: '0-a.txt'
      }).items[0].status
    ).toBe('cancelled');
  });

  it('retryOverwrite re-queues with overwrite; retryRename re-queues under a new leaf', () => {
    const over = uploadQueueReducer(stateWith([item({status: 'collision'})]), {
      type: 'retryOverwrite',
      id: '0-a.txt'
    });
    expect(over.items[0]).toMatchObject({status: 'queued', overwrite: true});

    const renamed = uploadQueueReducer(stateWith([item({status: 'collision', key: 'alice/docs/a.txt'})]), {
      type: 'retryRename',
      id: '0-a.txt',
      newName: 'b.txt'
    });
    expect(renamed.items[0]).toMatchObject({
      status: 'queued',
      overwrite: false,
      key: 'alice/docs/b.txt'
    });
  });

  it('remove drops one item; clearFinished drops only terminal items', () => {
    const items = [
      item({id: 'a', status: 'done'}),
      item({id: 'b', status: 'uploading'}),
      item({id: 'c', status: 'failed'}),
      item({id: 'd', status: 'queued'}),
      item({id: 'e', status: 'cancelled'})
    ];
    expect(uploadQueueReducer(stateWith(items), {type: 'remove', id: 'b'}).items.map((i) => i.id)).toEqual([
      'a',
      'c',
      'd',
      'e'
    ]);
    expect(uploadQueueReducer(stateWith(items), {type: 'clearFinished'}).items.map((i) => i.id)).toEqual(['b', 'd']); // uploading + queued survive
  });
});

// ─── Provider (concurrency gate + cancel) ───────────────────────────────────

// The provider is prop-less (session-scoped); each enqueue carries its own
// destination, so tests pass DEST explicitly.
const DEST = {bucket: 'us', prefix: 'alice/'};

/**
 * BESPOKE ON PURPOSE (SPEC-154 FR-007): the tree under test IS `UploadQueueProvider`, and
 * the shared harness has no way to nest a provider inside its own stack. The QueryClient is
 * the harness's factory, though — a bare `new QueryClient()` leaves retries ON, so a mocked
 * rejection waits for a backoff instead of failing the assertion.
 */
function wrapper() {
  const client = createTestQueryClient();
  return ({children}: {children: ReactNode}) =>
    createElement(QueryClientProvider, {client}, createElement(UploadQueueProvider, {children}));
}

function render() {
  return renderHook(() => useUploadQueue(), {wrapper: wrapper()});
}

function files(n: number): File[] {
  return Array.from({length: n}, (_, i) => new File(['x'], `f${i}.txt`, {type: 'text/plain'}));
}

const countBy = (items: UploadItem[], status: UploadItem['status']) => items.filter((i) => i.status === status).length;

describe('UploadQueueProvider concurrency gate (FR-001)', () => {
  it('runs at most UPLOAD_CONCURRENCY (3) uploads at once and starts the next as a slot frees', async () => {
    // uploadFile never resolves on its own — we hold the resolvers to control timing.
    const resolvers: ((v: {success: true; data: {key: string}}) => void)[] = [];
    mockUpload.mockImplementation(() => new Promise((res) => resolvers.push(res)));

    const {result} = render();
    act(() => result.current.enqueue(files(5), DEST));

    await waitFor(() => expect(countBy(result.current.items, 'uploading')).toBe(3));
    expect(countBy(result.current.items, 'queued')).toBe(2);
    expect(mockUpload).toHaveBeenCalledTimes(3);

    act(() => resolvers[0]({success: true, data: {key: 'alice/f0.txt'}}));
    await waitFor(() => expect(countBy(result.current.items, 'done')).toBe(1));
    expect(countBy(result.current.items, 'uploading')).toBe(3);
    expect(mockUpload).toHaveBeenCalledTimes(4);

    // Drain the rest. Each resolution frees a slot and launches the next queued
    // item, appending its resolver — so resolve sequentially as they appear.
    for (let i = 1; i < 5; i += 1) {
      await waitFor(() => expect(resolvers.length).toBeGreaterThan(i));
      act(() => resolvers[i]({success: true, data: {key: `alice/f${i}.txt`}}));
    }
    await waitFor(() => expect(countBy(result.current.items, 'done')).toBe(5));
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/');
  });

  it('uploads to the captured prefix + file name and routes a Collision to the collision state', async () => {
    mockUpload.mockResolvedValue({
      success: false,
      error: {message: 'exists', code: 'Collision'}
    });
    const {result} = render();
    act(() => result.current.enqueue(files(1), DEST));

    await waitFor(() => expect(result.current.items[0].status).toBe('collision'));
    expect(mockUpload).toHaveBeenCalledWith(
      expect.objectContaining({bucket: 'us', key: 'alice/f0.txt', overwrite: false})
    );

    // Overwrite re-queues with overwrite:true and re-runs.
    mockUpload.mockResolvedValue({success: true, data: {key: 'alice/f0.txt'}});
    act(() => result.current.resolveOverwrite(result.current.items[0].id));
    await waitFor(() => expect(result.current.items[0].status).toBe('done'));
    expect(mockUpload).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
  });

  it('rejects an oversize file on enqueue without ever calling uploadFile', async () => {
    const big = new File(['x'], 'huge.bin');
    Object.defineProperty(big, 'size', {value: maxUploadBytes() + 1});

    const {result} = render();
    act(() => result.current.enqueue([big], DEST));

    await waitFor(() => expect(result.current.items[0].status).toBe('failed'));
    expect(result.current.items[0].error).toMatch(/maximum upload size/i);
    expect(mockUpload).not.toHaveBeenCalled();
  });
});

describe('UploadQueueProvider cancel (FR-002)', () => {
  it('cancelling an in-flight upload aborts it and moves the item to cancelled', async () => {
    // Resolve to Cancelled the moment the signal aborts (mirrors uploadFile).
    mockUpload.mockImplementation(
      ({signal}) =>
        new Promise((resolve) => {
          signal?.addEventListener('abort', () =>
            resolve({
              success: false,
              error: {message: 'Upload cancelled.', code: 'Cancelled'}
            })
          );
        })
    );

    const {result} = render();
    act(() => result.current.enqueue(files(1), DEST));
    await waitFor(() => expect(result.current.items[0].status).toBe('uploading'));

    act(() => result.current.cancel(result.current.items[0].id));
    await waitFor(() => expect(result.current.items[0].status).toBe('cancelled'));
    expect(mockInvalidate).not.toHaveBeenCalled();
  });

  it('cancelling a still-queued item removes it without starting an upload', async () => {
    // First file occupies the only-needed slot but never resolves; with concurrency
    // 3 and 4 files, the 4th stays queued.
    mockUpload.mockImplementation(() => new Promise(() => {}));
    const {result} = render();
    act(() => result.current.enqueue(files(4), DEST));

    await waitFor(() => expect(countBy(result.current.items, 'queued')).toBe(1));
    const queued = result.current.items.find((i) => i.status === 'queued')!;
    act(() => result.current.cancel(queued.id));

    await waitFor(() => expect(result.current.items.some((i) => i.id === queued.id)).toBe(false));
    expect(mockUpload).toHaveBeenCalledTimes(3); // the queued one never started
  });

  it('dismiss removes a terminal item; clearFinished clears them all', async () => {
    mockUpload.mockResolvedValue({success: true, data: {key: 'alice/f0.txt'}});
    const {result} = render();
    act(() => result.current.enqueue(files(2), DEST));

    await waitFor(() => expect(countBy(result.current.items, 'done')).toBe(2));
    act(() => result.current.dismiss(result.current.items[0].id));
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    act(() => result.current.clearFinished());
    await waitFor(() => expect(result.current.items).toHaveLength(0));
  });
});

describe('a presigned URL is minted PER FILE, when that file starts (FR-008 AC2)', () => {
  /**
   * The transport, stubbed so the real `uploadFile` can run inside the real queue.
   *
   * Every request completes on the next microtask, which is what lets the concurrency gate free
   * a slot and start the next item without the test holding resolvers.
   */
  class ImmediateXhr {
    static opened: string[] = [];
    upload = {addEventListener: () => {}};
    private handlers = new Map<string, () => void>();
    status = 200;
    addEventListener(event: string, handler: () => void) {
      this.handlers.set(event, handler);
    }
    open(_method: string, url: string) {
      ImmediateXhr.opened.push(url);
    }
    setRequestHeader() {}
    send() {
      queueMicrotask(() => this.handlers.get('load')?.());
    }
    abort() {}
  }

  it('mints one URL per file, never one for the batch', async () => {
    // A BATCH mint ages while the queue drains: with three files in flight and a 15-minute
    // window, the fiftieth file's URL would be signed long before it was redeemed, fail
    // preflight-clean and 403 after its bytes were sent. So the mint has to sit inside the
    // upload, which is what this asserts through the real one.
    ImmediateXhr.opened = [];
    vi.stubGlobal('XMLHttpRequest', ImmediateXhr);
    const minted: string[] = [];
    vi.mocked(apiRequest).mockImplementation((async (route: string, options?: {body?: {key?: string}}) => {
      minted.push(`${route}:${options?.body?.key}`);
      return {success: true, data: {url: `https://signed/${options?.body?.key}`, expiresAt: 'later'}};
    }) as typeof apiRequest);
    // The REAL uploader, so the mint this asserts is the one production performs. Reached through
    // `importActual` because this file mocks the module it lives in — `service.uploadFile` would
    // be the stub calling itself.
    const {uploadFile: realUpload} =
      await vi.importActual<typeof import('./fileBrowser.service')>('./fileBrowser.service');
    mockUpload.mockImplementation(realUpload);

    const {result} = render();
    act(() => result.current.enqueue(files(5), DEST));

    await waitFor(() => expect(countBy(result.current.items, 'done')).toBe(5));
    expect(minted).toEqual([
      'objects.uploadUrl:alice/f0.txt',
      'objects.uploadUrl:alice/f1.txt',
      'objects.uploadUrl:alice/f2.txt',
      'objects.uploadUrl:alice/f3.txt',
      'objects.uploadUrl:alice/f4.txt'
    ]);
    // And each mint was redeemed by the file it was signed for.
    expect(ImmediateXhr.opened).toEqual(minted.map((entry) => `https://signed/${entry.split(':')[1]}`));

    vi.unstubAllGlobals();
  });

  it('starts at most UPLOAD_CONCURRENCY mints at a time, so no URL ages in a queue', async () => {
    // The other half of "per file": three in flight means three minted, not five.
    ImmediateXhr.opened = [];
    vi.stubGlobal('XMLHttpRequest', ImmediateXhr);
    let mints = 0;
    const held: (() => void)[] = [];
    vi.mocked(apiRequest).mockImplementation(
      () =>
        new Promise((resolve) => {
          mints += 1;
          held.push(() => resolve({success: true, data: {url: 'https://signed/x', expiresAt: 'later'}}));
        })
    );
    // The REAL uploader, so the mint this asserts is the one production performs. Reached through
    // `importActual` because this file mocks the module it lives in — `service.uploadFile` would
    // be the stub calling itself.
    const {uploadFile: realUpload} =
      await vi.importActual<typeof import('./fileBrowser.service')>('./fileBrowser.service');
    mockUpload.mockImplementation(realUpload);

    const {result} = render();
    act(() => result.current.enqueue(files(5), DEST));

    await waitFor(() => expect(mints).toBe(UPLOAD_CONCURRENCY));
    expect(countBy(result.current.items, 'queued')).toBe(5 - UPLOAD_CONCURRENCY);

    // Drained one at a time: each release frees a slot, which starts the next item and appends
    // ITS mint — so a single sweep of the array releases three and stops.
    for (let i = 0; i < 5; i += 1) {
      await waitFor(() => expect(held.length).toBeGreaterThan(i));
      await act(async () => held[i]());
    }
    await waitFor(() => expect(countBy(result.current.items, 'done')).toBe(5));
    expect(mints).toBe(5);

    vi.unstubAllGlobals();
  });
});
