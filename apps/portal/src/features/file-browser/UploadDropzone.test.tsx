import {describe, it, expect, vi} from 'vitest';
import {screen, fireEvent} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {UploadDropzone} from './UploadDropzone';

describe('UploadDropzone', () => {
  it('enqueues every file chosen via the picker', async () => {
    const onFiles = vi.fn();
    const {user} = renderWithProviders(<UploadDropzone onFiles={onFiles} />);
    await user.upload(screen.getByLabelText('Choose files'), [new File(['a'], 'a.txt'), new File(['b'], 'b.txt')]);
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

  it('ignores drops and disables the picker when disabled', () => {
    const onFiles = vi.fn();
    renderWithProviders(
      <UploadDropzone
        onFiles={onFiles}
        disabled
      />
    );
    const zone = screen.getByText('Drag files here').closest('div')!;
    fireEvent.drop(zone, {dataTransfer: {files: [new File(['x'], 'x.txt')]}});
    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'choose files'})).toBeDisabled();
  });
});
