import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {MetadataPanel} from './MetadataPanel';
import * as service from './fileBrowser.service';
import {triggerBrowserDownload} from './fileBrowser.download';
import type {ObjectMetadata} from './fileBrowser.types';
import type {S3FileItem} from '../../types/s3.types';

// Integration style (react.md §21): render the REAL MetadataPanel + its real
// useObjectMetadata hook + the shared Drawer, and mock ONLY the AWS boundary —
// getObjectMetadata / getDownloadUrl (partial-mock so the pure helpers stay
// real) and the download side effect. The panel's fetch/loading/error states
// come from the real TanStack Query path against the mocked service.
vi.mock('./fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof service>();
  return {...actual, getObjectMetadata: vi.fn(), getDownloadUrl: vi.fn()};
});
vi.mock('./fileBrowser.download', () => ({triggerBrowserDownload: vi.fn()}));
const mock = vi.mocked(service);

const file: S3FileItem = {
  type: 'file',
  key: 'alice/docs/report.pdf',
  name: 'report.pdf',
  size: 2048,
  lastModified: new Date('2024-03-01T12:00:00Z')
};

const metadata: ObjectMetadata = {
  key: 'alice/docs/report.pdf',
  contentType: 'application/pdf',
  size: 1_468_006,
  lastModified: new Date('2024-03-01T12:00:00Z'),
  etag: '"abc123"',
  storageClass: 'STANDARD',
  userMetadata: {}
};

const ok = <T,>(data: T) => ({success: true as const, data});
const fail = (message: string) => ({success: false as const, error: {message}});

function renderPanel(over: {canModify?: boolean} = {}) {
  const onClose = vi.fn();
  const onRequestRename = vi.fn();
  const result = renderWithProviders(
    <MetadataPanel
      bucket="us"
      file={file}
      rootPrefix="alice/"
      canModify={over.canModify ?? true}
      onRequestRename={onRequestRename}
      onClose={onClose}
    />
  );
  return {...result, onClose, onRequestRename};
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.getObjectMetadata.mockResolvedValue(ok(metadata));
  mock.getDownloadUrl.mockResolvedValue(ok({url: 'https://signed/report.pdf', expiresAt: '2026-01-01T00:00:00Z'}));
});

describe('MetadataPanel', () => {
  it('shows a loading state while the metadata fetch is in flight', () => {
    mock.getObjectMetadata.mockReturnValue(new Promise(() => {})); // never resolves
    renderPanel();
    expect(screen.getByRole('status', {name: /loading details/i})).toBeInTheDocument();
  });

  it('renders the loaded metadata fields with a copyable path and s3:// URI', async () => {
    renderPanel();
    // Type + storage class + ETag (unquoted) once the fetch resolves.
    expect(await screen.findByText('application/pdf')).toBeInTheDocument();
    expect(screen.getByText('STANDARD')).toBeInTheDocument();
    expect(screen.getByText('abc123')).toBeInTheDocument();
    // Path is relative to the user root (username prefix stripped).
    expect(screen.getByText('docs/report.pdf')).toBeInTheDocument();
    // Full cloud path is an s3:// URI, never an ARN.
    expect(screen.getByText('Full Cloud Path')).toBeInTheDocument();
    expect(screen.getByText('s3://us/alice/docs/report.pdf')).toBeInTheDocument();
    expect(screen.queryByText(/^arn:aws:s3/)).not.toBeInTheDocument();
    // Size shown human-readable + exact bytes.
    expect(screen.getByText(/1\.4 MB \(1,468,006 bytes\)/)).toBeInTheDocument();
    // Copy affordances for both path fields.
    expect(screen.getByRole('button', {name: /copy path/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /copy full cloud path/i})).toBeInTheDocument();
  });

  it('renders custom metadata pairs, or an empty state when there are none', async () => {
    mock.getObjectMetadata.mockResolvedValue(ok({...metadata, userMetadata: {author: 'alice', project: 'q1'}}));
    const {unmount} = renderPanel();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.getByText('q1')).toBeInTheDocument();
    expect(screen.queryByText(/no custom metadata/i)).not.toBeInTheDocument();
    unmount();

    mock.getObjectMetadata.mockResolvedValue(ok({...metadata, userMetadata: {}}));
    renderPanel();
    expect(await screen.findByText(/no custom metadata/i)).toBeInTheDocument();
  });

  // A custom metadata key is the user's own string; the labels around it are words this
  // drawer chose. Both halves are asserted in ONE render: an override applied to every
  // DetailField would satisfy the first assertion and is caught only by the second.
  it('shows a custom metadata key as the user typed it, and leaves fixed labels capitalised', async () => {
    mock.getObjectMetadata.mockResolvedValue(ok({...metadata, userMetadata: {reviewedBy: 'alice'}}));
    renderPanel();

    const userKey = await screen.findByText('reviewedBy');
    expect(userKey).toHaveClass('normal-case');

    expect(screen.getByText('Storage class')).not.toHaveClass('normal-case');
  });

  it('renders a fetch error inline as user-safe text, never the raw AWS detail', async () => {
    // SPEC-106: the raw service message is mapped via toUserMessage before rendering,
    // so the raw AWS text (NoSuchKey) never reaches the DOM — an unrecognized message
    // falls back to the generic user-safe wording.
    mock.getObjectMetadata.mockResolvedValue(fail('NoSuchKey: the raw S3 detail'));
    renderPanel();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/couldn.t load details/i);
    expect(alert).toHaveTextContent(/contact the administrator/i);
    expect(alert).not.toHaveTextContent(/NoSuchKey/i);
  });

  it('is a dismissible modal drawer (close button + Escape both fire onClose)', async () => {
    const {user, onClose} = renderPanel();
    const dialog = screen.getByRole('dialog', {name: /details for report\.pdf/i});
    expect(dialog).toHaveAttribute('aria-modal', 'true');

    await user.click(screen.getByRole('button', {name: /close details/i}));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('shows Download always but Rename only when the space is writable', () => {
    const {unmount} = renderPanel({canModify: true});
    expect(screen.getByRole('button', {name: 'Download report.pdf'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Rename report.pdf'})).toBeInTheDocument();
    unmount();

    renderPanel({canModify: false});
    expect(screen.getByRole('button', {name: 'Download report.pdf'})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Rename report.pdf'})).not.toBeInTheDocument();
  });

  it('downloads via a presigned URL (getDownloadUrl → triggerBrowserDownload)', async () => {
    const {user} = renderPanel();
    await user.click(screen.getByRole('button', {name: 'Download report.pdf'}));
    await waitFor(() =>
      expect(mock.getDownloadUrl).toHaveBeenCalledWith({
        bucket: 'us',
        key: 'alice/docs/report.pdf',
        fileName: 'report.pdf'
      })
    );
    expect(triggerBrowserDownload).toHaveBeenCalledWith('https://signed/report.pdf');
  });

  it('surfaces a download failure inline instead of failing silently', async () => {
    mock.getDownloadUrl.mockResolvedValue(fail('gone'));
    const {user} = renderPanel();
    await user.click(screen.getByRole('button', {name: 'Download report.pdf'}));
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText(/could not download report\.pdf/i)).toBeInTheDocument();
    expect(triggerBrowserDownload).not.toHaveBeenCalled();
  });

  it('opens the rename flow via onRequestRename', async () => {
    const {user, onRequestRename} = renderPanel({canModify: true});
    await user.click(screen.getByRole('button', {name: 'Rename report.pdf'}));
    expect(onRequestRename).toHaveBeenCalledWith(file);
  });
});
