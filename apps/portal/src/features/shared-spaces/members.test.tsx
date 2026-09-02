import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {AddMembersDialog} from './AddMembersDialog';
import {parseMemberInput} from './memberInput';
import {getUserDirectory} from '../user-directory';
import {QueryClientProvider} from '@tanstack/react-query';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {AuthContext} from '../auth/authContext';
import {authValue} from '../../test/authFixtures';
import {ManageMembersDrawer} from './ManageMembersDrawer';
import type {ReactElement} from 'react';
import userEvent from '@testing-library/user-event';

// ─── from AddMembersDialog.test.tsx ───
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

describe('AddMembersDialog', () => {
  // The dialog's field is now a `UsernameChipsField`, so this suite renders through the provider
  // stack and mocks the one service boundary it reaches. Every SPEC-053 behaviour below is
  // preserved and updated rather than replaced (SPEC-148 FR-007).

  const DIRECTORY = ['bob', 'cara', 'dave', 'owner'];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUserDirectory).mockResolvedValue({
      success: true,
      data: {usernames: DIRECTORY, generatedAt: '2026-08-05T04:00:11Z'}
    });
  });

  // `parseMemberInput` itself is now pinned directly in memberInput.test.ts; these three cases
  // stay because they are the ones SPEC-053 wrote, and this spec did not intend to change them.
  describe('parseMemberInput (SPEC-053 FR-002)', () => {
    it('splits on commas/whitespace/newlines, trims, lowercases, de-dupes', () => {
      expect(parseMemberInput('Bob, cara\n  bob   DAVE')).toEqual(['bob', 'cara', 'dave']);
    });

    it('returns an empty list for blank input', () => {
      expect(parseMemberInput('   \n  ')).toEqual([]);
    });
  });

  function renderDialog(over: Partial<React.ComponentProps<typeof AddMembersDialog>> = {}) {
    const onAdd = vi.fn();
    const onCancel = vi.fn();
    const {user} = renderWithProviders(
      <AddMembersDialog
        existing={[]}
        onAdd={onAdd}
        onCancel={onCancel}
        {...over}
      />
    );
    return {onAdd, onCancel, user};
  }

  const field = () => screen.getByRole('combobox', {name: 'Usernames'});
  const addButton = () => screen.getByRole('button', {name: /Add|Adding/});
  const chips = () => screen.queryByRole('list', {name: 'Members to add'});

  describe('AddMembersDialog', () => {
    it('sends the parsed list, excluding usernames already in the space', async () => {
      // The `existing` prop already includes the OWNER, and it is passed straight through as the
      // field's `exclude` — a like-for-like translation of the filter the textarea applied, not a
      // new restriction.
      const {onAdd, user} = renderDialog({existing: ['owner', 'cara']});
      await user.click(field());
      await user.keyboard('bob, cara, dave{Enter}');

      await user.click(addButton());

      expect(onAdd).toHaveBeenCalledWith(['bob', 'dave']);
    });

    it('excludes existing members from the suggestions', async () => {
      const {user} = renderDialog({existing: ['bob']});
      await user.click(field());
      await user.keyboard('b');

      await waitFor(() => expect(field()).toHaveValue('b'));
      expect(screen.queryAllByRole('option')).toHaveLength(0);
    });

    it('disables Add until there is at least one valid new username', async () => {
      const {user} = renderDialog();
      expect(addButton()).toBeDisabled();

      await user.click(field());
      await user.keyboard('bob{Enter}');

      expect(addButton()).toBeEnabled();
    });

    it('renders committed names as removable chips', async () => {
      const {user} = renderDialog();
      await user.click(field());
      await user.keyboard('bob, cara{Enter}');

      expect(within(chips()!).getAllByRole('listitem')).toHaveLength(2);
      await user.click(screen.getByRole('button', {name: 'Remove bob'}));
      expect(within(chips()!).getAllByRole('listitem')).toHaveLength(1);
    });

    it('focuses the field on open', () => {
      // `Modal` passes `initialFocus: false` and defers to each consumer's own focus effect, so a
      // field that does not ask for focus leaves it on the trigger OUTSIDE the modal — a screen
      // reader is never moved into the dialog. axe cannot see this; only this test can.
      renderDialog();
      expect(document.activeElement).toBe(field());
    });

    it('handles a mix of valid, invalid, duplicate and excluded names in one entry (FR-003)', async () => {
      // The combination matters: an earlier version reported ONLY the rule sentence whenever
      // there was malformed input, so the excluded name vanished with no chip and no explanation
      // — the exact silent drop this spec exists to remove, one branch deeper.
      const {user} = renderDialog({existing: ['cara']});
      await user.click(field());
      await user.keyboard('bob bob dave cara 1bad{Enter}');

      expect(
        within(chips()!)
          .getAllByRole('listitem')
          .map((li) => li.textContent)
      ).toEqual(['bob', 'dave']);
      expect(field()).toHaveValue('1bad');
      const alert = screen.getByRole('alert');
      expect(alert).toHaveTextContent('Use 3–63 characters');
      expect(alert).toHaveTextContent('cara is already a member of this space.');
    });

    it('no longer claims unknown usernames are ignored', async () => {
      // The copy said "Unknown usernames are ignored." — the same false claim SPEC-146 corrected
      // in two docstrings, and the only place a USER read it.
      renderDialog();
      expect(screen.queryByText(/ignored/i)).not.toBeInTheDocument();
      expect(screen.getByText(/reported back to you as a notification/i)).toBeInTheDocument();
    });

    it('cancels without sending', async () => {
      const {onAdd, onCancel, user} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Cancel'}));

      expect(onCancel).toHaveBeenCalled();
      expect(onAdd).not.toHaveBeenCalled();
    });
  });

  describe('AddMembersDialog — directory states', () => {
    it('commits a valid unlisted name and notes it neutrally when the directory is ready', async () => {
      const {onAdd, user} = renderDialog();
      await user.click(field());
      await user.keyboard('someone_new{Enter}');

      expect(await screen.findByText(/not in the directory/i)).toBeInTheDocument();
      expect(addButton()).toBeEnabled();

      await user.click(addButton());
      expect(onAdd).toHaveBeenCalledWith(['someone_new']);
    });

    it('commits with no note while the directory is still loading', async () => {
      // A note that arrives a second after the name was accepted reads as a delayed rejection.
      let release: (value: unknown) => void = () => {};
      vi.mocked(getUserDirectory).mockReturnValue(
        new Promise((resolve) => {
          release = resolve;
        }) as never
      );
      const {onAdd, user} = renderDialog();
      await user.click(field());
      await user.keyboard('someone_new{Enter}');

      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
      await user.click(addButton());
      expect(onAdd).toHaveBeenCalledWith(['someone_new']);
      release({success: true, data: {usernames: DIRECTORY, generatedAt: null}});
    });
  });
});

// ─── from AddMembersDialog.a11y.test.tsx ───

describe('AddMembersDialog.a11y', () => {
  // Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
  // COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result to
  // hand it. The QueryClient is still the harness's, so retry behaviour cannot drift.
  const client = createTestQueryClient();
  const noop = () => {};

  beforeEach(() => {
    vi.clearAllMocks();
    client.clear();
    vi.mocked(getUserDirectory).mockResolvedValue({
      success: true,
      data: {usernames: ['bob', 'bob_smith', 'cara'], generatedAt: null}
    });
  });

  function dialog(over: Partial<React.ComponentProps<typeof AddMembersDialog>> = {}): ReactElement {
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <AddMembersDialog
            existing={[]}
            onAdd={noop}
            onCancel={noop}
            {...over}
          />
        </QueryClientProvider>
      </AuthContext.Provider>
    );
  }

  describe('AddMembersDialog a11y', () => {
    it('has no violations while submitting', async () => {
      const {container} = render(dialog({busy: true}));
      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no violations with the suggestion list open', async () => {
      // The driven container, not a fresh render — otherwise axe inspects the closed state.
      const {container} = render(dialog());
      const user = userEvent.setup();
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('bob');
      await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    // NOT a responsive check: nothing in this tree reads `window.innerWidth` (the dialog uses no
    // `useBreakpoint`/`matchMedia`, and the combobox reads only `innerHeight`), and jsdom has no
    // layout engine. It is a MANY-CHIPS check, and the narrow viewport is set only so the DOM
    // matches what a phone would render. Real 400px layout is owed as a live browser pass.
    it('has no violations with many chips committed', async () => {
      Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
      try {
        const {container} = render(dialog());
        const user = userEvent.setup();
        await user.click(screen.getByRole('combobox'));
        await user.keyboard('bob, cara, dave, erin{Enter}');
        await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(4));

        await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
        cleanup();
      } finally {
        Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
      }
    });
  });
});

// ─── from ManageMembersDrawer.test.tsx ───

describe('ManageMembersDrawer', () => {
  // The nested AddMembersDialog now hosts a UsernameChipsField, which reads the published
  // directory — so this suite needs the provider stack and the one mocked service boundary.

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
      onTransferOwnership: vi.fn(),
      ...overrides
    };
    const {user} = renderWithProviders(<ManageMembersDrawer {...props} />);
    return {...props, user};
  }

  describe('ManageMembersDrawer (SPEC-053 FR-001/003)', () => {
    it('lists members, marks the owner, and offers no Remove for the owner', () => {
      setup();
      expect(within(screen.getByText('alice').closest('li')!).getByText('Owner')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Remove alice'})).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Remove bob'})).toBeInTheDocument();
    });

    it('removing a member confirms, then calls onRemoveMembers with that user', async () => {
      const {onRemoveMembers, user} = setup();
      // Row Remove opens the confirm dialog (no request yet).
      await user.click(screen.getByRole('button', {name: 'Remove bob'}));
      expect(onRemoveMembers).not.toHaveBeenCalled();
      expect(screen.getByText(/lose access to its/)).toBeInTheDocument();
      // The row control and the dialog's confirm no longer share a name, so this is an exact
      // query rather than "the last one" (SPEC-154 FR-006).
      await user.click(within(screen.getByRole('alertdialog')).getByRole('button', {name: 'Remove'}));
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
      expect(onRefresh).toHaveBeenCalledTimes(1);
    });
  });

  describe('transferring ownership (SPEC-208 FR-006)', () => {
    it('offers a per-member transfer control, named for the member, and none for the owner', () => {
      setup();
      // The visible text repeats on every row, so the accessible name is what tells a
      // screen-reader user which member each control hands the space to.
      expect(screen.getByRole('button', {name: 'Make owner: bob'})).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'Make owner: alice'})).not.toBeInTheDocument();
    });

    it('enqueues exactly one transfer, naming the member, once confirmed', async () => {
      const {onTransferOwnership, user} = setup();

      await user.click(screen.getByRole('button', {name: 'Make owner: bob'}));
      await user.click(screen.getByRole('button', {name: 'Transfer'}));

      expect(onTransferOwnership).toHaveBeenCalledTimes(1);
      expect(onTransferOwnership).toHaveBeenCalledWith('bob');
    });

    it("names the space and the new owner, and says the transfer is not the user's to undo", async () => {
      const {user} = setup();
      await user.click(screen.getByRole('button', {name: 'Make owner: bob'}));

      const dialog = screen.getByRole('alertdialog', {name: 'Transfer ownership of salesdata to bob'});
      expect(within(dialog).getByText(/salesdata/)).toBeInTheDocument();
      expect(within(dialog).getByText(/stay a member/)).toBeInTheDocument();
      expect(within(dialog).getByText(/only bob can transfer it back/)).toBeInTheDocument();
    });

    it('enqueues nothing on cancel and returns focus to the control that opened it', async () => {
      const {onTransferOwnership, user} = setup();
      const opener = screen.getByRole('button', {name: 'Make owner: bob'});

      await user.click(opener);
      await user.click(screen.getByRole('button', {name: 'Cancel'}));

      expect(onTransferOwnership).not.toHaveBeenCalled();
      await waitFor(() => expect(screen.getByRole('button', {name: 'Make owner: bob'})).toHaveFocus());
    });

    it('disables the control while a request is in flight', () => {
      setup({busy: true});
      expect(screen.getByRole('button', {name: 'Make owner: bob'})).toBeDisabled();
    });

    it('has no axe violations with the dialog open', async () => {
      const {user} = setup();
      await user.click(screen.getByRole('button', {name: 'Make owner: bob'}));

      // The DRIVEN container: `expectNoA11yViolations` re-renders from the element and would
      // silently check the closed drawer, where axe never sees the dialog at all.
      await expectContainerHasNoA11yViolations(document.body, COMPONENT_AXE_OPTIONS);
    });
  });
});
