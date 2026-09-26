import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {useCopy} from './useCopy';
import {copyObject, createFolder, deleteObject, firstFreeName, moveObject} from './fileBrowser.service';
import {invalidateListing} from './invalidateListing';
import {useDelete} from './useDelete';
import type {DeleteSummary} from './useDelete';
import {useCreateFolder} from './useCreateFolder';
import {useMove} from './useMove';
import type {SelectableItem} from './selectionContext';

// ─── from useCopy.test.ts ───
// One factory for all four hook suites: each only reads the members it drives, and
// the pure helpers still come from the real module via the spread.
vi.mock('./fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./fileBrowser.service')>()),
  copyObject: vi.fn(),
  firstFreeName: vi.fn(),
  deleteObject: vi.fn(),
  createFolder: vi.fn(),
  moveObject: vi.fn()
}));

vi.mock('./invalidateListing', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

describe('useCopy', () => {
  /**
   * Mock the AWS boundary only. `validateFolderName` is PURE and comes
   * through `importOriginal` — the factory used to re-implement the validator by hand, which
   * claimed to "reuse the real validation rules" while omitting the control-character rule
   * entirely and returning different messages. A hand-copied validator drifts from the one
   * users hit and asserts the copy instead (SPEC-154 FR-008).
   */

  const mockCopyObject = vi.mocked(copyObject);
  const mockFreeName = vi.mocked(firstFreeName);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render(username: string | undefined = 'alice') {
    return renderHookWithProviders(() => useCopy('us', username));
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useCopy — copy to a different folder', () => {
    it('copies files per object, invalidating ONLY the destination', async () => {
      mockCopyObject.mockResolvedValue({
        success: true,
        data: {destKey: 'alice/dest/f.txt'}
      });

      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceKey: 'alice/docs/f.txt',
          destKey: 'alice/dest/f.txt',
          overwrite: false
        })
      );
      // Dest-only invalidation: the destination is invalidated, the source is NOT.
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/dest/');
      expect(mockInvalidate).not.toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
    });

    it('refuses a FOLDER per item, and still copies the files beside it', async () => {
      // The recursive primitive is gone: an operation whose cost grows with object count belongs
      // on the file-operations plane. A folder reaches this hook only through a race the controls
      // cannot see, and the refusal is per item so a mixed selection is not lost with it.
      mockCopyObject.mockResolvedValue({success: true, data: {destKey: 'alice/dest/f.txt'}});

      const {result} = render();
      act(() =>
        result.current.copyItems(
          [
            {type: 'file', key: 'alice/docs/f.txt'},
            {type: 'folder', prefix: 'alice/docs/x/'}
          ],
          'alice/dest/'
        )
      );

      await waitFor(() =>
        expect(result.current.summary).toEqual({
          count: 1,
          errors: [
            {
              key: 'alice/docs/x/',
              message: 'Folders are copied by the file operations service.',
              code: 'PlaneRequired'
            }
          ]
        })
      );
    });

    it('prompts on a copy collision and overwrites just the collided items on confirm', async () => {
      mockCopyObject
        .mockResolvedValueOnce({
          success: false,
          error: {message: 'exists', code: 'Collision'}
        })
        .mockResolvedValueOnce({
          success: true,
          data: {destKey: 'alice/dest/f.txt'}
        });

      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.collision).not.toBeNull());
      expect(result.current.collision?.count).toBe(1);

      act(() => result.current.collision?.onOverwriteAll());
      await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
      expect(mockCopyObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
    });

    it('errors and does nothing when there is no username', async () => {
      const {result} = renderHookWithProviders(() => useCopy('us', undefined));
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.error).toMatch(/signed in/i));
      expect(mockCopyObject).not.toHaveBeenCalled();
    });
  });

  describe('useCopy — same-folder copy (auto-number, FR-003)', () => {
    it('asks ONCE for the free name and prefills the prompt with it', async () => {
      // The 999-probe loop moved to the route: behind the API each probe would have been a
      // browser → API → S3 round trip, which is strictly worse than what it replaced.
      mockFreeName.mockResolvedValue({success: true, data: 'report (2).pdf'});

      const {result} = render();
      act(() => result.current.startSameFolderCopy({type: 'file', key: 'alice/docs/report.pdf'}, 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.proposedName).toBe('report (2).pdf');
      expect(mockFreeName).toHaveBeenCalledTimes(1);
      expect(mockFreeName).toHaveBeenCalledWith({
        bucket: 'us',
        prefix: 'alice/docs/',
        baseName: 'report.pdf',
        kind: 'file'
      });
    });

    it('asks about a FOLDER by its leaf, so the route knows there is no extension to keep', async () => {
      mockFreeName.mockResolvedValue({success: true, data: 'notes (1)'});

      const {result} = render();
      act(() => result.current.startSameFolderCopy({type: 'folder', prefix: 'alice/docs/notes/'}, 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.kind).toBe('folder');
      expect(result.current.sameFolderPrompt?.proposedName).toBe('notes (1)');
      expect(mockFreeName).toHaveBeenCalledWith(expect.objectContaining({baseName: 'notes', kind: 'folder'}));
    });

    it('refuses a same-folder FOLDER copy rather than recursing', async () => {
      const {result} = render();
      act(() =>
        result.current.runSameFolderCopy({type: 'folder', prefix: 'alice/docs/notes/'}, 'alice/docs/', 'notes (1)')
      );

      await waitFor(() => expect(result.current.error).toMatch(/file operations service/i));
      expect(mockCopyObject).not.toHaveBeenCalled();
    });

    it('says the search was exhausted rather than that something went wrong', async () => {
      // Exhaustion and failure used to be one `null`, and one sentence covered both.
      mockFreeName.mockResolvedValue({
        success: false,
        error: {message: 'Could not find an available name for the copy.', code: 'NoFreeName'}
      });

      const {result} = render();
      act(() => result.current.startSameFolderCopy({type: 'file', key: 'alice/docs/report.pdf'}, 'alice/docs/'));

      await waitFor(() => expect(result.current.error).toBe('Could not find an available name for the copy.'));
      expect(result.current.sameFolderPrompt).toBeNull();
    });

    it('the same-folder prompt validate fn rejects names with a slash', async () => {
      mockFreeName.mockResolvedValue({success: true, data: 'report (1).pdf'});
      const {result} = render();
      act(() => result.current.startSameFolderCopy({type: 'file', key: 'alice/docs/report.pdf'}, 'alice/docs/'));
      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.validate('a/b')).not.toBeNull();
      expect(result.current.sameFolderPrompt?.validate('ok.pdf')).toBeNull();
    });
  });
});

// ─── from useDelete.test.ts ───

describe('useDelete', () => {
  const mockDeleteObject = vi.mocked(deleteObject);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render(username: string | undefined = 'alice') {
    return renderHookWithProviders(() => useDelete('us', 'alice/', username));
  }

  const file = (key: string): SelectableItem => ({type: 'file', key});
  const folder = (prefix: string): SelectableItem => ({type: 'folder', prefix});

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useDelete', () => {
    it('deletes each file in turn and aggregates the count', async () => {
      mockDeleteObject
        .mockResolvedValueOnce({success: true, data: {key: 'alice/a.txt'}})
        .mockResolvedValueOnce({success: true, data: {key: 'alice/b.txt'}});

      const {result} = render();
      let summary: DeleteSummary | null = null;
      await act(async () => {
        summary = await result.current.runDelete([file('alice/a.txt'), file('alice/b.txt')]);
      });

      expect(mockDeleteObject.mock.calls.map(([params]) => params.key)).toEqual(['alice/a.txt', 'alice/b.txt']);
      expect(summary).toEqual({count: 2, errors: []});
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/');
    });

    it('refuses a FOLDER per item, and still deletes the files beside it', async () => {
      // The recursive primitive is gone. A folder reaches this hook only through a race the
      // controls cannot see, so this pins the backstop, which is per item so the rest of the
      // selection is not lost with it.
      mockDeleteObject.mockResolvedValue({success: true, data: {key: 'alice/a.txt'}});

      const {result} = render();
      let summary: DeleteSummary | null = null;
      await act(async () => {
        summary = await result.current.runDelete([file('alice/a.txt'), folder('alice/p/')]);
      });

      expect(summary).toEqual({
        count: 1,
        errors: [
          {
            key: 'alice/p/',
            message: 'Folders are deleted by the file operations service.',
            code: 'PlaneRequired'
          }
        ]
      });
    });

    it('returns null and makes no calls for an empty selection', async () => {
      const {result} = render();
      let summary: DeleteSummary | null = null;
      await act(async () => {
        summary = await result.current.runDelete([]);
      });

      expect(summary).toBeNull();
      expect(mockDeleteObject).not.toHaveBeenCalled();
    });

    it('records a per-file failure as its own row rather than aborting the rest', async () => {
      mockDeleteObject
        .mockResolvedValueOnce({success: false, error: {message: 'denied', code: 'AccessDenied'}})
        .mockResolvedValueOnce({success: true, data: {key: 'alice/b.txt'}});

      const {result} = render();
      let summary: DeleteSummary | null = null;
      await act(async () => {
        summary = await result.current.runDelete([file('alice/a.txt'), file('alice/b.txt')]);
      });

      expect(summary).toEqual({
        count: 1,
        errors: [{key: 'alice/a.txt', message: 'denied', code: 'AccessDenied'}]
      });
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/');
    });

    it('aggregates the marker refusal into the summary rather than failing the run', async () => {
      mockDeleteObject.mockResolvedValueOnce({success: true, data: {key: 'alice/a.txt'}}).mockResolvedValueOnce({
        success: false,
        error: {message: 'cannot be deleted', code: 'ProtectedObject'}
      });

      const {result} = render();
      let summary: DeleteSummary | null = null;
      await act(async () => {
        summary = await result.current.runDelete([file('alice/a.txt'), file('alice/DO_NOT_DELETE.txt')]);
      });

      expect(summary).toEqual({
        count: 1,
        errors: [{key: 'alice/DO_NOT_DELETE.txt', message: 'cannot be deleted', code: 'ProtectedObject'}]
      });
    });
  });
});

// ─── useCreateFolder ───

describe('useCreateFolder', () => {
  const mockCreateFolder = vi.mocked(createFolder);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render() {
    return renderHookWithProviders(() => useCreateFolder('us', 'alice/'));
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useCreateFolder', () => {
    it('renames a folder on collision by re-running with the new name', async () => {
      mockCreateFolder
        .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}})
        .mockResolvedValueOnce({success: true, data: {prefix: 'alice/pictures/'}});

      const {result} = render();
      act(() => result.current.createNewFolder('photos'));

      await waitFor(() => expect(result.current.pendingCollision).toMatchObject({kind: 'folder', label: 'photos'}));
      act(() => result.current.pendingCollision!.retry({rename: 'pictures'}));

      await waitFor(() => expect(mockCreateFolder).toHaveBeenCalledTimes(2));
      expect(mockCreateFolder.mock.calls[1][0]).toEqual({
        bucket: 'us',
        prefix: 'alice/',
        name: 'pictures',
        overwrite: false
      });
      expect(result.current.pendingCollision).toBeNull();
    });

    it('overwrites a folder on collision by re-running the same name with overwrite', async () => {
      mockCreateFolder
        .mockResolvedValueOnce({success: false, error: {message: 'exists', code: 'Collision'}})
        .mockResolvedValueOnce({success: true, data: {prefix: 'alice/photos/'}});

      const {result} = render();
      act(() => result.current.createNewFolder('photos'));

      await waitFor(() => expect(result.current.pendingCollision).not.toBeNull());
      act(() => result.current.pendingCollision!.retry({overwrite: true}));

      await waitFor(() => expect(mockCreateFolder).toHaveBeenCalledTimes(2));
      expect(mockCreateFolder.mock.calls[1][0]).toEqual({
        bucket: 'us',
        prefix: 'alice/',
        name: 'photos',
        overwrite: true
      });
      expect(result.current.pendingCollision).toBeNull();
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

    it('surfaces a non-collision error, releases busy, and clears it on dismiss', async () => {
      mockCreateFolder.mockResolvedValue({success: false, error: {message: 'Access Denied', code: 'AccessDenied'}});

      const {result} = render();
      act(() => result.current.createNewFolder('photos'));

      // Mapped to friendly text (SPEC-106), not the raw 'Access Denied'.
      await waitFor(() =>
        expect(result.current.error).toBe('You don’t have permission to do that. Contact the Administrator.')
      );
      expect(result.current.isBusy).toBe(false);
      expect(mockInvalidate).not.toHaveBeenCalled();

      act(() => result.current.dismissError());
      expect(result.current.error).toBeNull();
    });
  });
});

// ─── from useMove.test.ts ───

describe('useMove', () => {
  const mockMoveObject = vi.mocked(moveObject);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render(username: string | undefined = 'alice') {
    return renderHookWithProviders(() => useMove('us', 'alice/docs/', username));
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

    it('refuses a FOLDER rename rather than recursing', async () => {
      // A folder rename is one CopyObject per contained object, so its cost cannot be bounded
      // without listing the folder first — which is the work the plane exists to take.
      const {result} = render();
      act(() => result.current.renameItem({type: 'folder', prefix: 'alice/docs/old/'}, 'new'));

      await waitFor(() => expect(result.current.error).toMatch(/file operations service/i));
      expect(mockMoveObject).not.toHaveBeenCalled();
    });

    it('errors and does nothing when there is no username', async () => {
      const {result} = renderHookWithProviders(() => useMove('us', 'alice/docs/', undefined));
      act(() => result.current.renameItem({type: 'file', key: 'alice/docs/a.txt'}, 'b.txt'));

      await waitFor(() => expect(result.current.error).toMatch(/signed in/i));
      expect(mockMoveObject).not.toHaveBeenCalled();
    });
  });

  describe('useMove — move', () => {
    it('moves files per object, invalidating both prefixes', async () => {
      mockMoveObject.mockResolvedValue({
        success: true,
        data: {destKey: 'alice/dest/f.txt'}
      });

      const {result} = render();
      act(() => result.current.moveItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
      expect(mockMoveObject).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceKey: 'alice/docs/f.txt',
          destKey: 'alice/dest/f.txt',
          overwrite: false
        })
      );
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/dest/');
    });

    it('refuses a FOLDER per item, and still moves the files beside it', async () => {
      mockMoveObject.mockResolvedValue({success: true, data: {destKey: 'alice/dest/f.txt'}});

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

      await waitFor(() =>
        expect(result.current.summary).toEqual({
          count: 1,
          errors: [
            {
              key: 'alice/docs/x/',
              message: 'Folders are moved by the file operations service.',
              code: 'PlaneRequired'
            }
          ]
        })
      );
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
  });
});
