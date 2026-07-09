import {renderHook, act} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {createElement, type ReactNode} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {useDelete, type DeleteSummary} from './useDelete';
import {deleteObjects, deleteFolder} from './fileBrowser.service';
import {invalidateListing} from '../../lib/queryClient';
import type {SelectableItem} from './selectionContext';

vi.mock('./fileBrowser.service', () => ({
  deleteObjects: vi.fn(),
  deleteFolder: vi.fn()
}));
vi.mock('../../lib/queryClient', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

const mockDeleteObjects = vi.mocked(deleteObjects);
const mockDeleteFolder = vi.mocked(deleteFolder);
const mockInvalidate = vi.mocked(invalidateListing);

function wrapper() {
  const client = new QueryClient();
  return ({children}: {children: ReactNode}) => createElement(QueryClientProvider, {client}, children);
}

function render(username: string | undefined = 'alice') {
  return renderHook(() => useDelete('us', 'alice/', username), {
    wrapper: wrapper()
  });
}

const file = (key: string): SelectableItem => ({type: 'file', key});
const folder = (prefix: string): SelectableItem => ({type: 'folder', prefix});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useDelete', () => {
  it('batches loose files and recursively deletes folders, aggregating counts', async () => {
    mockDeleteObjects.mockResolvedValue({
      success: true,
      data: {deleted: ['alice/a.txt', 'alice/b.txt'], errors: []}
    });
    mockDeleteFolder.mockResolvedValue({
      success: true,
      data: {deleted: ['alice/p/', 'alice/p/x.jpg'], errors: []}
    });

    const {result} = render();
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([file('alice/a.txt'), file('alice/b.txt'), folder('alice/p/')]);
    });

    expect(mockDeleteObjects).toHaveBeenCalledWith({
      bucket: 'us',
      keys: ['alice/a.txt', 'alice/b.txt'],
      username: 'alice'
    });
    expect(mockDeleteFolder).toHaveBeenCalledWith({
      bucket: 'us',
      prefix: 'alice/p/',
      username: 'alice'
    });
    expect(summary).toEqual({deletedCount: 4, errors: []});
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/');
  });

  it('does nothing and surfaces an error when there is no username', async () => {
    // Pass undefined directly — render()'s default would otherwise mask it.
    const {result} = renderHook(() => useDelete('us', 'alice/', undefined), {
      wrapper: wrapper()
    });
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([file('alice/a.txt')]);
    });

    expect(summary).toBeNull();
    expect(mockDeleteObjects).not.toHaveBeenCalled();
    expect(result.current.error).toMatch(/signed in/i);
  });

  it('returns null and makes no calls for an empty selection', async () => {
    const {result} = render();
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([]);
    });

    expect(summary).toBeNull();
    expect(mockDeleteObjects).not.toHaveBeenCalled();
    expect(mockDeleteFolder).not.toHaveBeenCalled();
  });

  it('aborts on a systemic files failure — no folder deletes, no invalidation', async () => {
    mockDeleteObjects.mockResolvedValue({
      success: false,
      error: {message: 'No AWS credentials — sign in required', code: 'NotAuthenticated'}
    });

    const {result} = render();
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([file('alice/a.txt'), folder('alice/p/')]);
    });

    expect(summary).toBeNull();
    expect(mockDeleteFolder).not.toHaveBeenCalled();
    expect(mockInvalidate).not.toHaveBeenCalled();
    // Mapped to friendly text (SPEC-106), not the raw credential message.
    expect(result.current.error).toBe('Sign in to continue.');
  });

  it('records a folder failure and continues with the remaining folders', async () => {
    mockDeleteFolder
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'Access Denied', code: 'AccessDenied'}
      })
      .mockResolvedValueOnce({
        success: true,
        data: {deleted: ['alice/q/'], errors: []}
      });

    const {result} = render();
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([folder('alice/p/'), folder('alice/q/')]);
    });

    expect(mockDeleteFolder).toHaveBeenCalledTimes(2);
    expect(summary).toEqual({
      deletedCount: 1,
      errors: [{key: 'alice/p/', message: 'Access Denied', code: 'AccessDenied'}]
    });
    expect(mockInvalidate).toHaveBeenCalled();
  });

  it('aggregates partial per-key errors (e.g. the marker refusal) into the summary', async () => {
    mockDeleteObjects.mockResolvedValue({
      success: true,
      data: {
        deleted: ['alice/a.txt'],
        errors: [{key: 'alice/DO_NOT_DELETE.txt', message: 'cannot be deleted'}]
      }
    });

    const {result} = render();
    let summary: DeleteSummary | null = null;
    await act(async () => {
      summary = await result.current.runDelete([file('alice/a.txt'), file('alice/DO_NOT_DELETE.txt')]);
    });

    expect(summary).toEqual({
      deletedCount: 1,
      errors: [{key: 'alice/DO_NOT_DELETE.txt', message: 'cannot be deleted'}]
    });
  });
});
