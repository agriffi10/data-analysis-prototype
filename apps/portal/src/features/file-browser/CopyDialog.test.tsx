import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi, beforeEach} from 'vitest';
import {CopyDialog} from './CopyDialog';
import {useFileBrowser} from './useFileBrowser';
import type {UseFileBrowserResult} from './useFileBrowser';
import type {SelectableItem} from './selectionContext';

vi.mock('./useFileBrowser');
const mockUseFileBrowser = vi.mocked(useFileBrowser);

const base: UseFileBrowserResult = {
  files: [],
  folders: [],
  isLoading: false,
  error: null,
  refresh: vi.fn(),
  hasMore: false,
  loadMore: vi.fn(),
  isLoadingMore: false
};

const folder = (prefix: string, name: string) => ({type: 'folder' as const, prefix, name});

beforeEach(() => {
  vi.clearAllMocks();
  mockUseFileBrowser.mockReturnValue(base);
});

function renderDialog(props?: Partial<React.ComponentProps<typeof CopyDialog>>) {
  const onCopy = vi.fn();
  const onCancel = vi.fn();
  render(
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
  return {onCopy, onCancel};
}

describe('CopyDialog — destination picker', () => {
  it('lists navigable destination folders and copies to the browsed prefix', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive')]
    });
    const {onCopy} = renderDialog();

    // At the root ("alice/"), Copy here is enabled (not the current parent for Move,
    // and same-folder is allowed for Copy anyway).
    const copyHere = screen.getByRole('button', {name: /copy here/i});
    expect(copyHere).toBeEnabled();
    fireEvent.click(copyHere);
    expect(onCopy).toHaveBeenCalledWith('alice/');
  });

  it('allows the current parent as a destination (same-folder copy is permitted)', () => {
    // Browse starts at the root; make the root the current parent.
    const {onCopy} = renderDialog({currentPrefix: 'alice/'});
    const copyHere = screen.getByRole('button', {name: /copy here/i});
    expect(copyHere).toBeEnabled();
    fireEvent.click(copyHere);
    expect(onCopy).toHaveBeenCalledWith('alice/');
  });

  it('does not offer the protected athenaresults folder as a destination', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/athenaresults/', 'athenaresults'), folder('alice/docs2/', 'docs2')]
    });
    renderDialog();
    expect(screen.queryByRole('button', {name: /open folder athenaresults/i})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: /open folder docs2/i})).toBeInTheDocument();
  });

  it('hides folders being copied (no descending into them)', () => {
    mockUseFileBrowser.mockReturnValue({
      ...base,
      folders: [folder('alice/archive/', 'archive'), folder('alice/photos/', 'photos')]
    });
    renderDialog({
      items: [{type: 'folder', prefix: 'alice/photos/'}],
      currentPrefix: 'alice/'
    });
    expect(screen.getByRole('button', {name: /open folder archive/i})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /open folder photos/i})).not.toBeInTheDocument();
  });
});

describe('CopyDialog — same-folder name prompt', () => {
  function promptProps(overrides?: Partial<{proposedName: string}>) {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    return {
      onConfirm,
      onCancel,
      sameFolderPrompt: {
        kind: 'file' as const,
        proposedName: overrides?.proposedName ?? 'report (1).pdf',
        validate: (name: string) => (name.includes('/') ? "no '/'" : name.trim() ? null : 'empty'),
        onConfirm,
        onCancel
      }
    };
  }

  it('shows the editable proposed name and confirms it', () => {
    const {onConfirm, sameFolderPrompt} = promptProps();
    renderDialog({sameFolderPrompt});

    const input = screen.getByLabelText(/name for the copy/i) as HTMLInputElement;
    expect(input.value).toBe('report (1).pdf');

    fireEvent.click(screen.getByRole('button', {name: /^copy$/i}));
    expect(onConfirm).toHaveBeenCalledWith('report (1).pdf');
  });

  it('lets the user override the name before confirming', () => {
    const {onConfirm, sameFolderPrompt} = promptProps();
    renderDialog({sameFolderPrompt});

    const input = screen.getByLabelText(/name for the copy/i);
    fireEvent.change(input, {target: {value: 'custom.pdf'}});
    fireEvent.click(screen.getByRole('button', {name: /^copy$/i}));
    expect(onConfirm).toHaveBeenCalledWith('custom.pdf');
  });

  it('disables Copy when the name is invalid', () => {
    const {sameFolderPrompt} = promptProps();
    renderDialog({sameFolderPrompt});

    const input = screen.getByLabelText(/name for the copy/i);
    fireEvent.change(input, {target: {value: 'a/b'}});
    expect(screen.getByRole('button', {name: /^copy$/i})).toBeDisabled();
  });

  it('does not render the folder picker while the same-folder prompt is shown', () => {
    const {sameFolderPrompt} = promptProps();
    renderDialog({sameFolderPrompt});
    expect(screen.queryByRole('button', {name: /copy here/i})).not.toBeInTheDocument();
  });
});
