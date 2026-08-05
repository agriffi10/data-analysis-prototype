import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {useTableShare} from './useTableShare';

const mockEnqueue = vi.fn();
vi.mock('./tableShare.service', () => ({
  enqueueTableShare: (req: unknown) => mockEnqueue(req)
}));

const RECIPIENTS = [{kind: 'user' as const, name: 'bob'}];

describe('useTableShare', () => {
  beforeEach(() => {
    mockEnqueue.mockReset();
  });

  it('open targets a rail table; close clears it', () => {
    const {result} = renderHook(() => useTableShare(vi.fn()));
    act(() => result.current.open('alice', 'orders'));
    expect(result.current.target).toEqual({database: 'alice', table: 'orders'});
    act(() => result.current.close());
    expect(result.current.target).toBeNull();
  });

  it('submit enqueues the SPEC-089 request, closes, and emits the pending toast', async () => {
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
    const notify = vi.fn();
    const {result} = renderHook(() => useTableShare(notify));
    act(() => result.current.open('alice', 'orders'));

    await act(() => result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS}));

    expect(mockEnqueue).toHaveBeenCalledWith({
      source: {database: 'alice', table: 'orders'},
      tableName: 'orders_copy',
      recipients: RECIPIENTS
    });
    expect(result.current.target).toBeNull();
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({variant: 'success', message: expect.stringContaining('alice.orders')})
    );
  });

  it('an enqueue failure keeps the dialog open with a user-safe error (values intact)', async () => {
    // The raw service message is mapped through toUserMessage (SPEC-106) — the code
    // drives friendly wording and the raw text never reaches the surface.
    mockEnqueue.mockResolvedValue({success: false, error: {message: 'no credentials', code: 'NotAuthenticated'}});
    const notify = vi.fn();
    const {result} = renderHook(() => useTableShare(notify));
    act(() => result.current.open('alice', 'orders'));

    await act(() => result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS}));

    expect(result.current.target).toEqual({database: 'alice', table: 'orders'});
    expect(result.current.error).toBe('Sign in to continue.');
    expect(notify).not.toHaveBeenCalled();
  });

  it('ignores submit with no target', async () => {
    const {result} = renderHook(() => useTableShare(vi.fn()));
    await act(() => result.current.submit({tableName: 'x_tbl', recipients: RECIPIENTS}));
    expect(mockEnqueue).not.toHaveBeenCalled();
  });

  // SPEC-150 FR-003. Both calls are made inside ONE act block with no await between
  // them — a real double-click, where both land before React re-renders. Awaiting
  // the first would let `busy` commit and would pass against the old state guard,
  // which is exactly the bug: two clicks in one render both read `busy === false`.
  it('two submits in a single render enqueue exactly once', async () => {
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
    const {result} = renderHook(() => useTableShare(vi.fn()));
    act(() => result.current.open('alice', 'orders'));

    await act(async () => {
      const first = result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS});
      const second = result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS});
      await Promise.all([first, second]);
    });

    expect(mockEnqueue).toHaveBeenCalledTimes(1);
  });

  it('the dropped second call resolves quietly and leaves the hook usable', async () => {
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
    const {result} = renderHook(() => useTableShare(vi.fn()));
    act(() => result.current.open('alice', 'orders'));

    await act(async () => {
      await Promise.all([
        expect(result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS})).resolves.toBeUndefined(),
        expect(result.current.submit({tableName: 'orders_copy', recipients: RECIPIENTS})).resolves.toBeUndefined()
      ]);
    });
    expect(result.current.error).toBeNull();

    // The guard cleared, so a later legitimate share still goes through.
    act(() => result.current.open('alice', 'invoices'));
    await act(() => result.current.submit({tableName: 'invoices_copy', recipients: RECIPIENTS}));

    expect(mockEnqueue).toHaveBeenCalledTimes(2);
    expect(mockEnqueue).toHaveBeenLastCalledWith(expect.objectContaining({tableName: 'invoices_copy'}));
  });
});
