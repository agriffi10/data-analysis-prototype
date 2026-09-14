import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, renderHook, waitFor} from '@testing-library/react';
import {useFileSend} from './useFileSend';
import {enqueueFileSend} from './fileSend.service';

vi.mock('./fileSend.service', () => ({enqueueFileSend: vi.fn()}));

describe('useFileSend', () => {
  const SPACE = {kind: 'personal' as const, name: 'alice'};
  const ITEMS = [{kind: 'folder' as const, key: 'alice/reports/'}];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(enqueueFileSend).mockResolvedValue({success: true, data: undefined});
  });

  const setup = () => {
    const notify = vi.fn();
    const hook = renderHook(() => useFileSend(SPACE, notify));
    return {notify, hook};
  };

  it('enqueues the selection, the space and the recipients, then closes', async () => {
    const {notify, hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    expect(enqueueFileSend).toHaveBeenCalledWith(
      expect.objectContaining({space: SPACE, items: ITEMS, recipients: [{kind: 'user', name: 'bob'}]})
    );
    expect(hook.result.current.items).toBeNull();
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({variant: 'success'}));
  });

  it('says the send was REQUESTED, never that it arrived', async () => {
    // The plane copies in the background and the outcome per recipient comes back as a
    // notification. "Sent" here would be a lie for the minutes a large send takes, and simply
    // wrong for one that conflicts.
    const {notify, hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    expect(notify).toHaveBeenCalledTimes(1);
    const {message} = notify.mock.calls[0][0];
    expect(message).toMatch(/requested/i);
    expect(message).toMatch(/notification/i);
    expect(message).not.toMatch(/\bsent\b/i);
  });

  it('mints a NEW request id per submit, so a retry is not swallowed by the queue', async () => {
    // The request id IS the FIFO MessageDeduplicationId and the only double-submit guard there
    // is. Reusing it across a failed attempt would make the retry a silent no-op: the user sees
    // an error, presses the button again, and nothing at all happens.
    vi.mocked(enqueueFileSend).mockResolvedValueOnce({
      success: false,
      error: {message: 'queue unavailable'}
    });
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    const [first, second] = vi.mocked(enqueueFileSend).mock.calls.map(([req]) => req.requestId);
    expect(first).not.toEqual(second);
  });

  it('keeps the dialog open with the error on a failure, and notifies nothing', async () => {
    vi.mocked(enqueueFileSend).mockResolvedValue({success: false, error: {message: 'queue unavailable'}});
    const {notify, hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    await waitFor(() => expect(hook.result.current.error).toBeTruthy());
    expect(hook.result.current.items).toEqual(ITEMS);
    expect(notify).not.toHaveBeenCalled();
  });

  it('never shows raw service text to the user', async () => {
    vi.mocked(enqueueFileSend).mockResolvedValue({
      success: false,
      error: {message: 'AccessDenied: User arn:aws:sts::1:assumed-role/x is not authorized'}
    });
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    await waitFor(() => expect(hook.result.current.error).toBeTruthy());
    expect(hook.result.current.error).not.toMatch(/arn:aws/);
  });

  it('ignores a second submit while one is in flight', async () => {
    // A ref, not `busy`: a second click in the same tick reads the state before React has
    // re-rendered, so a state read would lose the race and send twice.
    let release: (v: unknown) => void = () => {};
    vi.mocked(enqueueFileSend).mockImplementation(() => new Promise((resolve) => (release = resolve)) as never);
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    act(() => {
      void hook.result.current.submit([{kind: 'user', name: 'bob'}]);
      void hook.result.current.submit([{kind: 'user', name: 'bob'}]);
    });
    await act(async () => release({success: true, data: undefined}));

    expect(enqueueFileSend).toHaveBeenCalledTimes(1);
  });

  it('never wedges when the enqueue THROWS, and says something', async () => {
    // The request is BUILT before the ServiceResult contract starts, and `crypto.randomUUID()`
    // here is undefined outside a secure context, which is the documented dev-preview shape.
    // Leaving `busy` true there is unrecoverable: the submit reads "Sending…", Cancel is disabled,
    // the modal refuses to dismiss and swallows Escape, and `close()` refuses because it is busy.
    vi.mocked(enqueueFileSend).mockRejectedValue(new Error('crypto.randomUUID is not a function'));
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    expect(hook.result.current.error).toBeTruthy();
    expect(hook.result.current.items).toEqual(ITEMS);

    // And it can still be dismissed, which is the property that was actually broken.
    act(() => hook.result.current.close());
    expect(hook.result.current.items).toBeNull();
  });

  it('sends nothing when the space cannot be resolved', async () => {
    // The dev-unauth path and a space still loading: there is no source to send FROM.
    const notify = vi.fn();
    const hook = renderHook(() => useFileSend(null, notify));
    act(() => hook.result.current.open(ITEMS));
    await act(async () => hook.result.current.submit([{kind: 'user', name: 'bob'}]));

    expect(enqueueFileSend).not.toHaveBeenCalled();
  });

  it('refuses to close while busy, so a dismissal cannot orphan a request', async () => {
    vi.mocked(enqueueFileSend).mockImplementation(() => new Promise(() => {}) as never);
    const {hook} = setup();
    act(() => hook.result.current.open(ITEMS));
    act(() => void hook.result.current.submit([{kind: 'user', name: 'bob'}]));
    await waitFor(() => expect(hook.result.current.busy).toBe(true));

    act(() => hook.result.current.close());

    expect(hook.result.current.items).toEqual(ITEMS);
  });
});
