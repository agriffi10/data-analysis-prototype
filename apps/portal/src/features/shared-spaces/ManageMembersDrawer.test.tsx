import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, fireEvent, within, waitFor} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {ManageMembersDrawer} from './ManageMembersDrawer';
import {getUserDirectory} from '../user-directory';

// The nested AddMembersDialog now hosts a UsernameChipsField, which reads the published
// directory — so this suite needs the provider stack and the one mocked service boundary.
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUserDirectory).mockResolvedValue({
    success: true,
    data: {usernames: ['cara', 'dave'], generatedAt: null}
  });
});

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
  renderWithProviders(<ManageMembersDrawer {...props} />);
  return props;
}

describe('ManageMembersDrawer (SPEC-053 FR-001/003)', () => {
  it('lists members, marks the owner, and offers no Remove for the owner', () => {
    setup();
    expect(within(screen.getByText('alice').closest('li')!).getByText('Owner')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Remove alice'})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Remove bob'})).toBeInTheDocument();
  });

  it('removing a member confirms, then calls onRemoveMembers with that user', () => {
    const {onRemoveMembers} = setup();
    // Row Remove opens the confirm dialog (no request yet).
    fireEvent.click(screen.getByRole('button', {name: 'Remove bob'}));
    expect(onRemoveMembers).not.toHaveBeenCalled();
    expect(screen.getByText(/lose access to its/)).toBeInTheDocument();
    // The row control and the dialog's confirm no longer share a name, so this is an exact
    // query rather than "the last one" (SPEC-154 FR-006).
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', {name: 'Remove'}));
    expect(onRemoveMembers).toHaveBeenCalledWith(['bob']);
  });

  it('opening Add and submitting calls onAddMembers with the parsed list', async () => {
    const {onAddMembers} = setup();
    fireEvent.click(screen.getByRole('button', {name: 'Add members'}));
    // The field is a chips field since SPEC-148: Enter COMMITS the names, Add then submits.
    // This asserts the CALLBACK argument; the enqueued message is asserted field-by-field in
    // ConnectionsPage.test.tsx, which is where FR-001's payload criterion is really met.
    const field = screen.getByLabelText('Usernames');
    fireEvent.change(field, {target: {value: 'cara dave'}});
    fireEvent.keyDown(field, {key: 'Enter'});
    fireEvent.click(screen.getByRole('button', {name: 'Add'}));
    await waitFor(() => expect(onAddMembers).toHaveBeenCalledWith(['cara', 'dave']));
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

describe('ManageMembersDrawer — the Escape order in the live tree (SPEC-148 FR-006)', () => {
  it('closes the suggestion list, then the dialog, then the drawer', async () => {
    // SPEC-147 FR-004 specifies the mechanism and tests it against a fixture; this verifies it
    // in the REAL composition, where the drawer gates `closeOnEscape` on `!addOpen && !removing`.
    const onClose = vi.fn();
    const {user} = renderWithProviders(
      <ManageMembersDrawer
        open
        onClose={onClose}
        space="salesdata"
        owner="alice"
        members={[{username: 'alice', status: 'active' as const}]}
        onRefresh={vi.fn()}
        onAddMembers={vi.fn()}
        onRemoveMembers={vi.fn()}
      />
    );

    await user.click(screen.getByRole('button', {name: 'Add members'}));
    await user.click(screen.getByRole('combobox', {name: 'Usernames'}));
    await user.keyboard('car');
    await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));

    // 1 — the list only.
    await user.keyboard('{Escape}');
    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByRole('combobox', {name: 'Usernames'})).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    // 2 — the dialog only.
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('combobox', {name: 'Usernames'})).not.toBeInTheDocument());
    expect(onClose).not.toHaveBeenCalled();

    // 3 — the drawer.
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
