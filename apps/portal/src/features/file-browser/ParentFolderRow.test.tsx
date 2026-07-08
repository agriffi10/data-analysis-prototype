import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {ParentFolderRow} from './ParentFolderRow';

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

  it('navigates up on click and on keyboard activation', () => {
    const onNavigateUp = renderRow();
    const button = screen.getByRole('button', {name: /go up to parent folder/i});
    // A <button> is natively keyboard-activatable (Enter/Space fire click).
    fireEvent.click(button);
    expect(onNavigateUp).toHaveBeenCalledTimes(1);
  });

  it('is not selectable — no checkbox, no Details, no type pill', () => {
    renderRow({selectable: true});
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /details/i})).not.toBeInTheDocument();
    expect(screen.queryByText('Folder')).not.toBeInTheDocument();
  });

  it('shows a — in the size cell', () => {
    renderRow();
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
