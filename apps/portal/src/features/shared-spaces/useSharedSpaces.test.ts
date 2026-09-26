import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {MockedFunction} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import {useAcknowledgeMembership} from './useAcknowledgeMembership';
import {useManageMembers} from './useManageMembers';
import type {Connection} from '../connections/connection.types';

// ─── from useAcknowledgeMembership.test.ts ───
vi.mock('./sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./sharedSpaces.service')>()),
  enqueueSharedSpaceRequest: vi.fn()
}));

describe('useAcknowledgeMembership', () => {
  const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<(...a: unknown[]) => Promise<unknown>>;

  const personal: Connection = {id: 'personal', label: 'alice', database: 'alice', kind: 'personal'};
  const memberActive: Connection = {
    id: 'sales',
    label: 'sales',
    database: 'sales',
    kind: 'shared',
    role: 'member',
    status: 'active'
  };

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('useAcknowledgeMembership (SPEC-073 FR-003)', () => {
    it('enqueues exactly one acknowledge_membership request for a member on an active shared space', () => {
      renderHook(() => useAcknowledgeMembership('bob', [personal, memberActive], 'sales'));
      expect(mockEnqueue).toHaveBeenCalledTimes(1);
      expect(mockEnqueue).toHaveBeenCalledWith({action: 'acknowledge_membership', actor: 'bob', space: 'sales'});
    });

    it('is deduped to once per session per space across re-renders', () => {
      const {rerender} = renderHook(() => useAcknowledgeMembership('bob', [personal, memberActive], 'sales'));
      rerender();
      rerender();
      expect(mockEnqueue).toHaveBeenCalledTimes(1);
    });

    it('acks once, and throws nothing, when session storage refuses every access', () => {
      const refuse = () => {
        throw new DOMException('The operation is insecure.', 'SecurityError');
      };
      vi.stubGlobal('sessionStorage', {getItem: refuse, setItem: refuse});
      const {rerender} = renderHook(({connections}) => useAcknowledgeMembership('bob', connections, 'sales'), {
        initialProps: {connections: [personal, memberActive]}
      });

      rerender({connections: [personal, {...memberActive}]});

      expect(mockEnqueue).toHaveBeenCalledTimes(1);
    });

    it('does not ack the personal space, the owner, a non-active space, or when signed out', () => {
      const owner: Connection = {...memberActive, role: 'owner'};
      const provisioning: Connection = {...memberActive, status: 'provisioning'};

      renderHook(() => useAcknowledgeMembership('bob', [personal], 'personal'));
      renderHook(() => useAcknowledgeMembership('alice', [personal, owner], 'sales'));
      renderHook(() => useAcknowledgeMembership('bob', [personal, provisioning], 'sales'));
      renderHook(() => useAcknowledgeMembership(null, [personal, memberActive], 'sales'));

      expect(mockEnqueue).not.toHaveBeenCalled();
    });
  });
});

// ─── from useManageMembers.test.ts ───

describe('useManageMembers', () => {
  const mockEnqueue = enqueueSharedSpaceRequest as unknown as MockedFunction<(...a: unknown[]) => Promise<unknown>>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockEnqueue.mockResolvedValue({success: true, data: {requestId: 'r1'}});
  });

  describe('useManageMembers (SPEC-053 FR-002/003)', () => {
    it('addMembers enqueues one add_members request with the members payload', async () => {
      const {result} = renderHook(() => useManageMembers('alice'));
      await act(async () => {
        await result.current.addMembers('salesdata', ['bob', 'cara']);
      });
      expect(mockEnqueue).toHaveBeenCalledWith({
        action: 'add_members',
        actor: 'alice',
        space: 'salesdata',
        payload: {members: ['bob', 'cara']}
      });
    });

    it('removeMembers enqueues one remove_members request', async () => {
      const {result} = renderHook(() => useManageMembers('alice'));
      await act(async () => {
        await result.current.removeMembers('salesdata', ['bob']);
      });
      expect(mockEnqueue).toHaveBeenCalledWith({
        action: 'remove_members',
        actor: 'alice',
        space: 'salesdata',
        payload: {members: ['bob']}
      });
    });

    it('does not enqueue when not signed in or when the list is empty', async () => {
      const signedOut = renderHook(() => useManageMembers(null));
      const a = await signedOut.result.current.addMembers('s', ['bob']);
      expect(a).toEqual({success: false, error: expect.objectContaining({code: 'NotAuthenticated'})});

      const signedIn = renderHook(() => useManageMembers('alice'));
      const b = await signedIn.result.current.addMembers('s', []);
      expect(b).toEqual({success: false, error: expect.objectContaining({code: 'InvalidRequest'})});
      expect(mockEnqueue).not.toHaveBeenCalled();
    });
  });
});
