import {describe, expect, it, vi} from 'vitest';
import {act, fireEvent, render, renderHook, screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {BatchOverwritePrompt} from './BatchOverwritePrompt';
import {CollisionPrompt} from './CollisionPrompt';
import {CreateFolderDialog} from './CreateFolderDialog';
import {DeleteConfirmDialog} from './DeleteConfirmDialog';
import {RenameDialog} from './RenameDialog';
import {FileListRowMobile} from './FileListRowMobile';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {FolderDetailsPanel} from './FolderDetailsPanel';
import {OperationFeedback} from './OperationFeedback';
import {ParentFolderRow} from './ParentFolderRow';
import {UploadDropzone} from './UploadDropzone';
import {SelectionProvider} from './SelectionProvider';
import {initialSelectionState, selectionReducer, useSelection} from './selectionContext';
import type {SelectableItem, SelectionContextValue} from './selectionContext';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';
import type {BulkOperationState} from './fileBrowser.types';
import type {ReactNode} from 'react';
import userEvent from '@testing-library/user-event';

// ─── from BatchOverwritePrompt.test.tsx ───
describe('BatchOverwritePrompt', () => {
  describe('BatchOverwritePrompt', () => {
    it('names the conflicting count and wires Overwrite all / Cancel', async () => {
      const onOverwriteAll = vi.fn();
      const onCancel = vi.fn();
      const {user} = renderWithProviders(
        <BatchOverwritePrompt
          count={3}
          onOverwriteAll={onOverwriteAll}
          onCancel={onCancel}
        />
      );
      expect(screen.getByRole('alertdialog', {name: 'Destination already has items'})).toBeInTheDocument();
      expect(screen.getByText(/3 item\(s\) already exist/)).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Overwrite all'}));
      expect(onOverwriteAll).toHaveBeenCalledOnce();
      await user.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalledOnce();
    });
  });
});

// ─── from CollisionPrompt.test.tsx ───
describe('CollisionPrompt', () => {
  function setup(overrides = {}) {
    const props = {
      kind: 'file' as const,
      name: 'report.pdf',
      onOverwrite: vi.fn(),
      onRename: vi.fn(),
      onCancel: vi.fn(),
      ...overrides
    };
    render(<CollisionPrompt {...props} />);
    return props;
  }

  describe('CollisionPrompt', () => {
    it('overwrites on confirm', () => {
      const {onOverwrite} = setup();
      fireEvent.click(screen.getByRole('button', {name: /overwrite/i}));
      expect(onOverwrite).toHaveBeenCalledTimes(1);
    });

    it('disables save when the new name is unchanged', () => {
      setup();
      fireEvent.click(screen.getByRole('button', {name: /^rename$/i}));
      // input still equals the original name → save disabled
      expect(screen.getByRole('button', {name: /save as new name/i})).toBeDisabled();
    });
  });
});

// ─── from CreateFolderDialog.test.tsx ───
describe('CreateFolderDialog', () => {
  describe('CreateFolderDialog', () => {
    it('creates with a valid name', () => {
      const onCreate = vi.fn();
      render(
        <CreateFolderDialog
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );

      fireEvent.change(screen.getByLabelText(/folder name/i), {
        target: {value: 'photos'}
      });
      fireEvent.click(screen.getByRole('button', {name: /^create$/i}));

      expect(onCreate).toHaveBeenCalledWith('photos');
    });

    it('shows a validation error and does not create an invalid name', () => {
      const onCreate = vi.fn();
      render(
        <CreateFolderDialog
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );

      fireEvent.change(screen.getByLabelText(/folder name/i), {
        target: {value: 'a/b'}
      });
      fireEvent.click(screen.getByRole('button', {name: /^create$/i}));

      expect(onCreate).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent(/\//);
    });
  });
});

// ─── from DeleteConfirmDialog.test.tsx ───
describe('DeleteConfirmDialog', () => {
  const file = (key: string): SelectableItem => ({type: 'file', key});
  const folder = (prefix: string): SelectableItem => ({type: 'folder', prefix});

  function setup(items: SelectableItem[], isDeleting = false) {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DeleteConfirmDialog
        items={items}
        isDeleting={isDeleting}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    return {onConfirm, onCancel};
  }

  describe('DeleteConfirmDialog', () => {
    it('names a single file and warns it is irreversible', () => {
      setup([file('alice/report.pdf')]);
      const dialog = screen.getByRole('alertdialog', {name: /confirm delete/i});
      expect(dialog).toHaveTextContent(/delete .*report\.pdf/i);
      expect(dialog).toHaveTextContent(/can.t be undone/i);
    });

    it('shows the count and an item list for multiple items', () => {
      setup([file('alice/a.txt'), file('alice/b.txt'), folder('alice/c/')]);
      const dialog = screen.getByRole('alertdialog');
      expect(dialog).toHaveTextContent(/delete 3 items/i);
      expect(dialog).toHaveTextContent('a.txt');
      expect(dialog).toHaveTextContent('b.txt');
      expect(dialog).toHaveTextContent('c');
      expect(dialog).toHaveTextContent(/folders are deleted along with all of their contents/i);
    });

    it('truncates a long list with an "and N more" line', () => {
      const items = Array.from({length: 7}, (_, i) => file(`alice/f${i}.txt`));
      setup(items);
      expect(screen.getByText(/and 2 more/i)).toBeInTheDocument();
    });

    it('confirms and cancels via the buttons', () => {
      const {onConfirm, onCancel} = setup([file('alice/a.txt')]);
      fireEvent.click(screen.getByRole('button', {name: /^delete$/i}));
      expect(onConfirm).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole('button', {name: /cancel/i}));
      expect(onCancel).toHaveBeenCalledOnce();
    });

    it('disables actions and shows progress while deleting', () => {
      setup([file('alice/a.txt')], true);
      expect(screen.getByRole('button', {name: /deleting/i})).toBeDisabled();
      expect(screen.getByRole('button', {name: /cancel/i})).toBeDisabled();
    });
  });
});

// ─── from RenameDialog.test.tsx ───
describe('RenameDialog', () => {
  function setup(overrides?: {
    kind?: 'file' | 'folder';
    currentName?: string;
    parentPrefix?: string;
    isBusy?: boolean;
  }) {
    const onRename = vi.fn();
    const onCancel = vi.fn();
    render(
      <RenameDialog
        kind={overrides?.kind ?? 'file'}
        currentName={overrides?.currentName ?? 'report.pdf'}
        parentPrefix={overrides?.parentPrefix ?? 'alice/'}
        isBusy={overrides?.isBusy}
        onRename={onRename}
        onCancel={onCancel}
      />
    );
    return {onRename, onCancel};
  }

  describe('RenameDialog', () => {
    it('prefills the base name (extension held separately) and disables Rename until it changes', () => {
      setup();
      const input = screen.getByLabelText(/new name/i) as HTMLInputElement;
      expect(input.value).toBe('report'); // ".pdf" is locked, not in the editable field
      expect(screen.getByText(/extension can’t be changed/i)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /^rename$/i})).toBeDisabled();
    });

    it('enables Rename for a changed, valid name and submits it with the extension re-appended', () => {
      const {onRename} = setup();
      fireEvent.change(screen.getByLabelText(/new name/i), {
        target: {value: 'final'}
      });
      const btn = screen.getByRole('button', {name: /^rename$/i});
      expect(btn).toBeEnabled();
      fireEvent.click(btn);
      expect(onRename).toHaveBeenCalledWith('final.pdf');
    });

    it('lets a folder name be edited in full (no locked extension)', () => {
      const onRename = vi.fn();
      render(
        <RenameDialog
          kind="folder"
          currentName="my.reports"
          parentPrefix="alice/"
          onRename={onRename}
          onCancel={vi.fn()}
        />
      );
      const input = screen.getByLabelText(/new name/i) as HTMLInputElement;
      expect(input.value).toBe('my.reports');
      fireEvent.change(input, {target: {value: 'archive.2024'}});
      fireEvent.click(screen.getByRole('button', {name: /^rename$/i}));
      expect(onRename).toHaveBeenCalledWith('archive.2024');
    });

    it('rejects an invalid name (contains a slash) and keeps Rename disabled', () => {
      setup();
      fireEvent.change(screen.getByLabelText(/new name/i), {
        target: {value: 'a/b'}
      });
      expect(screen.getByRole('alert')).toHaveTextContent('/');
      expect(screen.getByRole('button', {name: /^rename$/i})).toBeDisabled();
    });

    // A file named like the app's folder is not that folder, and nothing downstream refuses it.
    it.each([
      {
        kind: 'folder' as const,
        parentPrefix: 'alice/',
        value: 'shared_tables',
        refusal: '“shared_tables” is a folder the app manages at the top of a space. Pick another name.'
      },
      {
        kind: 'folder' as const,
        parentPrefix: 'alice/projects/',
        value: 'user_settings',
        refusal: '“user_settings” is a name the app keeps for its own folders. Pick another name.'
      },
      {kind: 'file' as const, parentPrefix: 'alice/', value: 'shared_tables', refusal: null}
    ])('checks a $kind renamed to “$value” in $parentPrefix', ({kind, parentPrefix, value, refusal}) => {
      setup({kind, currentName: 'notes', parentPrefix});
      fireEvent.change(screen.getByLabelText(/new name/i), {target: {value}});
      expect(screen.queryByRole('alert')?.textContent ?? null).toBe(refusal);
      expect(screen.getByRole('button', {name: /^rename$/i})).toHaveProperty('disabled', refusal !== null);
    });
  });
});

// ─── from FileListRowMobile.test.tsx ───
describe('FileListRowMobile', () => {
  const file: S3FileItem = {
    type: 'file',
    key: 'alice/docs/report.pdf',
    name: 'report.pdf',
    size: 2048,
    lastModified: new Date('2026-03-01T12:00:00Z')
  };
  const folder: S3FolderItem = {type: 'folder', prefix: 'alice/docs/', name: 'docs'};

  function renderFile(over: Partial<Parameters<typeof FileListRowMobile>[0]> = {}) {
    const onActivate = vi.fn();
    const onDetails = vi.fn();
    const onToggleSelect = vi.fn();
    render(
      <ul>
        <FileListRowMobile
          kind="file"
          file={file}
          onActivate={onActivate}
          onDetails={onDetails}
          selectable={true}
          isSelected={false}
          onToggleSelect={onToggleSelect}
          {...(over as object)}
        />
      </ul>
    );
    return {onActivate, onDetails, onToggleSelect};
  }

  describe('FileListRowMobile', () => {
    it('renders a file as two lines (name + TYPE · date) with a trailing size', () => {
      renderFile();
      expect(screen.getByText('report.pdf')).toBeInTheDocument();
      expect(screen.getByText(/PDF · Mar 1, 2026/)).toBeInTheDocument();
      expect(screen.getByText('2.0 KB')).toBeInTheDocument();
    });

    it('activates (downloads) on body tap and opens details from the Details control', () => {
      const {onActivate, onDetails} = renderFile();
      fireEvent.click(screen.getByRole('button', {name: 'Download report.pdf'}));
      expect(onActivate).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole('button', {name: 'Details for report.pdf'}));
      expect(onDetails).toHaveBeenCalledWith(file);
    });

    it('shows a downloading indicator in place of the size while a download is signing', () => {
      renderFile({isDownloading: true});
      expect(screen.getByLabelText('Downloading')).toBeInTheDocument();
      expect(screen.queryByText('2.0 KB')).not.toBeInTheDocument();
    });

    it('renders a folder as name + "Folder" with a trailing chevron (no size) and opens on tap', () => {
      const onOpen = vi.fn();
      const onDetails = vi.fn();
      render(
        <ul>
          <FileListRowMobile
            kind="folder"
            folder={folder}
            onOpen={onOpen}
            onDetails={onDetails}
            selectable
            isSelected={false}
            onToggleSelect={vi.fn()}
          />
        </ul>
      );
      expect(screen.getByText('docs')).toBeInTheDocument();
      expect(screen.getByText('Folder')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', {name: 'Open folder docs'}));
      expect(onOpen).toHaveBeenCalledOnce();
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <ul>
          <FileListRowMobile
            kind="file"
            file={file}
            onActivate={vi.fn()}
            onDetails={vi.fn()}
            selectable
            isSelected={false}
            onToggleSelect={vi.fn()}
          />
        </ul>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from FolderDetailsPanel.test.tsx ───
describe('FolderDetailsPanel', () => {
  const folder: S3FolderItem = {
    type: 'folder',
    prefix: 'alice/docs/',
    name: 'docs'
  };

  function renderPanel(
    over: {canModify?: boolean; onClose?: () => void; onRequestRename?: (f: S3FolderItem) => void} = {}
  ) {
    const onClose = over.onClose ?? vi.fn();
    const onRequestRename = over.onRequestRename ?? vi.fn();
    // Through the provider stack rather than a bare `render`: the panel asks, once, whether
    // anything still lives under its prefix — a folder the plane removed is otherwise a full
    // panel with live actions and no error at all.
    renderWithProviders(
      <FolderDetailsPanel
        bucket="my-bucket"
        folder={folder}
        rootPrefix="alice/"
        canModify={over.canModify ?? true}
        onRequestRename={onRequestRename}
        onClose={onClose}
      />
    );
    return {onClose, onRequestRename};
  }

  describe('FolderDetailsPanel', () => {
    it('shows the name, user-relative path, and a Full Cloud Path S3 URI', () => {
      renderPanel();
      // Path is shown relative to the user root (the username prefix is stripped).
      expect(screen.getByText('docs/')).toBeInTheDocument();
      expect(screen.getByText('Full Cloud Path')).toBeInTheDocument();
      expect(screen.getByText('s3://my-bucket/alice/docs/')).toBeInTheDocument();
    });

    it('is a modal dialog labelled for the folder', () => {
      renderPanel();
      const dialog = screen.getByRole('dialog', {name: /details for docs/i});
      expect(dialog).toHaveAttribute('aria-modal', 'true');
    });

    // ── SPEC-097: Rename action (folders aren't downloadable) ───────────────────

    it('renders a Rename action when canModify and invokes onRequestRename', () => {
      const {onRequestRename} = renderPanel({canModify: true});
      const rename = screen.getByRole('button', {name: 'Rename docs'});
      expect(rename).toBeInTheDocument();
      fireEvent.click(rename);
      expect(onRequestRename).toHaveBeenCalledWith(folder);
    });
  });
});

// ─── from OperationFeedback.test.tsx ───
describe('OperationFeedback', () => {
  function state(over: Partial<BulkOperationState> = {}): BulkOperationState {
    return {
      isBusy: false,
      progress: null,
      error: null,
      summary: null,
      collision: null,
      dismissError: vi.fn(),
      dismissSummary: vi.fn(),
      ...over
    };
  }

  describe('OperationFeedback', () => {
    it('reports a clean run with the operation’s own past tense', () => {
      render(
        <OperationFeedback
          op={state({summary: {count: 3, errors: []}})}
          pastVerb="Copied"
          failVerb="copy"
        />
      );
      expect(screen.getByText(/Copied 3 items/i)).toBeInTheDocument();
    });

    it('names each failed item by its LEAF, and maps the error rather than showing raw AWS text', () => {
      render(
        <OperationFeedback
          op={state({
            summary: {
              count: 1,
              errors: [{key: 'alice/reports/q1.csv', message: 'Access Denied', code: 'AccessDenied'}]
            }
          })}
          pastVerb="Moved"
          failVerb="move"
        />
      );

      expect(screen.getByText(/Could not move 1/i)).toBeInTheDocument();
      expect(screen.getByText(/q1\.csv/)).toBeInTheDocument();
      expect(screen.queryByText(/alice\/reports\//)).toBeNull(); // the leaf, not the key
      expect(screen.queryByText(/Access Denied/)).toBeNull(); // SPEC-106: never raw
    });

    it('announces progress with the operation’s present participle', () => {
      // The verb became a prop in this refactor, so a wrong or missing one is exactly the
      // mistake that is now possible and was not before.
      render(
        <OperationFeedback
          op={state({isBusy: true, progress: 42})}
          pastVerb="Moved"
          failVerb="move"
          progressVerb="Moving"
        />
      );
      const status = screen.getByRole('status');
      expect(status).toHaveTextContent('Moving… 42%');
    });

    it('offers the batch overwrite confirmation and reports the choice', async () => {
      const user = userEvent.setup();
      const onOverwriteAll = vi.fn();
      const onCancel = vi.fn();
      render(
        <OperationFeedback
          op={state({collision: {count: 2, onOverwriteAll, onCancel}})}
          pastVerb="Copied"
          failVerb="copy"
        />
      );

      await user.click(screen.getByRole('button', {name: /overwrite/i}));
      expect(onOverwriteAll).toHaveBeenCalledTimes(1);
      expect(onCancel).not.toHaveBeenCalled();
    });

    it('renders its slot between the progress line and the collision prompt', () => {
      // Move's rename prompt lives here, at the position it held before the three stanzas
      // were merged.
      const {container} = render(
        <OperationFeedback
          op={state({isBusy: true, progress: 10, collision: {count: 1, onOverwriteAll: vi.fn(), onCancel: vi.fn()}})}
          pastVerb="Moved"
          failVerb="move"
          progressVerb="Moving">
          <p>rename prompt</p>
        </OperationFeedback>
      );

      const text = Array.from(container.querySelectorAll('*'))
        .map((el) => el.textContent ?? '')
        .join('|');
      expect(text.indexOf('Moving… 10%')).toBeLessThan(text.indexOf('rename prompt'));
      expect(text.indexOf('rename prompt')).toBeLessThan(text.lastIndexOf('Overwrite'));
    });
  });
});

// ─── from ParentFolderRow.test.tsx ───
describe('ParentFolderRow', () => {
  function renderRow(over: {selectable?: boolean; onNavigateUp?: () => void} = {}) {
    const onNavigateUp = over.onNavigateUp ?? vi.fn();
    render(
      <ul>
        <ParentFolderRow
          selectable={over.selectable ?? true}
          onNavigateUp={onNavigateUp}
        />
      </ul>
    );
    return onNavigateUp;
  }

  describe('ParentFolderRow', () => {
    it('renders a `..` row with an accessible "go up" control', () => {
      renderRow();
      const button = screen.getByRole('button', {name: /go up to parent folder/i});
      expect(button).toBeInTheDocument();
      expect(button).toHaveTextContent('..');
    });

    it('navigates up on activation via a native, keyboard-operable button', () => {
      const onNavigateUp = renderRow();
      const button = screen.getByRole('button', {name: /go up to parent folder/i});
      // A native <button> is Enter/Space-activatable and takes tab focus by default.
      expect(button.tagName).toBe('BUTTON');
      fireEvent.click(button);
      expect(onNavigateUp).toHaveBeenCalledTimes(1);
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <ul>
          <ParentFolderRow
            selectable
            onNavigateUp={vi.fn()}
          />
        </ul>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from UploadDropzone.test.tsx ───
describe('UploadDropzone', () => {
  describe('UploadDropzone', () => {
    it('enqueues every file chosen via the picker', async () => {
      const onFiles = vi.fn();
      const {user} = renderWithProviders(<UploadDropzone onFiles={onFiles} />);
      await user.upload(screen.getByLabelText('Choose files'), [new File(['a'], 'a.txt'), new File(['b'], 'b.txt')]);
      expect(onFiles).toHaveBeenCalledTimes(1);
      expect(onFiles.mock.calls[0][0]).toHaveLength(2);
    });

    // Drag-and-drop can't be modelled by userEvent — fireEvent is the right tool here.
    it('enqueues dropped files and tracks drag state', () => {
      const onFiles = vi.fn();
      renderWithProviders(<UploadDropzone onFiles={onFiles} />);
      const zone = screen.getByText('Drag files here').closest('div')!;
      fireEvent.dragOver(zone);
      fireEvent.dragLeave(zone);
      fireEvent.drop(zone, {dataTransfer: {files: [new File(['x'], 'x.txt')]}});
      expect(onFiles).toHaveBeenCalledWith([expect.any(File)]);
    });
  });
});

// ─── from SelectionProvider.test.tsx ───
describe('SelectionProvider', () => {
  const fileA: SelectableItem = {type: 'file', key: 'alice/a.txt'};
  const fileB: SelectableItem = {type: 'file', key: 'alice/b.txt'};
  const folder: SelectableItem = {type: 'folder', prefix: 'alice/docs/'};

  describe('selectionReducer', () => {
    it('toggle adds an unselected item', () => {
      const next = selectionReducer(initialSelectionState, {
        type: 'toggle',
        item: fileA
      });
      expect(next.items.size).toBe(1);
      expect(next.items.get('alice/a.txt')).toEqual(fileA);
    });

    it('selectAll replaces the selection with exactly the given items', () => {
      const withA = selectionReducer(initialSelectionState, {
        type: 'toggle',
        item: fileA
      });
      const all = selectionReducer(withA, {
        type: 'selectAll',
        items: [fileB, folder]
      });
      expect(all.items.size).toBe(2);
      expect(all.items.has('alice/a.txt')).toBe(false); // replaced, not merged
      expect(all.items.has('alice/b.txt')).toBe(true);
      expect(all.items.has('alice/docs/')).toBe(true);
    });
  });

  describe('SelectionProvider', () => {
    function renderSelection(prefix: string) {
      return renderHook(() => useSelection(), {
        wrapper: ({children}: {children: ReactNode}) => (
          <SelectionProvider prefix={prefix}>{children}</SelectionProvider>
        )
      });
    }

    it('exposes selection actions and derived count/isSelected', () => {
      const {result} = renderSelection('alice/');

      act(() => result.current.toggle(fileA));
      expect(result.current.count).toBe(1);
      expect(result.current.isSelected('alice/a.txt')).toBe(true);
      expect(result.current.isSelected('alice/b.txt')).toBe(false);
    });

    it('clears the selection when the prefix changes (navigate-clears)', () => {
      // renderHook's `wrapper` only receives `children`, so we drive the prefix
      // prop through a real render tree and capture the latest context value.
      let latest!: SelectionContextValue;
      function Capture() {
        latest = useSelection();
        return null;
      }
      const harness = (prefix: string) => (
        <SelectionProvider prefix={prefix}>
          <Capture />
        </SelectionProvider>
      );

      const {rerender} = render(harness('alice/'));

      act(() => latest.toggle(fileA));
      expect(latest.count).toBe(1);

      // Navigating into a different folder must drop the prior selection.
      rerender(harness('alice/docs/'));
      expect(latest.count).toBe(0);
    });

    it('throws when useSelection is used outside a provider', () => {
      expect(() => renderHook(() => useSelection())).toThrow(/must be used within a SelectionProvider/);
    });
  });
});
