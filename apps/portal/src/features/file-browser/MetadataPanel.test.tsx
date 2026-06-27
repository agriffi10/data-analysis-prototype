import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MetadataPanel } from './MetadataPanel';
import { useObjectMetadata } from './useObjectMetadata';
import type { UseObjectMetadataResult } from './useObjectMetadata';
import type { ObjectMetadata } from './fileBrowser.types';
import type { S3FileItem } from '../../types/s3.types';

vi.mock('./useObjectMetadata');
const mockUseObjectMetadata = vi.mocked(useObjectMetadata);

const file: S3FileItem = {
  type: 'file',
  key: 'alice/docs/report.pdf',
  name: 'report.pdf',
  size: 2048,
  lastModified: new Date('2024-03-01T12:00:00Z'),
};

const metadata: ObjectMetadata = {
  key: 'alice/docs/report.pdf',
  contentType: 'application/pdf',
  size: 1_468_006,
  lastModified: new Date('2024-03-01T12:00:00Z'),
  etag: '"abc123"',
  storageClass: 'STANDARD',
  userMetadata: {},
};

const loaded = (over: Partial<ObjectMetadata> = {}): UseObjectMetadataResult => ({
  metadata: { ...metadata, ...over },
  isLoading: false,
  error: null,
});

function renderPanel(onClose = vi.fn()) {
  render(<MetadataPanel bucket="us" file={file} rootPrefix="alice/" onClose={onClose} />);
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseObjectMetadata.mockReturnValue(loaded());
});

describe('MetadataPanel', () => {
  it('shows a loading state while fetching', () => {
    mockUseObjectMetadata.mockReturnValue({
      metadata: null,
      isLoading: true,
      error: null,
    });
    renderPanel();
    expect(screen.getByRole('status', { name: /loading details/i })).toBeInTheDocument();
  });

  it('renders the metadata fields when loaded', () => {
    renderPanel();
    expect(screen.getByText('application/pdf')).toBeInTheDocument();
    // Path is shown relative to the user root (the username prefix is stripped).
    expect(screen.getByText('docs/report.pdf')).toBeInTheDocument();
    expect(screen.getByText('STANDARD')).toBeInTheDocument();
    // ETag is shown without its surrounding quotes.
    expect(screen.getByText('abc123')).toBeInTheDocument();
  });

  it('shows the Full Cloud Path as an s3:// URI (not an ARN)', () => {
    renderPanel();
    expect(screen.getByText('Full Cloud Path')).toBeInTheDocument();
    expect(screen.getByText('s3://us/alice/docs/report.pdf')).toBeInTheDocument();
    expect(screen.queryByText(/^arn:aws:s3/)).not.toBeInTheDocument();
  });

  it('offers copy buttons for the path and the full cloud path', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: /copy path/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy full cloud path/i })).toBeInTheDocument();
  });

  it('shows size both human-readable and as exact bytes', () => {
    renderPanel();
    expect(screen.getByText(/1\.4 MB \(1,468,006 bytes\)/)).toBeInTheDocument();
  });

  it('shows a "No custom metadata" empty state when there are no pairs', () => {
    mockUseObjectMetadata.mockReturnValue(loaded({ userMetadata: {} }));
    renderPanel();
    expect(screen.getByText(/no custom metadata/i)).toBeInTheDocument();
  });

  it('lists custom metadata pairs when present', () => {
    mockUseObjectMetadata.mockReturnValue(loaded({ userMetadata: { author: 'alice', project: 'q1' } }));
    renderPanel();
    expect(screen.queryByText(/no custom metadata/i)).not.toBeInTheDocument();
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText('q1')).toBeInTheDocument();
  });

  it('renders a fetch error inline instead of crashing', () => {
    mockUseObjectMetadata.mockReturnValue({
      metadata: null,
      isLoading: false,
      error: 'This file no longer exists.',
    });
    renderPanel();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/couldn.t load details/i);
    expect(alert).toHaveTextContent(/no longer exists/i);
  });

  it('closes via the close button', () => {
    const onClose = renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /close details/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes when Escape is pressed', () => {
    const onClose = renderPanel();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('is a modal dialog (blur backdrop + focus trap via the shared Drawer)', () => {
    renderPanel();
    const dialog = screen.getByRole('dialog', { name: /details for report\.pdf/i });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });
});
