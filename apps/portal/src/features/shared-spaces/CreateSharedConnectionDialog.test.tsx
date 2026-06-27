import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {CreateSharedConnectionDialog} from './CreateSharedConnectionDialog';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CreateSharedConnectionDialog (SPEC-051 FR-001)', () => {
  it('disables Create until the name passes the catalog-safe rule', () => {
    render(
      <CreateSharedConnectionDialog
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const create = screen.getByRole('button', {name: 'Create'});
    expect(create).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: {value: '9bad'} // leading digit
    });
    expect(create).toBeDisabled();
    expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: {value: 'sales_data'}
    });
    expect(create).toBeEnabled();
  });

  it('states the name is permanent and globally unique', () => {
    render(
      <CreateSharedConnectionDialog
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText(/permanent/)).toBeInTheDocument();
    expect(screen.getByText(/globally unique/)).toBeInTheDocument();
  });

  it('confirms with the trimmed valid name', () => {
    const onCreate = vi.fn();
    render(
      <CreateSharedConnectionDialog
        onCreate={onCreate}
        onCancel={vi.fn()}
      />
    );
    fireEvent.change(screen.getByLabelText('Connection name'), {
      target: {value: '  marketing_q2  '}
    });
    fireEvent.click(screen.getByRole('button', {name: 'Create'}));
    expect(onCreate).toHaveBeenCalledWith('marketing_q2');
  });

  it('does not confirm an invalid name on Enter', () => {
    const onCreate = vi.fn();
    render(
      <CreateSharedConnectionDialog
        onCreate={onCreate}
        onCancel={vi.fn()}
      />
    );
    const input = screen.getByLabelText('Connection name');
    fireEvent.change(input, {target: {value: 'Bad-Name'}});
    fireEvent.keyDown(input, {key: 'Enter'});
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('cancels with no create', () => {
    const onCancel = vi.fn();
    const onCreate = vi.fn();
    render(
      <CreateSharedConnectionDialog
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
      <CreateSharedConnectionDialog
        busy
        onCreate={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole('button', {name: 'Creating…'})).toBeDisabled();
  });
});
