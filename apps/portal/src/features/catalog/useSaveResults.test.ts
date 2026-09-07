import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {useSaveResults} from './useSaveResults';
import {copyObject, objectExists} from '../file-browser/fileBrowser.service';
import {enqueueResultsConversion} from './resultsConversion.service';
import type {QuerySpace} from './catalog.types';

// Only the service boundary is mocked (react.md §21). A hook test rather than a component one
// because what is under test is the ROUTING and the probe's four outcomes — state the dialog
// above it cannot distinguish, since three of the four look identical on screen.
vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  objectExists: vi.fn(),
  copyObject: vi.fn()
}));
vi.mock('./resultsConversion.service', () => ({enqueueResultsConversion: vi.fn()}));
// `spaceFor` decides `kind` by comparing the bucket against the configured shared one, so the
// fixture buckets have to be the configured names or a shared destination reads as personal —
// which is the exact confusion the first test is here to catch.
vi.mock('../../lib/userSpace', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/userSpace')>()),
  userSpaceBucket: () => 'user-space',
  sharedSpaceBucket: () => 'shared-space'
}));

const SHARED: QuerySpace = {
  id: 'salesdata',
  label: 'salesdata',
  bucket: 'shared-space',
  rootPrefix: 'salesdata/',
  rootLabel: 'salesdata'
};
const PERSONAL: QuerySpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  rootLabel: 'My Files'
};

const pushed: {variant?: string; message: string}[] = [];

function renderSave() {
  return renderHookWithProviders(() =>
    useSaveResults({
      spaces: [PERSONAL, SHARED],
      username: 'alice',
      outputLocation: 's3://user-space/alice/athenaresults/exec-1.csv',
      executionId: 'exec-1',
      linkedSavedName: undefined,
      toast: {push: (t) => pushed.push(t), dismiss: () => {}}
    })
  );
}

/** Save into the SHARED space, whose root differs from the actor's — see the first test. */
const saveParquet = {
  destBucket: 'shared-space',
  destPrefix: 'salesdata/reports/',
  filename: 'q1.parquet',
  format: 'parquet' as const
};

beforeEach(() => {
  vi.clearAllMocks();
  pushed.length = 0;
  vi.mocked(enqueueResultsConversion).mockResolvedValue({success: true, data: {requestId: 'r1'}});
});

describe('useSaveResults, the conversion path (SPEC-223 FR-002, FR-003)', () => {
  it('enqueues with a ROOT-RELATIVE prefix into a shared space, and invalidates nothing', async () => {
    // The assertion this file exists for. The plane builds `{root}{prefix}{filename}`, so a
    // full in-space prefix would write `salesdata/salesdata/reports/q1.parquet` — and nothing
    // refuses it, because the containment check only proves the key starts with the root.
    // A shared destination is used deliberately: read and write coincide for a personal one,
    // so a personal-only fixture cannot tell a root-relative prefix from an absolute one.
    vi.mocked(objectExists).mockResolvedValue({success: true, data: false});
    const {result, queryClient} = renderSave();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    act(() => result.current.save(saveParquet));

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalled());
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({
      queryExecutionId: 'exec-1',
      format: 'parquet',
      destination: {space: {kind: 'shared', name: 'salesdata'}, prefix: 'reports/', filename: 'q1.parquet'},
      onConflict: 'refuse'
    });
    await waitFor(() => expect(result.current.open).toBe(false));
    expect(pushed).toEqual([
      {variant: 'success', message: 'Converting to Parquet — you’ll get a notification when q1.parquet is ready.'}
    ]);
    // Nothing has been written yet, so nothing is invalidated — the plane has only been asked.
    // The CSV path's own invalidation is the positive control that this spy would see one.
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('mints a fresh request id per submit, so the double-submit guard is not a collision', async () => {
    // Hoisting the id to a module constant turns the guard into its opposite and every other
    // assertion in this file still passes, because they all read the body with `toMatchObject`.
    vi.mocked(objectExists).mockResolvedValue({success: true, data: false});
    const {result} = renderSave();

    act(() => result.current.save(saveParquet));
    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(1));
    act(() => result.current.save(saveParquet));
    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalledTimes(2));

    const [first, second] = vi.mocked(enqueueResultsConversion).mock.calls.map(([req]) => req.requestId);
    expect(first).toEqual(expect.any(String));
    expect(first).not.toBe(second);
  });

  it('DOES invalidate on the CSV path, which is what makes the assertion above mean something', async () => {
    vi.mocked(copyObject).mockResolvedValue({success: true, data: {destKey: 'salesdata/reports/q1.csv'}});
    const {result, queryClient} = renderSave();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

    act(() => result.current.save({...saveParquet, filename: 'q1.csv', format: 'csv'}));

    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    expect(objectExists).not.toHaveBeenCalled();
  });

  it('asks before overwriting an occupied name, then re-submits with onConflict overwrite', async () => {
    vi.mocked(objectExists).mockResolvedValue({success: true, data: true});
    const {result} = renderSave();

    act(() => result.current.save(saveParquet));

    await waitFor(() => expect(result.current.overwritePrompt?.filename).toBe('q1.parquet'));
    expect(objectExists).toHaveBeenCalledWith({bucket: 'shared-space', key: 'salesdata/reports/q1.parquet'});
    expect(enqueueResultsConversion).not.toHaveBeenCalled();

    act(() => result.current.confirmOverwrite());

    await waitFor(() => expect(enqueueResultsConversion).toHaveBeenCalled());
    expect(vi.mocked(enqueueResultsConversion).mock.calls[0][0]).toMatchObject({
      onConflict: 'overwrite',
      destination: {prefix: 'reports/', filename: 'q1.parquet'}
    });
  });

  it('treats a 403 from the probe as occupied — the space may hold a file the actor cannot see', async () => {
    // A DIFFERENT FIXTURE reaching the same outcome as the test above, which is why it is its
    // own scenario: a probe answering `true` and a probe refusing are distinct branches, and a
    // test that only exercised one would pass with the other deleted.
    vi.mocked(objectExists).mockResolvedValue({success: false, error: {message: '', code: 'AccessDenied'}});
    const {result} = renderSave();

    act(() => result.current.save(saveParquet));

    await waitFor(() => expect(result.current.overwritePrompt?.filename).toBe('q1.parquet'));
    expect(enqueueResultsConversion).not.toHaveBeenCalled();
    expect(pushed).toEqual([]);
  });

  it('renders the mapped sentence for a refused enqueue, never the route’s own text', async () => {
    // The sentinel is the point: `InvalidRequest` maps to an authored sentence, so any part of
    // the route's raw body reaching a toast would be raw API text on screen — which the browser
    // fence forbids outright.
    const SENTINEL = 'ZZ_RAW_ROUTE_TEXT_ZZ';
    vi.mocked(objectExists).mockResolvedValue({success: true, data: false});
    vi.mocked(enqueueResultsConversion).mockResolvedValue({
      success: false,
      error: {message: SENTINEL, code: 'InvalidRequest'}
    });
    const {result} = renderSave();
    act(() => result.current.openDialog());

    act(() => result.current.save(saveParquet));

    await waitFor(() => expect(pushed).toHaveLength(1));
    // POSITIVE CONTROL: the mapped sentence is present. Without it the absence below passes on
    // a toast that said nothing at all.
    expect(pushed[0].message).toContain('Something went wrong');
    expect(pushed[0].message).not.toContain(SENTINEL);
    expect(pushed[0].variant).toBe('danger');
    // The dialog stays open so the name or folder can be changed and tried again.
    expect(result.current.open).toBe(true);
  });

  it('submits nothing and keeps the dialog open when the probe fails for any other reason', async () => {
    vi.mocked(objectExists).mockResolvedValue({success: false, error: {message: '', code: 'InternalError'}});
    const {result} = renderSave();
    act(() => result.current.openDialog());

    act(() => result.current.save(saveParquet));

    await waitFor(() => expect(pushed).toHaveLength(1));
    expect(pushed[0].variant).toBe('danger');
    expect(enqueueResultsConversion).not.toHaveBeenCalled();
    expect(result.current.overwritePrompt).toBeNull();
    // The dialog stays open, so the user can change the name or the folder and try again.
    expect(result.current.open).toBe(true);
  });
});
