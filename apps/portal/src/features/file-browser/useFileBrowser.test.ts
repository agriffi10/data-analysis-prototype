import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useFileBrowser } from './useFileBrowser';
import { listFiles } from './fileBrowser.service';
import type { FileList } from '../../types/s3.types';

vi.mock('./fileBrowser.service');

const mockListFiles = vi.mocked(listFiles);

const mockFileList: FileList = {
  files: [
    {
      type: 'file',
      key: 'docs/report.pdf',
      name: 'report.pdf',
      size: 1024,
      lastModified: new Date('2024-01-15'),
    },
  ],
  folders: [
    {
      type: 'folder',
      prefix: 'docs/archive/',
      name: 'archive',
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useFileBrowser', () => {
  it('starts in loading state', () => {
    mockListFiles.mockResolvedValue({ success: true, data: mockFileList });

    const { result } = renderHook(() => useFileBrowser('my-bucket'));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.files).toHaveLength(0);
    expect(result.current.folders).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it('resolves to data on success', async () => {
    mockListFiles.mockResolvedValue({ success: true, data: mockFileList });

    const { result } = renderHook(() => useFileBrowser('my-bucket'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.files).toEqual(mockFileList.files);
    expect(result.current.folders).toEqual(mockFileList.folders);
    expect(result.current.error).toBeNull();
  });

  it('sets error string on failure and leaves files and folders empty', async () => {
    mockListFiles.mockResolvedValue({
      success: false,
      error: { message: 'Access Denied', code: 'AccessDenied' },
    });

    const { result } = renderHook(() => useFileBrowser('my-bucket'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBe('Access Denied');
    expect(result.current.files).toHaveLength(0);
    expect(result.current.folders).toHaveLength(0);
  });

  it('re-fetches when prefix changes', async () => {
    mockListFiles
      .mockResolvedValueOnce({ success: true, data: mockFileList })
      .mockResolvedValueOnce({ success: true, data: { files: [], folders: [] } });

    const { result, rerender } = renderHook(
      ({ prefix }: { prefix?: string }) => useFileBrowser('my-bucket', prefix),
      { initialProps: { prefix: 'docs/' } },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockListFiles).toHaveBeenCalledWith('my-bucket', 'docs/');
    expect(result.current.files).toHaveLength(1);

    rerender({ prefix: 'images/' });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockListFiles).toHaveBeenCalledWith('my-bucket', 'images/');
    expect(mockListFiles).toHaveBeenCalledTimes(2);
    expect(result.current.files).toHaveLength(0);
  });

  it('refresh() re-fetches without changing prefix', async () => {
    mockListFiles
      .mockResolvedValueOnce({ success: true, data: mockFileList })
      .mockResolvedValueOnce({ success: true, data: { files: [], folders: [] } });

    const { result } = renderHook(() => useFileBrowser('my-bucket', 'docs/'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(mockListFiles).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.refresh();
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(mockListFiles).toHaveBeenCalledTimes(2);
    expect(mockListFiles).toHaveBeenLastCalledWith('my-bucket', 'docs/');
  });

  it('isLoading becomes true again during a refresh', async () => {
    let resolveSecond!: (v: Awaited<ReturnType<typeof listFiles>>) => void;
    const secondFetch = new Promise<Awaited<ReturnType<typeof listFiles>>>(
      (res) => { resolveSecond = res; },
    );

    mockListFiles
      .mockResolvedValueOnce({ success: true, data: mockFileList })
      .mockReturnValueOnce(secondFetch);

    const { result } = renderHook(() => useFileBrowser('my-bucket'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => { result.current.refresh(); });

    expect(result.current.isLoading).toBe(true);

    act(() => {
      resolveSecond({ success: true, data: { files: [], folders: [] } });
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it('hides the prefix marker from the listing by exact key (SPEC-014 FR-002)', async () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: {
        files: [
          {
            type: 'file',
            key: 'alice/DO_NOT_DELETE.txt',
            name: 'DO_NOT_DELETE.txt',
            size: 100,
            lastModified: new Date('2024-01-01'),
          },
          {
            type: 'file',
            key: 'alice/report.pdf',
            name: 'report.pdf',
            size: 1024,
            lastModified: new Date('2024-01-15'),
          },
        ],
        folders: [],
      },
    });

    const { result } = renderHook(() =>
      useFileBrowser('my-bucket', 'alice/', 'alice/DO_NOT_DELETE.txt'),
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.files.map((f) => f.key)).toEqual(['alice/report.pdf']);
  });

  it('shows a like-named file in a subfolder (only the exact root key is hidden)', async () => {
    mockListFiles.mockResolvedValue({
      success: true,
      data: {
        files: [
          {
            type: 'file',
            key: 'alice/docs/DO_NOT_DELETE.txt',
            name: 'DO_NOT_DELETE.txt',
            size: 100,
            lastModified: new Date('2024-01-01'),
          },
        ],
        folders: [],
      },
    });

    const { result } = renderHook(() =>
      useFileBrowser('my-bucket', 'alice/docs/', 'alice/DO_NOT_DELETE.txt'),
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.files.map((f) => f.key)).toEqual([
      'alice/docs/DO_NOT_DELETE.txt',
    ]);
  });

  it('clears a previous error and restores data on successful re-fetch', async () => {
    mockListFiles
      .mockResolvedValueOnce({
        success: false,
        error: { message: 'Network error' },
      })
      .mockResolvedValueOnce({ success: true, data: mockFileList });

    const { result } = renderHook(() => useFileBrowser('my-bucket'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBe('Network error');

    act(() => { result.current.refresh(); });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.files).toEqual(mockFileList.files);
  });
});
