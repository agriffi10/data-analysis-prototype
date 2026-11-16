import {waitFor, act} from '@testing-library/react';
import {createTestQueryClient, renderHookWithProviders} from '../../test/renderWithProviders';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useFileBrowser} from './useFileBrowser';
import {listFiles} from './fileBrowser.service';
import type {FileListPage} from '../../types/s3.types';

vi.mock('./fileBrowser.service');

const mockListFiles = vi.mocked(listFiles);

function page(over: Partial<FileListPage> = {}): FileListPage {
  return {files: [], folders: [], isTruncated: false, ...over};
}

const sampleFile = {
  type: 'file' as const,
  key: 'docs/report.pdf',
  name: 'report.pdf',
  size: 1024,
  lastModified: new Date('2024-01-15')
};
const sampleFolder = {
  type: 'folder' as const,
  prefix: 'docs/archive/',
  name: 'archive'
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useFileBrowser', () => {
  it('starts in loading state', () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: page({files: [sampleFile], folders: [sampleFolder]})
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.files).toHaveLength(0);
    expect(result.current.folders).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it('resolves to data on success', async () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: page({files: [sampleFile], folders: [sampleFolder]})
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.files).toEqual([sampleFile]);
    expect(result.current.folders).toEqual([sampleFolder]);
    expect(result.current.error).toBeNull();
    expect(result.current.hasMore).toBe(false);
  });

  it('exposes the error on failure and leaves files and folders empty', async () => {
    mockListFiles.mockResolvedValue({
      success: false,
      error: {message: 'Access Denied', code: 'AccessDenied'}
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket'));

    // The hook exposes the raw error object (SPEC-106 #7) so consumers map by code.
    await waitFor(() => expect(result.current.error).toEqual(expect.objectContaining({message: 'Access Denied'})));
    expect(result.current.files).toHaveLength(0);
    expect(result.current.folders).toHaveLength(0);
  });

  it('passes the prefix to listFiles', async () => {
    mockListFiles.mockResolvedValue({success: true, data: page()});

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'docs/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockListFiles).toHaveBeenCalledWith('my-bucket', 'docs/', undefined, expect.any(AbortSignal));
  });

  it('hides EVERY prefix marker, at any depth, with nothing passed in (SPEC-173 FR-003)', async () => {
    // The rule is the BASENAME, because that is what the portal role's policy for
    // each bucket denies deletion on. Showing one at `saved_queries/` would offer
    // an action this application's own IAM refuses.
    const file = (key: string) => ({
      type: 'file' as const,
      key,
      name: key.slice(key.lastIndexOf('/') + 1),
      size: 100,
      lastModified: new Date('2024-01-01')
    });
    mockListFiles.mockResolvedValue({
      success: true,
      data: page({
        files: [
          file('alice/DO_NOT_DELETE.txt'),
          file('alice/saved_queries/DO_NOT_DELETE.txt'),
          // Exact and case-sensitive, as S3 keys are — these two are ordinary files.
          file('alice/DO_NOT_DELETE.txt.bak'),
          file('alice/notes/do_not_delete.txt'),
          file('alice/report.pdf')
        ]
      })
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'alice/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    // Merged pages are re-sorted by NAME, which is why `do_not_delete.txt` leads.
    expect(result.current.files.map((f) => f.key)).toEqual([
      'alice/notes/do_not_delete.txt',
      'alice/DO_NOT_DELETE.txt.bak',
      'alice/report.pdf'
    ]);
  });

  it('hides a shared space\u2019s marker too, since the deny covers both buckets', async () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: page({
        files: [
          {
            type: 'file',
            key: 'project_alpha/saved_queries/DO_NOT_DELETE.txt',
            name: 'DO_NOT_DELETE.txt',
            size: 1,
            lastModified: new Date('2024-01-01')
          }
        ]
      })
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('shared-bucket', 'project_alpha/saved_queries/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.files).toEqual([]);
  });

  it('exposes hasMore and merges a second page on loadMore (SPEC-015 FR-002)', async () => {
    const fileA = {...sampleFile, key: 'a.txt', name: 'a.txt'};
    const fileB = {...sampleFile, key: 'b.txt', name: 'b.txt'};
    mockListFiles
      .mockResolvedValueOnce({
        success: true,
        data: page({files: [fileB], isTruncated: true, nextContinuationToken: 'T2'})
      })
      .mockResolvedValueOnce({
        success: true,
        data: page({files: [fileA], isTruncated: false})
      });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'p/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasMore).toBe(true);
    expect(result.current.files.map((f) => f.name)).toEqual(['b.txt']);

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.hasMore).toBe(false));
    // Merged across pages and globally re-sorted (a before b).
    expect(result.current.files.map((f) => f.name)).toEqual(['a.txt', 'b.txt']);
    expect(mockListFiles).toHaveBeenNthCalledWith(2, 'my-bucket', 'p/', 'T2', expect.any(AbortSignal));
  });

  it('exposes one server page at a time, fetching only past the last loaded one', async () => {
    const fileA = {...sampleFile, key: 'a.txt', name: 'a.txt'};
    const fileB = {...sampleFile, key: 'b.txt', name: 'b.txt'};
    mockListFiles
      .mockResolvedValueOnce({
        success: true,
        data: page({files: [fileB], isTruncated: true, nextContinuationToken: 'T2'})
      })
      .mockResolvedValueOnce({success: true, data: page({files: [fileA], isTruncated: false})});

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'p/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.page).toMatchObject({index: 0, count: 1, hasMoreServer: true, hasPrev: false, hasNext: true});
    expect(result.current.page.files.map((f) => f.name)).toEqual(['b.txt']);

    await act(() => result.current.page.goNext());

    await waitFor(() => expect(result.current.page.index).toBe(1));
    // The page as the server returned it — not a slice of the merged, re-sorted listing.
    expect(result.current.page.files.map((f) => f.name)).toEqual(['a.txt']);
    expect(result.current.page).toMatchObject({count: 2, hasMoreServer: false, hasPrev: true, hasNext: false});

    act(() => result.current.page.goPrev());

    await waitFor(() => expect(result.current.page.index).toBe(0));
    expect(result.current.page.files.map((f) => f.name)).toEqual(['b.txt']);
    expect(mockListFiles).toHaveBeenCalledTimes(2);
  });

  it('starts every listing at its first page, even one whose later pages are still cached', async () => {
    // The app's client keeps pages for minutes, so coming back to a folder finds its second
    // page still there. The position is filed per listing precisely so that the return lands
    // on page 1 rather than wherever the OTHER folder was left. The harness's zero cache time
    // would drop the second page and let the clamp hide a missing reset, hence a client that
    // keeps it.
    const client = createTestQueryClient();
    client.setDefaultOptions({queries: {retry: false, staleTime: 0, gcTime: Infinity}});
    const named = (name: string) => ({...sampleFile, key: name, name});
    mockListFiles.mockImplementation(async (_bucket, prefix, token) => {
      if (prefix === 'p/') return {success: true, data: page({files: [named('p1.csv')]})};
      return token === undefined
        ? {success: true, data: page({files: [named('q1.csv')], isTruncated: true, nextContinuationToken: 'T2'})}
        : {success: true, data: page({files: [named('q2.csv')]})};
    });

    const {result, rerender} = renderHookWithProviders(
      ({prefix}: {prefix: string}) => useFileBrowser('my-bucket', prefix),
      {
        queryClient: client,
        initialProps: {prefix: 'q/'}
      }
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(() => result.current.page.goNext());
    await waitFor(() => expect(result.current.page.index).toBe(1));

    rerender({prefix: 'p/'});
    await waitFor(() => expect(result.current.page.files.map((f) => f.name)).toEqual(['p1.csv']));
    expect(result.current.page.index).toBe(0);

    rerender({prefix: 'q/'});
    await waitFor(() => expect(result.current.page.count).toBe(2));
    expect(result.current.page.index).toBe(0);
    expect(result.current.page.files.map((f) => f.name)).toEqual(['q1.csv']);
  });

  it('does not throw the user forward when Prev was pressed while Next was still fetching', async () => {
    const named = (name: string) => ({...sampleFile, key: name, name});
    let deliverThird: (() => void) | undefined;
    mockListFiles.mockImplementation(async (_bucket, _prefix, after) => {
      if (after === undefined)
        return {success: true, data: page({files: [named('1.csv')], isTruncated: true, nextContinuationToken: 'T2'})};
      if (after === 'T2')
        return {success: true, data: page({files: [named('2.csv')], isTruncated: true, nextContinuationToken: 'T3'})};
      await new Promise<void>((resolve) => (deliverThird = resolve));
      return {success: true, data: page({files: [named('3.csv')]})};
    });

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'p/'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(() => result.current.page.goNext());
    await waitFor(() => expect(result.current.page.index).toBe(1));

    // Next on page 2 starts the fetch; Prev lands on page 1 before it resolves.
    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.page.goNext();
    });
    await waitFor(() => expect(deliverThird).toBeDefined());
    act(() => result.current.page.goPrev());
    await waitFor(() => expect(result.current.page.index).toBe(0));

    await act(async () => {
      deliverThird?.();
      await pending;
    });
    await waitFor(() => expect(result.current.page.count).toBe(3));
    expect(result.current.page.index).toBe(0);
  });

  it('stays on its page when the next one fails to arrive', async () => {
    const fileB = {...sampleFile, key: 'b.txt', name: 'b.txt'};
    mockListFiles
      .mockResolvedValueOnce({
        success: true,
        data: page({files: [fileB], isTruncated: true, nextContinuationToken: 'T2'})
      })
      .mockResolvedValue({success: false, error: {message: 'listing failed'}});

    const {result} = renderHookWithProviders(() => useFileBrowser('my-bucket', 'p/'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() => result.current.page.goNext());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    // Advancing onto a page that never came would show a blank page for a folder with rows.
    expect(result.current.page.index).toBe(0);
    expect(result.current.page.files.map((f) => f.name)).toEqual(['b.txt']);
  });
});
