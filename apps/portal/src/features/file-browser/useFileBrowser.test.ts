import {renderHook, waitFor, act} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {createElement, type ReactNode} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {useFileBrowser} from './useFileBrowser';
import {listFiles} from './fileBrowser.service';
import type {FileListPage} from '../../types/s3.types';

vi.mock('./fileBrowser.service');

const mockListFiles = vi.mocked(listFiles);

// Fresh client per render with retries off, so an errored query fails fast
// instead of waiting on the default retry/backoff.
function wrapper() {
  const client = new QueryClient({
    defaultOptions: {queries: {retry: false}}
  });
  return ({children}: {children: ReactNode}) => createElement(QueryClientProvider, {client}, children);
}

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

    const {result} = renderHook(() => useFileBrowser('my-bucket'), {
      wrapper: wrapper()
    });

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

    const {result} = renderHook(() => useFileBrowser('my-bucket'), {
      wrapper: wrapper()
    });

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

    const {result} = renderHook(() => useFileBrowser('my-bucket'), {
      wrapper: wrapper()
    });

    // The hook exposes the raw error object (SPEC-106 #7) so consumers map by code.
    await waitFor(() => expect(result.current.error).toEqual(expect.objectContaining({message: 'Access Denied'})));
    expect(result.current.files).toHaveLength(0);
    expect(result.current.folders).toHaveLength(0);
  });

  it('passes the prefix to listFiles', async () => {
    mockListFiles.mockResolvedValue({success: true, data: page()});

    const {result} = renderHook(() => useFileBrowser('my-bucket', 'docs/'), {
      wrapper: wrapper()
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockListFiles).toHaveBeenCalledWith('my-bucket', 'docs/', undefined);
  });

  it('hides the prefix marker from the listing by exact key (SPEC-014 FR-002)', async () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: page({
        files: [
          {
            type: 'file',
            key: 'alice/DO_NOT_DELETE.txt',
            name: 'DO_NOT_DELETE.txt',
            size: 100,
            lastModified: new Date('2024-01-01')
          },
          {
            type: 'file',
            key: 'alice/report.pdf',
            name: 'report.pdf',
            size: 1024,
            lastModified: new Date('2024-01-15')
          }
        ]
      })
    });

    const {result} = renderHook(() => useFileBrowser('my-bucket', 'alice/', 'alice/DO_NOT_DELETE.txt'), {
      wrapper: wrapper()
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.files.map((f) => f.key)).toEqual(['alice/report.pdf']);
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

    const {result} = renderHook(() => useFileBrowser('my-bucket', 'p/'), {
      wrapper: wrapper()
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasMore).toBe(true);
    expect(result.current.files.map((f) => f.name)).toEqual(['b.txt']);

    act(() => result.current.loadMore());

    await waitFor(() => expect(result.current.hasMore).toBe(false));
    // Merged across pages and globally re-sorted (a before b).
    expect(result.current.files.map((f) => f.name)).toEqual(['a.txt', 'b.txt']);
    expect(mockListFiles).toHaveBeenNthCalledWith(2, 'my-bucket', 'p/', 'T2');
  });
});
