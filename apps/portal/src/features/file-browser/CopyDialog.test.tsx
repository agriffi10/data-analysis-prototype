import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {CopyDialog} from './CopyDialog';
import * as service from './fileBrowser.service';
import type {SelectableItem} from './selectionContext';
import type {FileListPage, S3FolderItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL CopyDialog → real
// DestinationPicker → real useFileBrowser, mocking ONLY the AWS boundary
// (listFiles). Pure helpers stay real via importActual.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, listFiles: vi.fn()};
});
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const mock = vi.mocked(service);

const folder = (prefix: string, name: string): S3FolderItem => ({type: 'folder', prefix, name});
const ok = <T,>(data: T) => ({success: true as const, data});
const pageOf = (folders: S3FolderItem[] = []): FileListPage => ({files: [], folders, isTruncated: false});

function renderDialog(props?: Partial<React.ComponentProps<typeof CopyDialog>>) {
  const onCopy = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <CopyDialog
      bucket="us"
      items={[{type: 'file', key: 'alice/docs/f.txt'} satisfies SelectableItem]}
      rootPrefix="alice/"
      rootLabel="My Files"
      currentPrefix="alice/docs/"
      onCopy={onCopy}
      onCancel={onCancel}
      {...props}
    />
  );
  return {...result, onCopy, onCancel};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.listFiles.mockResolvedValue(ok(pageOf()));
});

describe('CopyDialog — destination picker', () => {
  it('copies to the browsed prefix, including the current parent (same-folder allowed)', async () => {
    // Browse starts at the root; the current parent is the root here, and Copy
    // permits it (→ same-folder auto-number), so "Copy here" is enabled.
    const {user, onCopy} = renderDialog({currentPrefix: 'alice/'});
    const copyHere = screen.getByRole('button', {name: /copy here/i});
    expect(copyHere).toBeEnabled();
    await user.click(copyHere);
    expect(onCopy).toHaveBeenCalledWith('alice/', 'us', undefined);
  });

  it('filters protected (athenaresults) and the folders being copied from the picker', async () => {
    mock.listFiles.mockResolvedValue(
      ok(
        pageOf([
          folder('alice/athenaresults/', 'athenaresults'),
          folder('alice/photos/', 'photos'),
          folder('alice/docs2/', 'docs2')
        ])
      )
    );
    renderDialog({items: [{type: 'folder', prefix: 'alice/photos/'}], currentPrefix: 'alice/'});
    expect(await screen.findByRole('button', {name: /open folder docs2/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
  });
});

describe('CopyDialog — same-folder name prompt', () => {
  function promptProps() {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    return {
      onConfirm,
      onCancel,
      sameFolderPrompt: {
        kind: 'file' as const,
        proposedName: 'report (1).pdf',
        validate: (name: string) => (name.includes('/') ? "no '/'" : name.trim() ? null : 'empty'),
        onConfirm,
        onCancel
      }
    };
  }

  it('replaces the picker with an editable pre-filled name and confirms an override', async () => {
    const {onConfirm, sameFolderPrompt} = promptProps();
    const {user} = renderDialog({sameFolderPrompt});

    // The folder picker is gone while the prompt is shown.
    expect(screen.queryByRole('button', {name: /copy here/i})).not.toBeInTheDocument();

    const input = screen.getByLabelText(/name for the copy/i) as HTMLInputElement;
    expect(input.value).toBe('report (1).pdf');
    await user.clear(input);
    await user.type(input, 'custom.pdf');
    await user.click(screen.getByRole('button', {name: /^copy$/i}));
    expect(onConfirm).toHaveBeenCalledWith('custom.pdf');
  });

  it('disables Copy when the proposed name is invalid', async () => {
    const {sameFolderPrompt} = promptProps();
    const {user} = renderDialog({sameFolderPrompt});
    const input = screen.getByLabelText(/name for the copy/i);
    await user.clear(input);
    await user.type(input, 'a/b');
    expect(screen.getByRole('button', {name: /^copy$/i})).toBeDisabled();
  });
});
