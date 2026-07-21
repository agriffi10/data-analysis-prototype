import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {StartQualityCheckDialog} from './StartQualityCheckDialog';
import * as fileBrowserService from '../file-browser/fileBrowser.service';
import type {FileSpaceTarget} from '../file-browser';
import type {FileListPage} from '../../types/s3.types';

// Integration style (react.md §21): the real dialog driving the real DestinationPicker and
// the real useFileBrowser, with only the S3 listing boundary mocked.
vi.mock('../file-browser/fileBrowser.service', async (importActual) => ({
  ...(await importActual<typeof fileBrowserService>()),
  listFiles: vi.fn()
}));
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const mockList = vi.mocked(fileBrowserService.listFiles);

const personal: FileSpaceTarget = {
  id: 'personal',
  bucket: 'user-space',
  rootPrefix: 'alice/',
  kind: 'personal',
  label: 'alice'
};
const shared: FileSpaceTarget = {
  id: 'team-data',
  bucket: 'shared-space',
  rootPrefix: 'team-data/',
  kind: 'shared',
  label: 'team-data'
};

const page = (over: Partial<FileListPage> = {}): FileListPage => ({
  files: [],
  folders: [],
  isTruncated: false,
  ...over
});
const listing = (data: FileListPage) => mockList.mockResolvedValue({success: true, data});

function renderDialog(props?: Partial<React.ComponentProps<typeof StartQualityCheckDialog>>) {
  const onStart = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <StartQualityCheckDialog
      spaces={[personal]}
      onStart={onStart}
      onCancel={onCancel}
      {...props}
    />
  );
  return {...result, onStart, onCancel};
}

beforeEach(() => {
  vi.clearAllMocks();
  listing(page());
});

describe('StartQualityCheckDialog', () => {
  it('carries the read-only reassurance and the background promise', async () => {
    // This is the one place a user decides whether to point a background job at their data.
    // Same promise, same words as the Files-browser confirm (SPEC-113 FR-002).
    renderDialog();
    const dialog = await screen.findByRole('dialog', {name: 'Start a quality check'});
    expect(dialog).toHaveTextContent(/only reads/i);
    expect(dialog).toHaveTextContent(/nothing is modified, moved, or deleted/i);
    expect(dialog).toHaveTextContent(/notification when it finishes/i);
  });

  it('omits the space selector when there is only one space', async () => {
    renderDialog();
    await screen.findByRole('dialog');
    expect(screen.queryByLabelText('Space')).not.toBeInTheDocument();
  });

  it('focuses the space selector when there is one to focus', async () => {
    // Modal defers initial focus to the consumer, and this dialog has no text field to
    // inherit it (the SaveResultsDialog precedent focuses its filename input).
    renderDialog({spaces: [personal, shared]});
    await waitFor(() => expect(screen.getByLabelText('Space')).toHaveFocus());
  });

  it('renders nothing when there are no usable spaces', () => {
    // Only reachable with the bucket env var unset — a personal space always exists.
    const {container} = renderDialog({spaces: []});
    expect(container).toBeEmptyDOMElement();
  });

  it('starts with the space root as the target, so the root is never dead on arrival', async () => {
    listing(page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]}));
    const {user, onStart} = renderDialog();

    // `allowCurrentParent` — without it the picker disables confirm AT the space root.
    const confirm = await screen.findByRole('button', {name: 'Check this folder'});
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    expect(onStart).toHaveBeenCalledWith({
      space: {kind: 'personal', bucket: 'user-space', prefix: 'alice/'},
      location: 'alice/'
    });
  });

  it('enqueues exactly the location it last displayed', async () => {
    listing(
      page({files: [{type: 'file', key: 'alice/report.csv', name: 'report.csv', size: 1, lastModified: new Date(0)}]})
    );
    const {user, onStart} = renderDialog();

    await user.click(await screen.findByRole('button', {name: 'Select file report.csv'}));
    // The target line is the dialog's claim about what is about to happen; the enqueued
    // location is what actually happens. A drift between them is a silent wrong-target.
    // Read by id: the line is deliberately two spans (head-truncation), so no single text
    // node carries the whole location.
    const shown = document.getElementById('dq-start-target')?.textContent;
    expect(shown).toBe('alice/report.csv');
    await user.click(screen.getByRole('button', {name: 'Check this file'}));

    expect(onStart).toHaveBeenCalledWith(expect.objectContaining({location: shown}));
  });

  it('identifies a shared space by its own root prefix, not the browsed folder', async () => {
    listing(page({folders: [{type: 'folder', prefix: 'team-data/raw/', name: 'raw'}]}));
    const {user, onStart} = renderDialog({spaces: [shared]});

    await user.click(await screen.findByRole('button', {name: /open folder raw/i}));
    await user.click(await screen.findByRole('button', {name: 'Check this folder'}));

    expect(onStart).toHaveBeenCalledWith({
      space: {kind: 'shared', bucket: 'shared-space', prefix: 'team-data/'},
      location: 'team-data/raw/'
    });
  });

  it('locks the dialog while a request is in flight', async () => {
    listing(page({folders: [{type: 'folder', prefix: 'alice/sales/', name: 'sales'}]}));
    renderDialog({isPending: true});

    await screen.findByRole('button', {name: /starting…/i});
    expect(screen.getByRole('button', {name: /starting…/i})).toBeDisabled();
    // Not dismissible mid-flight: no orphaned send.
    expect(screen.getByRole('button', {name: /cancel/i})).toBeDisabled();
  });
});
