import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {TableShareDialog} from './TableShareDialog';
import {getUserDirectory} from '../user-directory';
import {QueryClientProvider} from '@tanstack/react-query';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {AuthContext} from '../auth/authContext';
import {authValue} from '../../test/authFixtures';
import type {ReactElement} from 'react';
import userEvent from '@testing-library/user-event';

// ─── from TableShareDialog.test.tsx ───
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

describe('TableShareDialog', () => {
  // The user-kind entry is now a `UsernameCombobox`, so this suite renders through the provider
  // stack and mocks the ONE service boundary the field reaches (SPEC-148). Every behaviour the
  // SPEC-093 suite pinned is preserved below, updated rather than replaced — a case this spec did
  // not intend to change should fail loudly.

  const SOURCE = {database: 'alice', table: 'orders'};

  const directory = (usernames: string[] = ['bob', 'bob_smith', 'cara', 'alice']) => ({
    success: true as const,
    data: {usernames, generatedAt: '2026-08-05T04:00:11Z'}
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUserDirectory).mockResolvedValue(directory());
  });

  function renderDialog(over: Partial<React.ComponentProps<typeof TableShareDialog>> = {}) {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    const rendered = renderWithProviders(
      <TableShareDialog
        source={SOURCE}
        onSubmit={onSubmit}
        onCancel={onCancel}
        {...over}
      />
    );
    return {onSubmit, onCancel, user: rendered.user};
  }

  const entryInput = () => screen.getByLabelText(/Usernames|Space names/) as HTMLInputElement;
  const addButton = () => screen.getByRole('button', {name: 'Add'});
  const shareButton = () => screen.getByRole('button', {name: /Share|Submitting/});
  const chipList = () => screen.getByRole('list', {name: 'Recipients'});

  async function addRecipients(user: ReturnType<typeof renderDialog>['user'], raw: string) {
    await user.click(entryInput());
    await user.keyboard(raw);
    await user.click(addButton());
  }

  describe('TableShareDialog', () => {
    it('shows the fully-qualified source read-only and defaults the result name to the source table', () => {
      renderDialog();
      expect(screen.getByText('alice.orders')).toBeInTheDocument();
      expect(screen.getByLabelText('Table name for recipients')).toHaveValue('orders');
    });

    it('adds comma/space-separated names as removable chips tagged with the selected kind', async () => {
      // THE USER ENTRY IS STILL A BULK FIELD. `bob, cara` in one go must still produce two chips —
      // that is what `onCommitMany` is for, and losing it would be a silent regression.
      const {user} = renderDialog();
      await addRecipients(user, 'bob, cara');

      expect(within(chipList()).getAllByRole('listitem')).toHaveLength(2);
      expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
      // The entry box clears after an add.
      expect(entryInput()).toHaveValue('');

      await user.click(within(chipList()).getByRole('button', {name: 'Remove user bob'}));
      expect(within(chipList()).queryByRole('button', {name: 'Remove user bob'})).not.toBeInTheDocument();
      expect(within(chipList()).getByRole('button', {name: 'Remove user cara'})).toBeInTheDocument();
    });

    it('tags entries added under "Shared spaces" as spaces (a mixed list is allowed)', async () => {
      const {user} = renderDialog();
      await addRecipients(user, 'bob');
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await addRecipients(user, 'salesteam');

      expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
      expect(within(chipList()).getByRole('button', {name: 'Remove space salesteam'})).toBeInTheDocument();
    });

    it('keeps committed recipients of both kinds when the toggle is switched', async () => {
      const {user} = renderDialog();
      await addRecipients(user, 'bob');
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await addRecipients(user, 'salesteam');
      await user.click(screen.getByRole('radio', {name: 'Users'}));

      expect(within(chipList()).getAllByRole('listitem')).toHaveLength(2);
    });

    it('Enter in the recipient input adds names instead of submitting', async () => {
      const {onSubmit, user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('bob{Enter}');

      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    });

    it('dedupes an already-added name of the same kind', async () => {
      const {user} = renderDialog();
      await addRecipients(user, 'bob');
      await addRecipients(user, 'bob');

      expect(within(chipList()).getAllByRole('listitem')).toHaveLength(1);
    });

    it('SURFACES malformed tokens rather than dropping them (SPEC-148 FR-003)', async () => {
      // A deliberate behaviour change from SPEC-093, where `parseMemberInput` dropped them without
      // comment and the user watched half their entry disappear.
      const {user} = renderDialog();
      await addRecipients(user, 'bob 1bad -x');

      expect(within(chipList()).getAllByRole('listitem')).toHaveLength(1);
      expect(entryInput()).toHaveValue('1bad -x');
      expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();
    });

    it('keeps Add enabled for a wholly-invalid user entry, so clicking it explains the problem', async () => {
      // Under the SPACE kind, Add is gated on a pre-parse and goes disabled — correct there,
      // because nothing would happen. Under the USER kind the combobox owns the parse, so Add
      // stays live and clicking it surfaces the rule rather than leaving a dead button with no
      // explanation. Reverting to the pre-spec `pendingNames.length === 0` gate breaks this.
      const {user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('Bad-Name');
      expect(addButton()).toBeEnabled();

      await user.click(addButton());
      expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();

      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      expect(addButton()).toBeDisabled();
    });

    it('returns focus to the entry after Add, for both kinds', async () => {
      const {user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('bob');
      await user.click(addButton());

      expect(document.activeElement).toBe(entryInput());
    });

    it('disables Share until there is at least one recipient and a valid name', async () => {
      const {onSubmit, user} = renderDialog();
      expect(shareButton()).toBeDisabled();

      await addRecipients(user, 'bob');
      expect(shareButton()).toBeEnabled();

      const nameInput = screen.getByLabelText('Table name for recipients');
      await user.clear(nameInput);
      await user.type(nameInput, 'Bad-Name');
      expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();
      expect(shareButton()).toBeDisabled();

      await user.clear(nameInput);
      await user.type(nameInput, 'orders_copy');
      await user.click(shareButton());

      // FIELD-BY-FIELD, the same payload SPEC-093 sent for the same recipients.
      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'orders_copy',
        recipients: [{kind: 'user', name: 'bob'}]
      });
    });

    it('locks the form while busy and surfaces a submit error inline', () => {
      renderDialog({busy: true, submitError: 'Failed to submit the request'});
      expect(screen.getByRole('button', {name: 'Submitting…'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
      expect(entryInput()).toBeDisabled();
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to submit the request');
    });

    it('Cancel invokes onCancel', async () => {
      const {onCancel, user} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
    });
  });

  describe('TableShareDialog — suggestions', () => {
    it('suggests usernames under the Users kind', async () => {
      const {user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('bob');

      await waitFor(() =>
        expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['bob', 'bob_smith'])
      );
    });

    it('offers NO suggestions under the Shared spaces kind', async () => {
      // Space names are not in the user directory; offering usernames here would be actively wrong.
      const {user} = renderDialog();
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.click(entryInput());
      await user.keyboard('bob');

      expect(screen.queryAllByRole('option')).toHaveLength(0);
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    });

    it('does NOT exclude the current user', async () => {
      // Sharing a table into your own database is something the pipeline allows; the field must
      // not invent a restriction the control plane does not have.
      const {user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('alice{Enter}');

      expect(within(chipList()).getByRole('button', {name: 'Remove user alice'})).toBeInTheDocument();
    });

    it('stays fully usable when the directory is unavailable', async () => {
      vi.mocked(getUserDirectory).mockResolvedValue({success: false, error: {message: 'boom'}});
      const {onSubmit, user} = renderDialog();

      await addRecipients(user, 'someone_new');
      await user.click(shareButton());

      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'orders',
        recipients: [{kind: 'user', name: 'someone_new'}]
      });
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
    });

    it('commits a valid unlisted name with a neutral note when the directory IS ready', async () => {
      const {user} = renderDialog();
      await addRecipients(user, 'someone_new');

      expect(within(chipList()).getByRole('button', {name: 'Remove user someone_new'})).toBeInTheDocument();
      expect(await screen.findByText(/not in the directory/i)).toBeInTheDocument();
      expect(shareButton()).toBeEnabled();
    });
  });
});

// ─── from TableShareDialog.a11y.test.tsx ───

describe('TableShareDialog.a11y', () => {
  // The user-kind entry is a UsernameCombobox since SPEC-148, so these checks need the provider
  // stack and the mocked directory boundary.

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
      data: {usernames: ['bob', 'bob_smith'], generatedAt: null}
    });
  });

  function dialog(over: Partial<React.ComponentProps<typeof TableShareDialog>> = {}): ReactElement {
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <TableShareDialog
            source={{database: 'alice', table: 'orders'}}
            onSubmit={noop}
            onCancel={noop}
            {...over}
          />
        </QueryClientProvider>
      </AuthContext.Provider>
    );
  }

  describe('TableShareDialog a11y', () => {
    it('has no axe violations in the default state', async () => {
      const {container} = render(dialog());
      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no axe violations with a submit error while busy', async () => {
      const {container} = render(dialog({busy: true, submitError: 'Failed to submit the request'}));
      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no axe violations with the suggestion list open', async () => {
      // Checked on the DRIVEN container, not a fresh render: `open` is internal state, so
      // re-rendering the element would silently hand axe the closed state instead.
      const {container} = render(dialog());
      const user = userEvent.setup();
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('bob');
      await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no axe violations under the Shared spaces kind, with recipients listed', async () => {
      const {container} = render(dialog());
      const user = userEvent.setup();
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('bob{Enter}');
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.type(screen.getByLabelText('Space names'), 'salesteam{enter}');
      await waitFor(() => expect(screen.getAllByRole('listitem').length).toBeGreaterThan(1));

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });
  });
});
