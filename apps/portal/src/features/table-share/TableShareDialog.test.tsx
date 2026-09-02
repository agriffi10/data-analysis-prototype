import {beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {TableShareDialog} from './TableShareDialog';
import {getUserDirectory} from '../user-directory';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {connectionKeys} from '../connections/connectionKeys';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
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

// The SPACE entry suggests from the connections cache since SPEC-158, so this suite now mocks a
// second service boundary — and only that one. There is no space-directory document to fetch.
vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

/** A connections cache holding `names` as active shared spaces. */
const spacesCache = (names: string[]) => ({
  success: true as const,
  data: {
    version: 1 as const,
    connections: names.map((name) => ({name, role: 'member' as const, status: 'active' as const}))
  }
});

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
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(spacesCache(['salesteam', 'salesops', 'finance']));
  });

  function renderDialog(
    over: Partial<React.ComponentProps<typeof TableShareDialog>> = {},
    options: Parameters<typeof renderWithProviders>[1] = {}
  ) {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    const rendered = renderWithProviders(
      <TableShareDialog
        source={SOURCE}
        onSubmit={onSubmit}
        onCancel={onCancel}
        {...over}
      />,
      options
    );
    return {onSubmit, onCancel, user: rendered.user};
  }

  // By ROLE, not by label: since SPEC-158 both kinds are a combobox, and its open listbox is
  // labelled `<kind> suggestions` — which a label query matches too.
  const entryInput = () => screen.getByRole('combobox') as HTMLInputElement;
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

    it('Cancel invokes onCancel', async () => {
      const {onCancel, user} = renderDialog();
      await user.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalledTimes(1);
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

    it('never offers USERNAMES under the Shared spaces kind', async () => {
      // The two sources must not bleed: a username is not a share target under this kind.
      const {user} = renderDialog();
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.click(entryInput());
      await user.keyboard('bob');

      expect(screen.queryAllByRole('option')).toHaveLength(0);
    });

    it('does NOT exclude the current user', async () => {
      // Sharing a table into your own database is something the pipeline allows; the field must
      // not invent a restriction the control plane does not have.
      const {user} = renderDialog();
      await user.click(entryInput());
      await user.keyboard('alice{Enter}');

      expect(within(chipList()).getByRole('button', {name: 'Remove user alice'})).toBeInTheDocument();
    });

    it('commits a valid unlisted name with a neutral note when the directory IS ready', async () => {
      const {user} = renderDialog();
      await addRecipients(user, 'someone_new');

      expect(within(chipList()).getByRole('button', {name: 'Remove user someone_new'})).toBeInTheDocument();
      expect(await screen.findByText(/not in the directory/i)).toBeInTheDocument();
      expect(shareButton()).toBeEnabled();
    });
  });

  describe('TableShareDialog — space suggestions (SPEC-158 FR-003)', () => {
    async function spaceKind(user: ReturnType<typeof renderDialog>['user'], typed: string) {
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.click(entryInput());
      await user.keyboard(typed);
    }

    it('suggests the spaces the signed-in user belongs to', async () => {
      const {user} = renderDialog();
      await spaceKind(user, 'sales');

      await waitFor(() =>
        expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['salesops', 'salesteam'])
      );
    });

    it('does NOT suggest the current user’s personal database', async () => {
      // It is not a shared space, and it is already reachable as a USER recipient in this dialog.
      const {user} = renderDialog();
      await spaceKind(user, 'alic');

      expect(screen.queryAllByRole('option')).toHaveLength(0);
    });

    it('commits a space that is not one of yours, with a note that does not call the name wrong', async () => {
      // Sharing to a space you are not a member of is PERMITTED
      // (`test_recipient_space_membership_not_required`), so the note must not read as a refusal.
      const {onSubmit, user} = renderDialog();
      await spaceKind(user, 'someone_elses{Enter}');

      expect(within(chipList()).getByRole('button', {name: 'Remove space someone_elses'})).toBeInTheDocument();
      const note = await screen.findByText(/not one of your shared spaces/i);
      expect(note).toHaveTextContent(/you can still share to a space you are not a member of/i);
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();

      await user.click(shareButton());
      expect(onSubmit).toHaveBeenCalledWith({
        tableName: 'orders',
        recipients: [{kind: 'space', name: 'someone_elses'}]
      });
    });

    it('notes nothing for a space that IS one of yours', async () => {
      const {user} = renderDialog();
      await spaceKind(user, 'finance{Enter}');

      expect(within(chipList()).getByRole('button', {name: 'Remove space finance'})).toBeInTheDocument();
      expect(screen.queryByText(/not one of your shared spaces/i)).not.toBeInTheDocument();
    });

    it('hides a space already listed under the space kind, and keeps the per-kind dedupe', async () => {
      const {user} = renderDialog();
      await spaceKind(user, 'salesteam{Enter}');
      await user.keyboard('sales');

      await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['salesops']));

      await user.clear(entryInput());
      await user.keyboard('salesteam{Enter}');
      expect(within(chipList()).getAllByRole('listitem')).toHaveLength(1);
    });

    it('does not carry a space note over to the user kind', async () => {
      // What `key={kind}` buys. The two kinds used to be different components, which unmounted the
      // note for free; one element keyed on the kind has to be TOLD, and deleting the key leaves
      // "…is not one of your shared spaces…" sitting under the Usernames field, describing a name
      // that is not in it.
      const {user} = renderDialog();
      await spaceKind(user, 'someone_elses{Enter}');
      expect(await screen.findByText(/not one of your shared spaces/i)).toBeInTheDocument();

      await user.click(screen.getByRole('radio', {name: 'Users'}));

      expect(screen.queryByText(/not one of your shared spaces/i)).not.toBeInTheDocument();
    });

    it('keeps the Escape order: the space list first, the dialog second', async () => {
      const {onCancel, user} = renderDialog();
      await spaceKind(user, 'sales');
      await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));

      await user.keyboard('{Escape}');
      expect(screen.queryAllByRole('option')).toHaveLength(0);
      expect(onCancel).not.toHaveBeenCalled();
      expect(entryInput()).toHaveValue('sales');

      await user.keyboard('{Escape}');
      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it('reads a query the app has ALREADY made rather than issuing its own request', async () => {
      // The point of the whole spec: no new AWS call, no published space directory. Seeded with
      // the connections query the Connections page and the Query rail already populate, the
      // dialog suggests without touching the service at all.
      const client = new QueryClient({defaultOptions: {queries: {retry: false, staleTime: Infinity}}});
      client.setQueryData(connectionKeys.list('alice'), spacesCache(['salesteam', 'salesops']).data);
      const {user} = renderDialog({}, {queryClient: client});

      await spaceKind(user, 'sales');

      await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2));
      expect(readSharedConnectionsCache).not.toHaveBeenCalled();
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
    // SPEC-163 gates the recipient-KIND toggle on `sharedWorkspaces`, so the flags have to be
    // in the cache. AFTER `client.clear()`, which would otherwise wipe them — and
    // `setQueryDefaults` first, because the harness client runs `gcTime: 0` and would evict
    // an observer-less seed before the dialog ever mounts.
    client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
    client.setQueryData(featureFlagKeys.resolved(undefined), FEATURE_FLAG_DEFAULTS);
    vi.mocked(getUserDirectory).mockResolvedValue({
      success: true,
      data: {usernames: ['bob', 'bob_smith'], generatedAt: null}
    });
    // Set here rather than inherited from the suite above: `clearAllMocks` clears usage data,
    // not implementations, so an inherited resolved value is an accident waiting to be relied on.
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({
      success: true,
      data: {
        version: 1,
        connections: [
          {name: 'salesteam', role: 'member', status: 'active'},
          {name: 'salesops', role: 'owner', status: 'active'}
        ]
      }
    });
  });

  function dialog(over: Partial<React.ComponentProps<typeof TableShareDialog>> = {}): ReactElement {
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          {/* SPEC-163 gates the recipient-KIND toggle on `sharedWorkspaces`. This file
              drives its own client, so it seeds the flags itself rather than through the
              shared harness. */}
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
    it('has no axe violations with a submit error while busy', async () => {
      const {container} = render(dialog({busy: true, submitError: 'Failed to submit the request'}));
      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no axe violations under the Shared spaces kind, with recipients listed', async () => {
      const {container} = render(dialog());
      const user = userEvent.setup();
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('bob{Enter}');
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.type(screen.getByRole('combobox'), 'salesteam{enter}');
      await waitFor(() => expect(screen.getAllByRole('listitem').length).toBeGreaterThan(1));

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });

    it('has no axe violations with the SPACE suggestion list open', async () => {
      // The space kind's own open state, on the driven container. Without this, the only open
      // listbox axe ever saw was the username one — a different label, a different source, and
      // the case SPEC-158 actually added.
      const {container} = render(dialog());
      const user = userEvent.setup();
      await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('sales');
      await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
      expect(screen.getByRole('listbox')).toHaveAccessibleName('Space names suggestions');

      await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
      cleanup();
    });
  });
});
