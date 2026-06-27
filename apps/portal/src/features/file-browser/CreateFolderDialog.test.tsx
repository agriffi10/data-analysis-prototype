import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {CreateFolderDialog} from './CreateFolderDialog';

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

  it('cancels', () => {
    const onCancel = vi.fn();
    render(
      <CreateFolderDialog
        onCreate={vi.fn()}
        onCancel={onCancel}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: /cancel/i}));
    expect(onCancel).toHaveBeenCalled();
  });
});
