import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders} from '../../test/renderWithProviders';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {useCopy} from './useCopy';
import {
  copyFolder,
  copyObject,
  createFolder,
  deleteFolder,
  deleteObjects,
  moveFolder,
  moveObject,
  objectExists,
  uploadFile
} from './fileBrowser.service';
import {invalidateListing} from './invalidateListing';
import {useDelete} from './useDelete';
import type {DeleteSummary} from './useDelete';
import {useFileUpload} from './useFileUpload';
import {useMove} from './useMove';
import type {SelectableItem} from './selectionContext';

// ─── from useCopy.test.ts ───
// One factory for all four hook suites: each only reads the members it drives, and
// `uploadPercent` still comes from the real module via the spread.
vi.mock('./fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./fileBrowser.service')>()),
  copyObject: vi.fn(),
  copyFolder: vi.fn(),
  objectExists: vi.fn(),
  deleteObjects: vi.fn(),
  deleteFolder: vi.fn(),
  uploadFile: vi.fn(),
  createFolder: vi.fn(),
  moveObject: vi.fn(),
  moveFolder: vi.fn()
}));

vi.mock('./invalidateListing', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined)
}));

describe('useCopy', () => {
  /**
   * Mock the AWS boundary only. `validateFolderName` and `uploadPercent` are PURE and come
   * through `importOriginal` — the factory used to re-implement the validator by hand, which
   * claimed to "reuse the real validation rules" while omitting the control-character rule
   * entirely and returning different messages. A hand-copied validator drifts from the one
   * users hit and asserts the copy instead (SPEC-154 FR-008).
   */

  const mockCopyObject = vi.mocked(copyObject);
  const mockCopyFolder = vi.mocked(copyFolder);
  const mockObjectExists = vi.mocked(objectExists);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render(username: string | undefined = 'alice') {
    return renderHookWithProviders(() => useCopy('us', 'alice/docs/', username));
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('useCopy — copy to a different folder', () => {
    it('copies files (per object) and folders (recursive), invalidating ONLY the destination', async () => {
      mockCopyObject.mockResolvedValue({
        success: true,
        data: {destKey: 'alice/dest/f.txt'}
      });
      mockCopyFolder.mockResolvedValue({
        success: true,
        data: {copied: ['alice/dest/x/', 'alice/dest/x/a'], errors: []}
      });

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

      await waitFor(() => expect(result.current.summary).toEqual({count: 3, errors: []}));
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceKey: 'alice/docs/f.txt',
          destKey: 'alice/dest/f.txt',
          overwrite: false
        })
      );
      expect(mockCopyFolder).toHaveBeenCalledWith(
        expect.objectContaining({
          sourcePrefix: 'alice/docs/x/',
          destPrefix: 'alice/dest/x/',
          overwrite: false
        })
      );
      // Dest-only invalidation: the destination is invalidated, the source is NOT.
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/dest/');
      expect(mockInvalidate).not.toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
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

    it('aggregates a per-key folder failure into the copy summary', async () => {
      mockCopyFolder.mockResolvedValue({
        success: true,
        data: {
          copied: ['alice/dest/x/'],
          errors: [{key: 'alice/docs/x/locked', message: 'Access Denied'}]
        }
      });

      const {result} = render();
      act(() => result.current.copyItems([{type: 'folder', prefix: 'alice/docs/x/'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.summary).not.toBeNull());
      expect(result.current.summary).toEqual({
        count: 1,
        errors: [{key: 'alice/docs/x/locked', message: 'Access Denied'}]
      });
    });

    it('errors and does nothing when there is no username', async () => {
      const {result} = renderHookWithProviders(() => useCopy('us', 'alice/docs/', undefined));
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/f.txt'}], 'alice/dest/'));

      await waitFor(() => expect(result.current.error).toMatch(/signed in/i));
      expect(mockCopyObject).not.toHaveBeenCalled();
    });
  });

  describe('useCopy — same-folder copy (auto-number, FR-003)', () => {
    it('proposes "{name} (1)" for a file when the destination is the current parent', async () => {
      // (1) is free.
      mockObjectExists.mockResolvedValue({success: true, data: false});

      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/report.pdf'}], 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.kind).toBe('file');
      expect(result.current.sameFolderPrompt?.proposedName).toBe('report (1).pdf');
      // HEAD-checked the (1) candidate at the current parent.
      expect(mockObjectExists).toHaveBeenCalledWith({
        bucket: 'us',
        key: 'alice/docs/report (1).pdf'
      });
      // No copy runs until the user confirms.
      expect(mockCopyObject).not.toHaveBeenCalled();
    });

    it('increments to "{name} (2)" when "{name} (1)" already exists', async () => {
      mockObjectExists
        .mockResolvedValueOnce({success: true, data: true}) // (1) taken
        .mockResolvedValueOnce({success: true, data: false}); // (2) free

      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/report.pdf'}], 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.proposedName).toBe('report (2).pdf');
    });

    it('proposes "{leaf} (1)" for a folder and copies recursively on confirm', async () => {
      mockObjectExists.mockResolvedValue({success: true, data: false});
      mockCopyFolder.mockResolvedValue({
        success: true,
        data: {copied: ['alice/docs/notes (1)/'], errors: []}
      });

      const {result} = render();
      act(() => result.current.copyItems([{type: 'folder', prefix: 'alice/docs/notes/'}], 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.kind).toBe('folder');
      expect(result.current.sameFolderPrompt?.proposedName).toBe('notes (1)');

      act(() => result.current.sameFolderPrompt?.onConfirm('notes (1)'));
      await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
      expect(mockCopyFolder).toHaveBeenCalledWith(
        expect.objectContaining({
          sourcePrefix: 'alice/docs/notes/',
          destPrefix: 'alice/docs/notes (1)/'
        })
      );
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
    });

    it('copies a file under the confirmed (possibly edited) name', async () => {
      mockObjectExists.mockResolvedValue({success: true, data: false});
      mockCopyObject.mockResolvedValue({
        success: true,
        data: {destKey: 'alice/docs/my copy.pdf'}
      });

      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/report.pdf'}], 'alice/docs/'));

      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      act(() => result.current.sameFolderPrompt?.onConfirm('my copy.pdf'));

      await waitFor(() => expect(result.current.summary).toEqual({count: 1, errors: []}));
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceKey: 'alice/docs/report.pdf',
          destKey: 'alice/docs/my copy.pdf'
        })
      );
    });

    it('the same-folder prompt validate fn rejects names with a slash', async () => {
      mockObjectExists.mockResolvedValue({success: true, data: false});
      const {result} = render();
      act(() => result.current.copyItems([{type: 'file', key: 'alice/docs/report.pdf'}], 'alice/docs/'));
      await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
      expect(result.current.sameFolderPrompt?.validate('a/b')).not.toBeNull();
      expect(result.current.sameFolderPrompt?.validate('ok.pdf')).toBeNull();
    });
  });
});

// ─── from useDelete.test.ts ───

describe('useDelete', () => {
  const mockDeleteObjects = vi.mocked(deleteObjects);
  const mockDeleteFolder = vi.mocked(deleteFolder);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render(username: string | undefined = 'alice') {
    return renderHookWithProviders(() => useDelete('us', 'alice/', username, 'alice/'));
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
        username: 'alice',
        // The space root, which is what lets deleteFolder tell the space's own
        // athenaresults/ from a like-named user folder (SPEC-150 FR-007).
        rootPrefix: 'alice/'
      });
      expect(summary).toEqual({count: 4, errors: []});
      expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/');
    });

    it('does nothing and surfaces an error when there is no username', async () => {
      // Pass undefined directly — render()'s default would otherwise mask it.
      const {result} = renderHookWithProviders(() => useDelete('us', 'alice/', undefined, 'alice/'));
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
        count: 1,
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
        count: 1,
        errors: [{key: 'alice/DO_NOT_DELETE.txt', message: 'cannot be deleted'}]
      });
    });
  });
});

// ─── from useFileUpload.test.ts ───

describe('useFileUpload', () => {
  const mockUpload = vi.mocked(uploadFile);
  const mockCreateFolder = vi.mocked(createFolder);
  const mockInvalidate = vi.mocked(invalidateListing);

  function render() {
    return renderHookWithProviders(() => useFileUpload('us', 'alice/'));
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
});

// ─── from useMove.test.ts ───

describe('useMove', () => {
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
});
