import {renderHook, waitFor, act} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {createElement, type ReactNode} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {useFileUpload} from './useFileUpload';
import {uploadFile, createFolder} from './fileBrowser.service';
import {invalidateListing} from '../../lib/queryClient';

vi.mock('./fileBrowser.service', () => ({
  uploadFile: vi.fn(),
  createFolder: vi.fn(),
  uploadPercent: (loaded: number, total: number) => (total > 0 ? Math.round((loaded / total) * 100) : 100)
}));
vi.mock('../../lib/queryClient', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

const mockUpload = vi.mocked(uploadFile);
const mockCreateFolder = vi.mocked(createFolder);
const mockInvalidate = vi.mocked(invalidateListing);

function wrapper() {
  const client = new QueryClient();
  return ({children}: {children: ReactNode}) => createElement(QueryClientProvider, {client}, children);
}

function render() {
  return renderHook(() => useFileUpload('us', 'alice/'), {wrapper: wrapper()});
}

const file = new File(['hello'], 'report.pdf', {type: 'application/pdf'});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useFileUpload', () => {
  it('uploads to currentPrefix + name and invalidates the listing on success', async () => {
    mockUpload.mockResolvedValue({success: true, data: {key: 'alice/report.pdf'}});

    const {result} = render();
    act(() => result.current.uploadOne(file));

    await waitFor(() => expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/'));
    expect(mockUpload).toHaveBeenCalledWith(
      expect.objectContaining({
        bucket: 'us',
        key: 'alice/report.pdf',
        contentType: 'application/pdf',
        overwrite: false
      })
    );
  });

  it('surfaces a collision and overwrites on confirm', async () => {
    mockUpload
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}})
      .mockResolvedValueOnce({success: true, data: {key: 'alice/report.pdf'}});

    const {result} = render();
    act(() => result.current.uploadOne(file));

    await waitFor(() => expect(result.current.pendingCollision).not.toBeNull());
    expect(result.current.pendingCollision?.kind).toBe('file');

    act(() => result.current.pendingCollision!.retry({overwrite: true}));

    await waitFor(() => expect(mockInvalidate).toHaveBeenCalled());
    expect(mockUpload).toHaveBeenCalledTimes(2);
    expect(mockUpload.mock.calls[1][0]).toMatchObject({overwrite: true});
    expect(result.current.pendingCollision).toBeNull();
  });

  it('renames on collision by re-running with the new key', async () => {
    mockUpload
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}})
      .mockResolvedValueOnce({success: true, data: {key: 'alice/renamed.pdf'}});

    const {result} = render();
    act(() => result.current.uploadOne(file));

    await waitFor(() => expect(result.current.pendingCollision).not.toBeNull());
    act(() => result.current.pendingCollision!.retry({rename: 'renamed.pdf'}));

    await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(2));
    expect(mockUpload.mock.calls[1][0]).toMatchObject({
      key: 'alice/renamed.pdf',
      overwrite: false
    });
  });

  it('creates a folder and invalidates on success', async () => {
    mockCreateFolder.mockResolvedValue({success: true, data: {prefix: 'alice/photos/'}});

    const {result} = render();
    act(() => result.current.createNewFolder('photos'));

    await waitFor(() => expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/'));
    expect(mockCreateFolder).toHaveBeenCalledWith({
      bucket: 'us',
      prefix: 'alice/',
      name: 'photos',
      overwrite: false
    });
  });

  it('a folder collision + rename re-runs createFolder with the new name', async () => {
    mockCreateFolder
      .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}})
      .mockResolvedValueOnce({success: true, data: {prefix: 'alice/pics/'}});

    const {result} = render();
    act(() => result.current.createNewFolder('photos'));

    await waitFor(() => expect(result.current.pendingCollision?.kind).toBe('folder'));
    act(() => result.current.pendingCollision!.retry({rename: 'pics'}));

    await waitFor(() => expect(mockCreateFolder).toHaveBeenCalledTimes(2));
    expect(mockCreateFolder.mock.calls[1][0]).toMatchObject({name: 'pics', overwrite: false});
  });

  it('surfaces a non-collision error and clears it on dismiss', async () => {
    mockUpload.mockResolvedValue({success: false, error: {message: 'Access Denied', code: 'AccessDenied'}});

    const {result} = render();
    act(() => result.current.uploadOne(file));

    // Mapped to friendly text (SPEC-106), not the raw 'Access Denied'.
    await waitFor(() =>
      expect(result.current.error).toBe("You don't have permission to do that. Contact the Administrator.")
    );
    expect(mockInvalidate).not.toHaveBeenCalled();

    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();
  });

  it('exposes a percentage while the upload is in flight', async () => {
    let resolveUpload!: (v: Awaited<ReturnType<typeof uploadFile>>) => void;
    mockUpload.mockImplementation((params) => {
      params.onProgress?.(50, 100);
      return new Promise((res) => {
        resolveUpload = res;
      });
    });

    const {result} = render();
    act(() => result.current.uploadOne(file));

    await waitFor(() => expect(result.current.progress).toBe(50));

    act(() => resolveUpload({success: true, data: {key: 'alice/report.pdf'}}));
    await waitFor(() => expect(result.current.progress).toBeNull());
  });
});
