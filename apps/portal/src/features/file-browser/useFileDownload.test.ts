import {renderHook, act, waitFor} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useFileDownload} from './useFileDownload';
import {getDownloadUrl} from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import type {S3FileItem} from '../../types/s3.types';

vi.mock('./fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./fileBrowser.service')>()),
  getDownloadUrl: vi.fn()
}));
vi.mock('./fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));

const mockGetUrl = vi.mocked(getDownloadUrl);
const mockTrigger = vi.mocked(triggerBrowserDownload);

const file = (name = 'report.csv'): S3FileItem => ({
  type: 'file',
  key: `alice/${name}`,
  name,
  size: 10,
  lastModified: new Date(0)
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useFileDownload', () => {
  it('presigns the file and hands the URL to the browser', async () => {
    mockGetUrl.mockResolvedValue({
      success: true,
      data: {url: 'https://signed/report.csv', expiresAt: '2026-01-01T00:15:00Z'}
    });
    const {result} = renderHook(() => useFileDownload('my-bucket'));

    await act(async () => {
      await result.current.download(file());
    });

    expect(mockGetUrl).toHaveBeenCalledWith({bucket: 'my-bucket', key: 'alice/report.csv', fileName: 'report.csv'});
    expect(mockTrigger).toHaveBeenCalledWith('https://signed/report.csv');
    expect(result.current.error).toBeNull();
    expect(result.current.downloadingKey).toBeNull();
  });

  it('marks the in-flight key so one row can be disabled without disabling the rest', async () => {
    let release!: () => void;
    mockGetUrl.mockReturnValue(
      new Promise((resolve) => {
        release = () =>
          resolve({success: true, data: {url: 'https://signed/report.csv', expiresAt: '2026-01-01T00:15:00Z'}});
      })
    );
    const {result} = renderHook(() => useFileDownload('my-bucket'));

    act(() => void result.current.download(file()));
    await waitFor(() => expect(result.current.downloadingKey).toBe('alice/report.csv'));

    await act(async () => {
      release();
    });
    await waitFor(() => expect(result.current.downloadingKey).toBeNull());
  });

  it('ignores a second click on the SAME key while it is in flight', async () => {
    // SPEC-081 FR-002: a rapid double-click must not mint two presigned URLs.
    let release!: () => void;
    mockGetUrl.mockReturnValue(
      new Promise((resolve) => {
        release = () =>
          resolve({success: true, data: {url: 'https://signed/report.csv', expiresAt: '2026-01-01T00:15:00Z'}});
      })
    );
    const {result} = renderHook(() => useFileDownload('my-bucket'));

    act(() => void result.current.download(file()));
    await waitFor(() => expect(result.current.downloadingKey).toBe('alice/report.csv'));
    act(() => void result.current.download(file()));

    expect(mockGetUrl).toHaveBeenCalledTimes(1);
    await act(async () => {
      release();
    });
  });

  it('reports a failure in user-safe words, naming the file and never the raw AWS text', async () => {
    mockGetUrl.mockResolvedValue({success: false, error: {message: 'Access Denied', code: 'AccessDenied'}});
    const {result} = renderHook(() => useFileDownload('my-bucket'));

    await act(async () => {
      await result.current.download(file());
    });

    expect(result.current.error).toContain('Could not download report.csv.');
    expect(result.current.error).not.toContain('Access Denied');
    expect(mockTrigger).not.toHaveBeenCalled();
  });

  it('clears a previous failure when a new download starts, and on dismiss', async () => {
    mockGetUrl.mockResolvedValueOnce({success: false, error: {message: 'nope', code: 'AccessDenied'}});
    const {result} = renderHook(() => useFileDownload('my-bucket'));

    await act(async () => {
      await result.current.download(file());
    });
    expect(result.current.error).not.toBeNull();

    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();

    mockGetUrl.mockResolvedValueOnce({success: false, error: {message: 'nope', code: 'AccessDenied'}});
    await act(async () => {
      await result.current.download(file());
    });
    expect(result.current.error).not.toBeNull();

    mockGetUrl.mockResolvedValueOnce({
      success: true,
      data: {url: 'https://signed/other.csv', expiresAt: '2026-01-01T00:15:00Z'}
    });
    await act(async () => {
      await result.current.download(file('other.csv'));
    });
    expect(result.current.error).toBeNull();
  });
});
