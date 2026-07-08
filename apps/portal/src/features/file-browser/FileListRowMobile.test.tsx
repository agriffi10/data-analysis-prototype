import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {FileListRowMobile} from './FileListRowMobile';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import type {S3FileItem, S3FolderItem} from '../../types/s3.types';

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

  it('shows a selection checkbox and reflects the selected treatment', () => {
    const {onToggleSelect} = renderFile({isSelected: true});
    const checkbox = screen.getByRole('checkbox', {name: 'Select report.pdf'});
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    expect(onToggleSelect).toHaveBeenCalledOnce();
    // Selected rows get the accent-soft fill.
    expect(checkbox.closest('li')).toHaveClass('bg-accent-soft');
  });

  it('shows a downloading indicator in place of the size while a download is signing', () => {
    renderFile({isDownloading: true});
    expect(screen.getByLabelText('Downloading')).toBeInTheDocument();
    expect(screen.queryByText('2.0 KB')).not.toBeInTheDocument();
  });

  it('omits the checkbox when not selectable (read-only browse)', () => {
    renderFile({selectable: false});
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    // Download + Details still available in read-only.
    expect(screen.getByRole('button', {name: 'Download report.pdf'})).toBeInTheDocument();
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
