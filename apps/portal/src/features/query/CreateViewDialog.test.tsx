import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {CreateViewDialog} from './CreateViewDialog';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CreateViewDialog (SPEC-048 FR-001/002)', () => {
  it('shows the derived target database read-only (SPEC-077 FR-008)', () => {
    render(
      <CreateViewDialog
        targetDatabase="alice"
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText('alice')).toBeInTheDocument();
  });

  it('disables Create until the name passes the catalog-safe rule', () => {
    render(
      <CreateViewDialog
        targetDatabase="alice"
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const create = screen.getByRole('button', {name: 'Create'});
    expect(create).toBeDisabled();

    // Invalid: leading digit.
    fireEvent.change(screen.getByLabelText('View name'), {
      target: {value: '9bad'}
    });
    expect(create).toBeDisabled();
    expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();

    // Valid.
    fireEvent.change(screen.getByLabelText('View name'), {
      target: {value: 'monthly_revenue'}
    });
    expect(create).toBeEnabled();
  });

  it('confirms with the trimmed valid name', () => {
    const onCreate = vi.fn();
    render(
      <CreateViewDialog
        targetDatabase="alice"
        onCreate={onCreate}
        onCancel={vi.fn()}
      />
    );
    fireEvent.change(screen.getByLabelText('View name'), {
      target: {value: '  sales_view  '}
    });
    fireEvent.click(screen.getByRole('button', {name: 'Create'}));
    expect(onCreate).toHaveBeenCalledWith('sales_view');
  });

  it('does not confirm an invalid name on Enter', () => {
    const onCreate = vi.fn();
    render(
      <CreateViewDialog
        targetDatabase="alice"
        onCreate={onCreate}
        onCancel={vi.fn()}
      />
    );
    const input = screen.getByLabelText('View name');
    fireEvent.change(input, {target: {value: 'Bad-Name'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('cancels with no create', () => {
    const onCancel = vi.fn();
    const onCreate = vi.fn();
    render(
      <CreateViewDialog
        targetDatabase="alice"
        onCreate={onCreate}
        onCancel={onCancel}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('locks Create + shows progress while busy', () => {
    render(
      <CreateViewDialog
        targetDatabase="alice"
        busy
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole('button', {name: 'Creating…'})).toBeDisabled();
  });
});
