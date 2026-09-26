import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {ClearQueryDialog} from './ClearQueryDialog';

describe('ClearQueryDialog', () => {
  it('never claims the clear cannot be undone, since Ctrl/Cmd+Z brings the SQL back', () => {
    renderWithProviders(
      <ClearQueryDialog
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/This empties the editor/)).not.toHaveTextContent(/unlinks/);
    expect(screen.queryByText(/can’t be undone/)).not.toBeInTheDocument();
  });

  it('says a linked tab loses its link, the one part undo does not restore', () => {
    renderWithProviders(
      <ClearQueryDialog
        linkedName="Monthly"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/This empties the editor/)).toHaveTextContent(
      'It also unlinks this tab from “Monthly”, which stays saved.'
    );
  });
});
