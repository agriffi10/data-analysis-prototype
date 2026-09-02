import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {useDataQualityCheck} from './useDataQualityCheck';
import type {DataQualitySpace} from './dataQuality.types';
import type {ServiceResult} from '../../types/service.types';
import * as service from './dataQuality.service';

vi.mock('./dataQuality.service', () => ({
  enqueueQualityCheck: vi.fn().mockResolvedValue({success: true, data: {requestId: 'req-1'}})
}));

describe('useDataQualityCheck', () => {
  const mock = vi.mocked(service);
  const space: DataQualitySpace = {kind: 'personal', bucket: 'user-space', prefix: 'alice/'};

  type EnqueueResult = ServiceResult<{requestId: string}>;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // The dialog test covers everything a user can drive. This file exists for the ONE
  // behaviour a component test structurally cannot reach: two `start` calls landing
  // before the first resolves. The dialog's confirm button is disabled by then, and
  // userEvent refuses to click a disabled button — so a component test passes with the
  // re-entry guard deleted, which is exactly the false green this covers.
  describe('useDataQualityCheck — the re-entry guard', () => {
    it('enqueues once when start is called twice before the first resolves', async () => {
      let release: (v: EnqueueResult) => void = () => {};
      mock.enqueueQualityCheck.mockReturnValue(
        new Promise<EnqueueResult>((resolve) => {
          release = resolve;
        })
      );

      const {result} = renderHookWithProviders(() => useDataQualityCheck());

      await act(async () => {
        // Deliberately un-awaited: both calls are in flight at once. `isPending` state
        // has not re-rendered yet, which is why a state-based guard would not hold here.
        void result.current.start({space, location: 'alice/sales/'});
        void result.current.start({space, location: 'alice/sales/'});
      });

      expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(1);

      await act(async () => {
        release({success: true, data: {requestId: 'req-1'}});
      });
    });

    it('releases the guard after a request settles, so a later check still runs', async () => {
      mock.enqueueQualityCheck.mockResolvedValue({success: true, data: {requestId: 'req-1'}});
      const {result} = renderHookWithProviders(() => useDataQualityCheck());

      await act(async () => {
        await result.current.start({space, location: 'alice/sales/'});
      });
      await act(async () => {
        await result.current.start({space, location: 'alice/other/'});
      });

      expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(2);
      await waitFor(() => expect(result.current.isPending).toBe(false));
    });

    it('releases the guard even when the enqueue rejects outright', async () => {
      // A thrown error, not a failed ServiceResult — services shouldn't throw, but a
      // guard that leaks on the one path nobody expects would wedge the button forever.
      mock.enqueueQualityCheck.mockRejectedValueOnce(new Error('boom'));
      const {result} = renderHookWithProviders(() => useDataQualityCheck());

      await act(async () => {
        await result.current.start({space, location: 'alice/sales/'}).catch(() => {});
      });
      expect(result.current.isPending).toBe(false);

      mock.enqueueQualityCheck.mockResolvedValue({success: true, data: {requestId: 'req-2'}});
      await act(async () => {
        await result.current.start({space, location: 'alice/sales/'});
      });
      expect(mock.enqueueQualityCheck).toHaveBeenCalledTimes(2);
    });
  });
});
