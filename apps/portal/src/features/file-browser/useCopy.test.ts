import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useCopy } from './useCopy';
import { copyObject, copyFolder, objectExists } from './fileBrowser.service';
import { invalidateListing } from '../../lib/queryClient';

vi.mock('./fileBrowser.service', () => ({
  copyObject: vi.fn(),
  copyFolder: vi.fn(),
  objectExists: vi.fn(),
  uploadPercent: (loaded: number, total: number) => (total > 0 ? Math.round((loaded / total) * 100) : 100),
  // Reuse the real validation rules (non-empty trimmed, no `/`, no control chars).
  validateFolderName: (name: string) => {
    if (name.trim().length === 0) return 'Folder name cannot be empty.';
    if (name !== name.trim()) return 'spaces';
    if (name.includes('/')) return "no '/'";
    return null;
  },
}));
vi.mock('../../lib/queryClient', () => ({
  invalidateListing: vi.fn().mockResolvedValue(undefined),
}));

const mockCopyObject = vi.mocked(copyObject);
const mockCopyFolder = vi.mocked(copyFolder);
const mockObjectExists = vi.mocked(objectExists);
const mockInvalidate = vi.mocked(invalidateListing);

function wrapper() {
  const client = new QueryClient();
  return ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
}

function render(username: string | undefined = 'alice') {
  return renderHook(() => useCopy('us', 'alice/docs/', username), {
    wrapper: wrapper(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useCopy — copy to a different folder', () => {
  it('copies files (per object) and folders (recursive), invalidating ONLY the destination', async () => {
    mockCopyObject.mockResolvedValue({
      success: true,
      data: { destKey: 'alice/dest/f.txt' },
    });
    mockCopyFolder.mockResolvedValue({
      success: true,
      data: { copied: ['alice/dest/x/', 'alice/dest/x/a'], errors: [] },
    });

    const { result } = render();
    act(() =>
      result.current.copyItems(
        [
          { type: 'file', key: 'alice/docs/f.txt' },
          { type: 'folder', prefix: 'alice/docs/x/' },
        ],
        'alice/dest/'
      )
    );

    await waitFor(() => expect(result.current.summary).toEqual({ copiedCount: 3, errors: [] }));
    expect(mockCopyObject).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceKey: 'alice/docs/f.txt',
        destKey: 'alice/dest/f.txt',
        overwrite: false,
      })
    );
    expect(mockCopyFolder).toHaveBeenCalledWith(
      expect.objectContaining({
        sourcePrefix: 'alice/docs/x/',
        destPrefix: 'alice/dest/x/',
        overwrite: false,
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
        error: { message: 'exists', code: 'Collision' },
      })
      .mockResolvedValueOnce({
        success: true,
        data: { destKey: 'alice/dest/f.txt' },
      });

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/f.txt' }], 'alice/dest/'));

    await waitFor(() => expect(result.current.copyCollision).not.toBeNull());
    expect(result.current.copyCollision?.count).toBe(1);

    act(() => result.current.copyCollision?.onOverwriteAll());
    await waitFor(() => expect(result.current.summary).toEqual({ copiedCount: 1, errors: [] }));
    expect(mockCopyObject).toHaveBeenLastCalledWith(expect.objectContaining({ overwrite: true }));
  });

  it('aggregates a per-key folder failure into the copy summary', async () => {
    mockCopyFolder.mockResolvedValue({
      success: true,
      data: {
        copied: ['alice/dest/x/'],
        errors: [{ key: 'alice/docs/x/locked', message: 'Access Denied' }],
      },
    });

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'folder', prefix: 'alice/docs/x/' }], 'alice/dest/'));

    await waitFor(() => expect(result.current.summary).not.toBeNull());
    expect(result.current.summary).toEqual({
      copiedCount: 1,
      errors: [{ item: 'alice/docs/x/locked', message: 'Access Denied' }],
    });
  });

  it('errors and does nothing when there is no username', async () => {
    const { result } = renderHook(() => useCopy('us', 'alice/docs/', undefined), { wrapper: wrapper() });
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/f.txt' }], 'alice/dest/'));

    await waitFor(() => expect(result.current.error).toMatch(/signed in/i));
    expect(mockCopyObject).not.toHaveBeenCalled();
  });
});

describe('useCopy — same-folder copy (auto-number, FR-003)', () => {
  it('proposes "{name} (1)" for a file when the destination is the current parent', async () => {
    // (1) is free.
    mockObjectExists.mockResolvedValue({ success: true, data: false });

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/report.pdf' }], 'alice/docs/'));

    await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
    expect(result.current.sameFolderPrompt?.kind).toBe('file');
    expect(result.current.sameFolderPrompt?.proposedName).toBe('report (1).pdf');
    // HEAD-checked the (1) candidate at the current parent.
    expect(mockObjectExists).toHaveBeenCalledWith({
      bucket: 'us',
      key: 'alice/docs/report (1).pdf',
    });
    // No copy runs until the user confirms.
    expect(mockCopyObject).not.toHaveBeenCalled();
  });

  it('increments to "{name} (2)" when "{name} (1)" already exists', async () => {
    mockObjectExists
      .mockResolvedValueOnce({ success: true, data: true }) // (1) taken
      .mockResolvedValueOnce({ success: true, data: false }); // (2) free

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/report.pdf' }], 'alice/docs/'));

    await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
    expect(result.current.sameFolderPrompt?.proposedName).toBe('report (2).pdf');
  });

  it('proposes "{leaf} (1)" for a folder and copies recursively on confirm', async () => {
    mockObjectExists.mockResolvedValue({ success: true, data: false });
    mockCopyFolder.mockResolvedValue({
      success: true,
      data: { copied: ['alice/docs/notes (1)/'], errors: [] },
    });

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'folder', prefix: 'alice/docs/notes/' }], 'alice/docs/'));

    await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
    expect(result.current.sameFolderPrompt?.kind).toBe('folder');
    expect(result.current.sameFolderPrompt?.proposedName).toBe('notes (1)');

    act(() => result.current.sameFolderPrompt?.onConfirm('notes (1)'));
    await waitFor(() => expect(result.current.summary).toEqual({ copiedCount: 1, errors: [] }));
    expect(mockCopyFolder).toHaveBeenCalledWith(
      expect.objectContaining({
        sourcePrefix: 'alice/docs/notes/',
        destPrefix: 'alice/docs/notes (1)/',
      })
    );
    expect(mockInvalidate).toHaveBeenCalledWith(expect.anything(), 'us', 'alice/docs/');
  });

  it('copies a file under the confirmed (possibly edited) name', async () => {
    mockObjectExists.mockResolvedValue({ success: true, data: false });
    mockCopyObject.mockResolvedValue({
      success: true,
      data: { destKey: 'alice/docs/my copy.pdf' },
    });

    const { result } = render();
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/report.pdf' }], 'alice/docs/'));

    await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
    act(() => result.current.sameFolderPrompt?.onConfirm('my copy.pdf'));

    await waitFor(() => expect(result.current.summary).toEqual({ copiedCount: 1, errors: [] }));
    expect(mockCopyObject).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceKey: 'alice/docs/report.pdf',
        destKey: 'alice/docs/my copy.pdf',
      })
    );
  });

  it('the same-folder prompt validate fn rejects names with a slash', async () => {
    mockObjectExists.mockResolvedValue({ success: true, data: false });
    const { result } = render();
    act(() => result.current.copyItems([{ type: 'file', key: 'alice/docs/report.pdf' }], 'alice/docs/'));
    await waitFor(() => expect(result.current.sameFolderPrompt).not.toBeNull());
    expect(result.current.sameFolderPrompt?.validate('a/b')).not.toBeNull();
    expect(result.current.sameFolderPrompt?.validate('ok.pdf')).toBeNull();
  });
});
