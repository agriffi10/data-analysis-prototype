import {render, screen, fireEvent} from '@testing-library/react';
import {describe, it, expect, vi} from 'vitest';
import {ParentFolderRow} from './ParentFolderRow';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';

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
