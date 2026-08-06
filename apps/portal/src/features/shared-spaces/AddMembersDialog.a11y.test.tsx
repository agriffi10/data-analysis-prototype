import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClientProvider} from '@tanstack/react-query';
import {createTestQueryClient} from '../../test/renderWithProviders';
import type {ReactElement} from 'react';
import {expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {AuthContext} from '../auth/authContext';
import {authValue} from '../../test/authFixtures';
import {AddMembersDialog} from './AddMembersDialog';
import {getUserDirectory} from '../user-directory';

vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

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
  it('has no violations in the empty state', async () => {
    const {container} = render(dialog());
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    cleanup();
  });

  it('has no violations while submitting', async () => {
    const {container} = render(dialog({busy: true}));
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
    cleanup();
  });

  it('has no violations populated with chips', async () => {
    const {container} = render(dialog());
    const user = userEvent.setup();
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('bob, cara{Enter}');
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2));

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
