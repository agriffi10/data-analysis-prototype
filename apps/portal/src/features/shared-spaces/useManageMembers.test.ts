import { describe, it, expect, vi, beforeEach, type MockedFunction } from 'vitest';
import { renderHook, act } from '@testing-library/react';

vi.mock('./sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn(),
}));

import { enqueueSharedSpaceRequest } from './sharedSpaces.service';
import { useManageMembers } from './useManageMembers';

const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<
  (...a: unknown[]) => Promise<unknown>
>;

beforeEach(() => {
  vi.clearAllMocks();
  mockEnqueue.mockResolvedValue({ success: true, data: { requestId: 'r1' } });
});

describe('useManageMembers (SPEC-053 FR-002/003)', () => {
  it('addMembers enqueues one add_members request with the members payload', async () => {
    const { result } = renderHook(() => useManageMembers('alice'));
    await act(async () => {
      await result.current.addMembers('salesdata', ['bob', 'cara']);
    });
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'add_members',
      actor: 'alice',
      space: 'salesdata',
      payload: { members: ['bob', 'cara'] },
    });
  });

  it('removeMembers enqueues one remove_members request', async () => {
    const { result } = renderHook(() => useManageMembers('alice'));
    await act(async () => {
      await result.current.removeMembers('salesdata', ['bob']);
    });
    expect(mockEnqueue).toHaveBeenCalledWith({
      action: 'remove_members',
      actor: 'alice',
      space: 'salesdata',
      payload: { members: ['bob'] },
    });
  });

  it('does not enqueue when not signed in or when the list is empty', async () => {
    const signedOut = renderHook(() => useManageMembers(null));
    const a = await signedOut.result.current.addMembers('s', ['bob']);
    expect(a.success).toBe(false);

    const signedIn = renderHook(() => useManageMembers('alice'));
    const b = await signedIn.result.current.addMembers('s', []);
    expect(b.success).toBe(false);
    expect(mockEnqueue).not.toHaveBeenCalled();
  });
});
