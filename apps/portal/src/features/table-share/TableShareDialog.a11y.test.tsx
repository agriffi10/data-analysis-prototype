import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {AuthContext} from '../auth/authContext';
import {authValue} from '../../test/authFixtures';
import {TableShareDialog} from './TableShareDialog';
import {getUserDirectory} from '../user-directory';

// The user-kind entry is a UsernameCombobox since SPEC-148, so these checks need the provider
// stack and the mocked directory boundary.
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
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
