import {describe, it, expect, vi, beforeEach} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';

// Integration style: exercise the real polling hook over a mocked Athena
// service boundary. `isTerminalState` stays real (importActual) so the
// refetch-stop logic runs exactly as in production.
vi.mock('./query.service', async (importActual) => {
  const actual = await importActual<typeof import('./query.service')>();
  return {...actual, getQueryStatus: vi.fn()};
});

import {getQueryStatus} from './query.service';
import {useQueryExecution} from './useQueryExecution';
import type {QueryStatus} from './query.types';

const mockGetStatus = vi.mocked(getQueryStatus);

const status = (over: Partial<QueryStatus> = {}): QueryStatus => ({
  queryExecutionId: 'q-1',
  state: 'SUCCEEDED',
  ...over
});
const ok = (data: QueryStatus) => ({success: true as const, data});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useQueryExecution', () => {
  it('is disabled and does not poll while the id is null', () => {
    const {result} = renderHookWithProviders(() => useQueryExecution(null));
    expect(result.current.fetchStatus).toBe('idle');
    expect(mockGetStatus).not.toHaveBeenCalled();
  });

  it('fetches the execution status for a non-null id and exposes the terminal state', async () => {
    mockGetStatus.mockResolvedValue(ok(status({state: 'SUCCEEDED'})));
    const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

    await waitFor(() => expect(result.current.data?.state).toBe('SUCCEEDED'));
    expect(mockGetStatus).toHaveBeenCalledWith('q-1');
  });

  it('surfaces a service failure as an error state (queryFn throws)', async () => {
    mockGetStatus.mockResolvedValue({success: false, error: {message: 'boom'}});
    const {result} = renderHookWithProviders(() => useQueryExecution('q-1'));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toEqual(expect.objectContaining({message: 'boom'}));
  });
});
