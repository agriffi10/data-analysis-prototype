import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {MembersList} from './MembersList';
import type {Member} from './sharedSpaces.types';

const roster: Member[] = [
  {username: 'cara', status: 'pending'},
  {username: 'alice', status: 'active'},
  {username: 'bob', status: 'active'}
];

describe('MembersList (SPEC-075)', () => {
  it('lists the owner first (tagged), then the rest alphabetical', () => {
    render(
      <MembersList
        owner="alice"
        members={roster}
      />
    );
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => within(li).getAllByText(/alice|bob|cara/)[0].textContent)).toEqual([
      'alice',
      'bob',
      'cara'
    ]);
    const ownerRow = screen.getByText('alice').closest('li')!;
    expect(within(ownerRow).getByText('Owner')).toBeInTheDocument();
  });

  it('renders a per-member status chip and never a chip on the owner', () => {
    render(
      <MembersList
        owner="alice"
        members={roster}
      />
    );
    expect(within(screen.getByText('cara').closest('li')!).getByText('Pending')).toBeInTheDocument();
    expect(within(screen.getByText('bob').closest('li')!).getByText('Active')).toBeInTheDocument();
    // The owner row shows "Owner", not a join-status chip.
    const ownerRow = screen.getByText('alice').closest('li')!;
    expect(within(ownerRow).queryByText('Active')).not.toBeInTheDocument();
  });

  it('is read-only by default — no Remove buttons', () => {
    render(
      <MembersList
        owner="alice"
        members={roster}
      />
    );
    expect(screen.queryByRole('button', {name: /^Remove /})).not.toBeInTheDocument();
  });

  it('renders Remove per non-owner member when onRemove is given, and calls it', () => {
    const onRemove = vi.fn();
    render(
      <MembersList
        owner="alice"
        members={roster}
        onRemove={onRemove}
      />
    );
    // Owner has no Remove. Queried by the member-naming label since SPEC-154 FR-006, which
    // also retires the `.closest('li')` reach this needed to disambiguate identical buttons.
    expect(screen.queryByRole('button', {name: 'Remove alice'})).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: 'Remove bob'}));
    expect(onRemove).toHaveBeenCalledWith('bob');
  });
});
