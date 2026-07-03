import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {ManageMembersDrawer} from './ManageMembersDrawer';

function setup(overrides: Partial<Parameters<typeof ManageMembersDrawer>[0]> = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    space: 'salesdata',
    owner: 'alice',
    members: [
      {username: 'alice', status: 'active' as const},
      {username: 'bob', status: 'active' as const}
    ],
    onRefresh: vi.fn(),
    onAddMembers: vi.fn(),
    onRemoveMembers: vi.fn(),
    ...overrides
  };
  render(<ManageMembersDrawer {...props} />);
  return props;
}

describe('ManageMembersDrawer (SPEC-053 FR-001/003)', () => {
  it('lists members, marks the owner, and offers no Remove for the owner', () => {
    setup();
    const ownerRow = screen.getByText('alice').closest('li')!;
    expect(within(ownerRow).getByText('Owner')).toBeInTheDocument();
    expect(within(ownerRow).queryByRole('button', {name: 'Remove'})).not.toBeInTheDocument();

    const memberRow = screen.getByText('bob').closest('li')!;
    expect(within(memberRow).getByRole('button', {name: 'Remove'})).toBeInTheDocument();
  });

  it('removing a member confirms, then calls onRemoveMembers with that user', () => {
    const {onRemoveMembers} = setup();
    // Row Remove opens the confirm dialog (no request yet).
    fireEvent.click(screen.getByRole('button', {name: 'Remove'}));
    expect(onRemoveMembers).not.toHaveBeenCalled();
    expect(screen.getByText(/lose access to its/)).toBeInTheDocument();
    // The dialog's confirm is the second "Remove" button; confirm it.
    fireEvent.click(screen.getAllByRole('button', {name: 'Remove'}).at(-1)!);
    expect(onRemoveMembers).toHaveBeenCalledWith(['bob']);
  });

  it('opening Add and submitting calls onAddMembers with the parsed list', () => {
    const {onAddMembers} = setup();
    fireEvent.click(screen.getByRole('button', {name: 'Add members'}));
    fireEvent.change(screen.getByLabelText('Usernames'), {
      target: {value: 'cara dave'}
    });
    fireEvent.click(screen.getByRole('button', {name: 'Add'}));
    expect(onAddMembers).toHaveBeenCalledWith(['cara', 'dave']);
  });

  it('shows an info note when the member projection is unavailable', () => {
    setup({members: [{username: 'alice', status: 'active'}], unavailable: true});
    expect(screen.getByText(/Member details aren.t available yet/)).toBeInTheDocument();
  });

  it('renders a per-member Pending/Active status chip (SPEC-073 FR-004)', () => {
    setup({
      members: [
        {username: 'alice', status: 'active'},
        {username: 'bob', status: 'pending'},
        {username: 'cara', status: 'active'}
      ]
    });
    const bobRow = screen.getByText('bob').closest('li')!;
    expect(within(bobRow).getByText('Pending')).toBeInTheDocument();
    const caraRow = screen.getByText('cara').closest('li')!;
    expect(within(caraRow).getByText('Active')).toBeInTheDocument();
  });

  it('offers a Refresh control that re-reads member state (SPEC-073 FR-006)', () => {
    const {onRefresh} = setup();
    fireEvent.click(screen.getByRole('button', {name: 'Refresh connections'}));
    expect(onRefresh).toHaveBeenCalled();
  });
});
