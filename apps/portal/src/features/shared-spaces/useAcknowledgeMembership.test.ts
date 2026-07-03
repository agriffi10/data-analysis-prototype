import {describe, it, expect, vi, beforeEach, type MockedFunction} from 'vitest';
import {renderHook} from '@testing-library/react';

vi.mock('./sharedSpaces.service', () => ({
  enqueueSharedSpaceRequest: vi.fn()
}));

import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import {useAcknowledgeMembership} from './useAcknowledgeMembership';
import type {Connection} from '../query/query.types';

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
