import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {FolderDetailsPanel} from './FolderDetailsPanel';
import type {S3FolderItem} from '../../types/s3.types';

const folder: S3FolderItem = {
  type: 'folder',
  prefix: 'alice/docs/',
  name: 'docs'
};

function renderPanel(onClose = vi.fn()) {
  render(
    <FolderDetailsPanel
      bucket="my-bucket"
      folder={folder}
      rootPrefix="alice/"
      onClose={onClose}
    />
  );
  return onClose;
}

describe('FolderDetailsPanel', () => {
  it('shows the name, user-relative path, and a Full Cloud Path S3 URI', () => {
    renderPanel();
    // Path is shown relative to the user root (the username prefix is stripped).
    expect(screen.getByText('docs/')).toBeInTheDocument();
    expect(screen.getByText('Full Cloud Path')).toBeInTheDocument();
    expect(screen.getByText('s3://my-bucket/alice/docs/')).toBeInTheDocument();
  });

  it('offers copy buttons for the path and the full cloud path', () => {
    renderPanel();
    expect(screen.getByRole('button', {name: /copy path/i})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /copy full cloud path/i})).toBeInTheDocument();
  });

  it('closes via the close button', () => {
    const onClose = renderPanel();
    fireEvent.click(screen.getByRole('button', {name: /close details/i}));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('is a modal dialog labelled for the folder', () => {
    renderPanel();
    const dialog = screen.getByRole('dialog', {name: /details for docs/i});
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });
});
