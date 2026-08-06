import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useMove} from './useMove';
import {moveObject, moveFolder} from './fileBrowser.service';
import {invalidateListing} from '../../lib/queryClient';

vi.mock('./fileBrowser.service', () => ({
  moveObject: vi.fn(),
  moveFolder: vi.fn(),
  uploadPercent: (loaded: number, total: number) => (total > 0 ? Math.round((loaded / total) * 100) : 100)
}));
vi.mock('../../lib/queryClient', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

const mockMoveObject = vi.mocked(moveObject);
const mockMoveFolder = vi.mocked(moveFolder);
const mockInvalidate = vi.mocked(invalidateListing);

function render(username: string | undefined = 'alice') {
  return renderHookWithProviders(() => useMove('us', 'alice/docs/', username, 'alice/'));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useMove — rename', () => {
  it('renames a file within its parent and invalidates the source listing', async () => {
    mockMoveObject.mockResolvedValue({
      success: true,
      data: {destKey: 'alice/docs/new.txt'}
    });

    const {result} = render();
    act(() => result.current.renameItem({type: 'file', key: 'alice/docs/old.txt'}, 'new.txt'));

    await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
    expect(mockMoveObject).toHaveBeenCalledWith({
      bucket: 'us',
      sourceKey: 'alice/docs/old.txt',
      destKey: 'alice/docs/new.txt',
      username: 'alice',
      overwrite: false
    });
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
  });

  it('renames a folder recursively to a new leaf prefix', async () => {
    mockMoveFolder.mockResolvedValue({
      success: true,
      data: {moved: ['alice/docs/old/', 'alice/docs/old/a.txt'], errors: []}
    });

    const {result} = render();
    act(() => result.current.renameItem({type: 'folder', prefix: 'alice/docs/old/'}, 'new'));

    await waitFor(() => expect(result.current.summary).toEqual({count: 2, errors: []}));
    expect(mockMoveFolder).toHaveBeenCalledWith(
      expect.objectContaining({
        bucket: 'us',
        sourcePrefix: 'alice/docs/old/',
        destPrefix: 'alice/docs/new/',
        username: 'alice',
        overwrite: false
      })
    );
  });

  it('surfaces a rename collision, then overwrites on confirm', async () => {
    mockMoveObject
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'exists', code: 'Collision'}
      })
      .mockResolvedValueOnce({
        success: true,
        data: {destKey: 'alice/docs/new.txt'}
      });

    const {result} = render();
    act(() => result.current.renameItem({type: 'file', key: 'alice/docs/old.txt'}, 'new.txt'));

    await waitFor(() => expect(result.current.renameCollision).not.toBeNull());
    expect(result.current.renameCollision?.kind).toBe('file');

    act(() => result.current.renameCollision?.onOverwrite());
    await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
    expect(mockMoveObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
  });

  it('errors and does nothing when there is no username', async () => {
    const {result} = renderHookWithProviders(() => useMove('us', 'alice/docs/', undefined, 'alice/'));
    act(() => result.current.renameItem({type: 'file', key: 'alice/docs/a.txt'}, 'b.txt'));

    await waitFor(() => expect(result.current.error).toMatch(/signed in/i));
    expect(mockMoveObject).not.toHaveBeenCalled();
  });
});

describe('useMove — move', () => {
  it('moves files (per object) and folders (recursive), invalidating both prefixes', async () => {
    mockMoveObject.mockResolvedValue({
      success: true,
      data: {destKey: 'alice/dest/f.txt'}
    });
    mockMoveFolder.mockResolvedValue({
      success: true,
      data: {moved: ['alice/dest/x/', 'alice/dest/x/a'], errors: []}
    });

    const {result} = render();
    act(() =>
      result.current.moveItems(
        [
          {type: 'file', key: 'alice/docs/f.txt'},
          {type: 'folder', prefix: 'alice/docs/x/'}
        ],
        'alice/dest/'
      )
    );

    await waitFor(() => expect(result.current.summary).toEqual({count: 3, errors: []}));
    expect(mockMoveObject).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceKey: 'alice/docs/f.txt',
        destKey: 'alice/dest/f.txt',
        overwrite: false
      })
    );
    expect(mockMoveFolder).toHaveBeenCalledWith(
      expect.objectContaining({
        sourcePrefix: 'alice/docs/x/',
        destPrefix: 'alice/dest/x/',
        overwrite: false
      })
    );
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/dest/');
  });

  it('prompts on a move collision and overwrites just the collided items on confirm', async () => {
    mockMoveObject
      .mockResolvedValueOnce({
        success: false,
        error: {message: 'exists', code: 'Collision'}
      })
      .mockResolvedValueOnce({
        success: true,
        data: {destKey: 'alice/dest/f.txt'}
      });

    const {result} = render();
    act(() => result.current.moveItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

    await waitFor(() => expect(result.current.collision).not.toBeNull());
    expect(result.current.collision?.count).toBe(1);

    act(() => result.current.collision?.onOverwriteAll());
    await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
    expect(mockMoveObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
  });

  it('aggregates a per-key folder failure into the move summary', async () => {
    mockMoveFolder.mockResolvedValue({
      success: true,
      data: {
        moved: ['alice/dest/x/'],
        errors: [{key: 'alice/docs/x/locked', message: 'Access Denied'}]
      }
    });

    const {result} = render();
    act(() => result.current.moveItems([{type: 'folder', prefix: 'alice/docs/x/'}], 'alice/dest/'));

    await waitFor(() => expect(result.current.summary).not.toBeNull());
    expect(result.current.summary).toEqual({
      count: 1,
      errors: [{key: 'alice/docs/x/locked', message: 'Access Denied'}]
    });
  });
});
