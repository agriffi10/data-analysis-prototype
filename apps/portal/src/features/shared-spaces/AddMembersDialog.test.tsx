import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AddMembersDialog } from './AddMembersDialog';
import { parseMemberInput } from './memberInput';

describe('parseMemberInput (SPEC-053 FR-002)', () => {
  it('splits on commas/whitespace/newlines, trims, lowercases, de-dupes', () => {
    expect(parseMemberInput('Bob, cara\n  bob   DAVE')).toEqual(['bob', 'cara', 'dave']);
  });

  it('drops tokens that fail the catalog-safe username rule', () => {
    // 'x' too short, 'No-Dashes' has a dash, '1leading' starts with a digit.
    expect(parseMemberInput('x, no-dashes, 1leading, validname')).toEqual(['validname']);
  });

  it('returns an empty list for blank input', () => {
    expect(parseMemberInput('   \n  ')).toEqual([]);
  });
});

describe('AddMembersDialog', () => {
  it('sends the parsed list, excluding usernames already in the space', () => {
    const onAdd = vi.fn();
    render(<AddMembersDialog existing={['owner', 'cara']} onAdd={onAdd} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Usernames'), {
      target: { value: 'bob, cara, dave' }, // cara already a member
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(onAdd).toHaveBeenCalledWith(['bob', 'dave']);
  });

  it('disables Add until there is at least one valid new username', () => {
    render(<AddMembersDialog existing={[]} onAdd={vi.fn()} onCancel={vi.fn()} />);
    const add = screen.getByRole('button', { name: 'Add' });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Usernames'), {
      target: { value: 'bob' },
    });
    expect(add).toBeEnabled();
  });

  it('cancels without sending', () => {
    const onCancel = vi.fn();
    render(<AddMembersDialog existing={[]} onAdd={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
