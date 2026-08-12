import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {isArchiveId, useArchive, useRestoreArchive} from './useArchive';
import {enqueueArchive, enqueueRestore} from './archive.service';

vi.mock('./archive.service', () => ({enqueueArchive: vi.fn(), enqueueRestore: vi.fn()}));

const SPACE = {kind: 'personal' as const, name: 'alice'};
const ITEMS = [{kind: 'folder' as const, key: 'alice/reports/'}];
const ARCHIVE_ID = '33333333-3333-4333-8333-333333333333';

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(enqueueArchive).mockResolvedValue({success: true, data: undefined});
  vi.mocked(enqueueRestore).mockResolvedValue({success: true, data: undefined});
});

describe('useArchive', () => {
  const setup = () => {
    const notify = vi.fn();
    const hook = renderHook(() => useArchive(SPACE, notify));
    return {notify, hook};
  };

  it('enqueues the whole selection and the space, then closes', async () => {
    const {notify, hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit());

    expect(enqueueArchive).toHaveBeenCalledWith(expect.objectContaining({space: SPACE, items: ITEMS}));
    expect(hook.result.current.items).toBeNull();
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({variant: 'success'}));
  });

  it('says the archive was STARTED, never that it finished', async () => {
    // The plane copies to Glacier, confirms every object and only then deletes the source. "Your
    // files are archived" here would be wrong for the minutes that takes and false for a run
    // that rolls back — and this is the one operation where the difference is the user's data.
    const {notify, hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit());

    const {message} = notify.mock.calls[0][0];
    expect(message).toMatch(/started/i);
    expect(message).toMatch(/notification/i);
    expect(message).not.toMatch(/\barchived\b/i);
  });

  it('mints a NEW request id per submit, so a retry is not swallowed by the queue', async () => {
    // The request id IS the FIFO MessageDeduplicationId and the only double-submit guard there
    // is. Reusing it across a failed attempt would make the retry a silent no-op.
    vi.mocked(enqueueArchive).mockResolvedValueOnce({success: false, error: {message: 'queue unavailable'}});
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit());
    await act(async () => hook.result.current.submit());

    const ids = vi.mocked(enqueueArchive).mock.calls.map(([req]) => req.requestId);
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it('keeps the dialog open with a user-safe error when the enqueue fails', async () => {
    vi.mocked(enqueueArchive).mockResolvedValue({success: false, error: {message: 'queue unavailable'}});
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    const ok = await act(async () => hook.result.current.submit());

    expect(ok).toBe(false);
    expect(hook.result.current.items).toEqual(ITEMS);
    expect(hook.result.current.error).toEqual(expect.any(String));
  });

  it('returns true only on success, which is what the caller clears the selection on', async () => {
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));

    await expect(act(async () => hook.result.current.submit())).resolves.toBe(true);
  });

  it('never submits twice from two clicks in one tick', async () => {
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => {
      await Promise.all([hook.result.current.submit(), hook.result.current.submit()]);
    });

    expect(enqueueArchive).toHaveBeenCalledTimes(1);
  });

  it('recovers from a throw rather than wedging the dialog busy forever', async () => {
    // The request is BUILT before the ServiceResult contract starts — crypto.randomUUID() and
    // the SHA-256 digest are both undefined outside a secure context. Without the catch, `busy`
    // stays true: the confirm reads "Archiving…", Cancel is disabled and Escape is swallowed.
    vi.mocked(enqueueArchive).mockRejectedValue(new Error('insecure context'));
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    const ok = await act(async () => hook.result.current.submit());

    expect(ok).toBe(false);
    expect(hook.result.current.busy).toBe(false);
    expect(hook.result.current.error).toEqual(expect.any(String));
  });

  it('does nothing at all without a resolved space', async () => {
    const hook = renderHook(() => useArchive(null, vi.fn()));
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit());

    expect(enqueueArchive).not.toHaveBeenCalled();
  });
});

describe('isArchiveId', () => {
  it('accepts a UUID v4 in either case, trimmed', () => {
    expect(isArchiveId(ARCHIVE_ID)).toBe(true);
    expect(isArchiveId(` ${ARCHIVE_ID.toUpperCase()} `)).toBe(true);
  });

  it('rejects what the control plane rejects, rather than a looser lookalike', () => {
    // A second, laxer rule in the browser reports a value valid that the plane then refuses —
    // which is the hours-late notification this check exists to prevent.
    expect(isArchiveId('')).toBe(false);
    expect(isArchiveId('not-a-uuid')).toBe(false);
    expect(isArchiveId('33333333333343338333333333333333')).toBe(false);
    // v1, not v4 — the version nibble is what the plane matches on.
    expect(isArchiveId('33333333-3333-1333-8333-333333333333')).toBe(false);
    // A traversal that would otherwise become a path segment in two buckets.
    expect(isArchiveId('../33333333-3333-4333-8333-333333333333')).toBe(false);
  });
});

describe('useRestoreArchive', () => {
  const setup = () => {
    const notify = vi.fn();
    const hook = renderHook(() => useRestoreArchive(SPACE, notify));
    return {notify, hook};
  };

  it('enqueues the pasted id and the ROUTE’s space, then closes', async () => {
    const {notify, hook} = setup();
    act(() => hook.result.current.openDialog());
    await act(async () => hook.result.current.submit(ARCHIVE_ID));

    expect(enqueueRestore).toHaveBeenCalledWith(expect.objectContaining({space: SPACE, archiveId: ARCHIVE_ID}));
    expect(hook.result.current.open).toBe(false);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({variant: 'success'}));
  });

  it('says the restore takes several hours, because nobody can infer that', async () => {
    const {notify, hook} = setup();
    act(() => hook.result.current.openDialog());
    await act(async () => hook.result.current.submit(ARCHIVE_ID));

    const {message} = notify.mock.calls[0][0];
    expect(message).toMatch(/hours/i);
    expect(message).toMatch(/notification/i);
  });

  it('sends the run id and the archive id as different values', async () => {
    const {hook} = setup();
    act(() => hook.result.current.openDialog());
    await act(async () => hook.result.current.submit(ARCHIVE_ID));

    const [req] = vi.mocked(enqueueRestore).mock.calls[0];
    expect(req.requestId).not.toBe(req.archiveId);
  });

  it('mints a new run id per submit, so a refused restore is re-submittable', async () => {
    vi.mocked(enqueueRestore).mockResolvedValueOnce({success: false, error: {message: 'queue unavailable'}});
    const {hook} = setup();
    act(() => hook.result.current.openDialog());
    await act(async () => hook.result.current.submit(ARCHIVE_ID));
    await act(async () => hook.result.current.submit(ARCHIVE_ID));

    const ids = vi.mocked(enqueueRestore).mock.calls.map(([req]) => req.requestId);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it('keeps the dialog open with the error when the enqueue fails', async () => {
    vi.mocked(enqueueRestore).mockResolvedValue({success: false, error: {message: 'queue unavailable'}});
    const {hook} = setup();
    act(() => hook.result.current.openDialog());
    const ok = await act(async () => hook.result.current.submit(ARCHIVE_ID));

    expect(ok).toBe(false);
    expect(hook.result.current.open).toBe(true);
    expect(hook.result.current.error).toEqual(expect.any(String));
  });

  it('never submits twice from two clicks in one tick', async () => {
    const {hook} = setup();
    act(() => hook.result.current.openDialog());
    await act(async () => {
      await Promise.all([hook.result.current.submit(ARCHIVE_ID), hook.result.current.submit(ARCHIVE_ID)]);
    });

    expect(enqueueRestore).toHaveBeenCalledTimes(1);
  });
});
