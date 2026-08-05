import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {queryKeys} from '../query/queryKeys';
import {getS3Client} from '../../lib/s3Client';
import {useTableRefresh} from './useTableRefresh';
import type {GlueTableSummary} from '../query/query.types';

// Integration style: the real hook, the real QueryClient and the real auth
// context — only the AWS boundary (the enqueue service) is mocked.
const mockEnqueue = vi.fn();
vi.mock('./tableBuild.service', () => ({
  enqueueTableRefresh: (req: unknown) => mockEnqueue(req)
}));
vi.mock('../../lib/s3Client', () => ({getS3Client: vi.fn()}));

const TABLE: GlueTableSummary = {
  name: 'sales_2026',
  columns: [{name: 'region', type: 'string'}],
  location: 's3://dat-prod-user-space/alice/sales/2026'
};

const SHARED_TABLE: GlueTableSummary = {
  name: 'events',
  columns: [],
  location: 's3://dat-prod-shared-space/salesdata/events/'
};

function render(username = 'alice') {
  const notify = vi.fn();
  const rendered = renderHookWithProviders(() => useTableRefresh(notify), {auth: authenticated(username)});
  return {...rendered, notify};
}

/** The FR-005 entry point: a target the caller derived from the notification link. */
function renderLinked(pending = {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id']}) {
  const notify = vi.fn();
  const onConsumed = vi.fn();
  const target = {database: 'alice', table: TABLE, pending};
  const rendered = renderHookWithProviders(() => useTableRefresh(notify, {target, onConsumed}), {
    auth: authenticated('alice')
  });
  return {...rendered, notify, onConsumed, target};
}

describe('useTableRefresh', () => {
  beforeEach(() => {
    mockEnqueue.mockReset();
    mockEnqueue.mockResolvedValue({success: true, data: undefined});
  });

  it('open targets a rail table with no pending removal; close clears it', () => {
    const {result} = render();
    act(() => result.current.open('alice', TABLE));
    expect(result.current.target).toEqual({database: 'alice', table: TABLE, pending: null});
    act(() => result.current.close());
    expect(result.current.target).toBeNull();
  });

  it('open carries a link-borne pending removal', () => {
    const {result} = render();
    const pending = {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id']};
    act(() => result.current.open('alice', TABLE, pending));
    expect(result.current.target?.pending).toEqual(pending);
  });

  it('submits a personal-space request built from the table location', async () => {
    const {result, notify} = render();
    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(false));

    expect(mockEnqueue).toHaveBeenCalledWith({
      space: {
        kind: 'personal',
        bucket: 'dat-prod-user-space',
        prefix: 'alice/sales/2026/', // trailing slash normalised by the parser
        database: 'alice'
      },
      tableName: 'sales_2026'
    });
    expect(result.current.target).toBeNull();
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({variant: 'success', message: expect.stringContaining('alice.sales_2026')})
    );
  });

  it('marks a database that is not the signed-in user as a shared space', async () => {
    const {result} = render();
    act(() => result.current.open('salesdata', SHARED_TABLE));
    await act(() => result.current.submit(false));
    expect(mockEnqueue).toHaveBeenCalledWith(
      expect.objectContaining({
        space: {kind: 'shared', bucket: 'dat-prod-shared-space', prefix: 'salesdata/events/', database: 'salesdata'}
      })
    );
  });

  it('sends allowRemovals only when the opt-in was ticked', async () => {
    const {result} = render();
    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(true));
    expect(mockEnqueue.mock.calls[0][0]).toMatchObject({allowRemovals: true});

    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(false));
    expect(mockEnqueue.mock.calls[1][0]).not.toHaveProperty('allowRemovals');
  });

  it('keeps the dialog open with a user-safe error when the enqueue fails', async () => {
    // SPEC-106: the raw service text never reaches the surface.
    mockEnqueue.mockResolvedValue({success: false, error: {message: 'no credentials', code: 'NotAuthenticated'}});
    const {result, notify} = render();
    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(false));

    expect(result.current.target).toEqual({database: 'alice', table: TABLE, pending: null});
    expect(result.current.error).toBe('Sign in to continue.');
    expect(notify).not.toHaveBeenCalled();
  });

  it('refuses to build a request for a table with no location', async () => {
    const {result} = render();
    act(() => result.current.open('alice', {name: 'no_files', columns: []}));
    await act(() => result.current.submit(false));
    expect(mockEnqueue).not.toHaveBeenCalled();
    expect(result.current.error).toContain('no data folder');
  });

  it('ignores submit with no target', async () => {
    const {result} = render();
    await act(() => result.current.submit(false));
    expect(mockEnqueue).not.toHaveBeenCalled();
  });

  it('invalidates the rail once on submit and once on the next focus', async () => {
    const {result, queryClient} = render();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(false));

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({queryKey: queryKeys.schema('alice')});

    // The refresh lands while the user is elsewhere, so coming back re-reads once…
    await act(async () => void window.dispatchEvent(new Event('focus')));
    expect(invalidate).toHaveBeenCalledTimes(2);

    // …and only once: further focus events are not a reason to refetch.
    await act(async () => void window.dispatchEvent(new Event('focus')));
    await act(async () => void window.dispatchEvent(new Event('focus')));
    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it('does not invalidate on focus when no refresh was submitted', async () => {
    const {result, queryClient} = render();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    act(() => result.current.open('alice', TABLE));
    act(() => result.current.close());
    await act(async () => void window.dispatchEvent(new Event('focus')));
    expect(invalidate).not.toHaveBeenCalled();
  });

  describe('a link-borne target (FR-005)', () => {
    it('is the target without anything being opened', () => {
      const {result, target} = renderLinked();
      expect(result.current.target).toEqual(target);
    });

    it('retires the link on close — the parameters are what hold the dialog open', () => {
      const {result, onConsumed} = renderLinked();
      act(() => result.current.close());
      expect(onConsumed).toHaveBeenCalledTimes(1);
    });

    it('submits it and retires the link', async () => {
      const {result, onConsumed} = renderLinked();
      await act(() => result.current.submit(true));
      expect(mockEnqueue).toHaveBeenCalledWith(expect.objectContaining({tableName: 'sales_2026', allowRemovals: true}));
      expect(onConsumed).toHaveBeenCalledTimes(1);
    });

    it('keeps the link alive when the enqueue fails, so the dialog can be retried', async () => {
      mockEnqueue.mockResolvedValue({success: false, error: {message: 'nope'}});
      const {result, onConsumed} = renderLinked();
      await act(() => result.current.submit(true));
      expect(onConsumed).not.toHaveBeenCalled();
      expect(result.current.error).toBeTruthy();
    });

    it('is overridden by an explicitly opened table', () => {
      const {result} = renderLinked();
      const other = {name: 'other_table', columns: [], location: 's3://dat-prod-user-space/alice/other/'};
      act(() => result.current.open('alice', other));
      expect(result.current.target).toEqual({database: 'alice', table: other, pending: null});
    });
  });

  it('persists nothing — no localStorage write and no S3 call on any path', async () => {
    // FR-003: the opt-in is never remembered. `user_settings/` is reached through the
    // S3 client, so a feature that never obtains one cannot have written there.
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const {result} = render();
    act(() => result.current.open('alice', TABLE));
    await act(() => result.current.submit(true));
    expect(setItem).not.toHaveBeenCalled();
    expect(getS3Client).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
