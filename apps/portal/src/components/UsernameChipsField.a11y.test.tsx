import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useState} from 'react';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';
import {AuthContext} from '../features/auth/authContext';
import {authValue} from '../test/authFixtures';
import {UsernameChipsField} from './UsernameChipsField';
import {getUserDirectory} from '../features/user-directory';

vi.mock('../features/user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

// Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
// COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result to
// hand it. The client is bespoke too, and that is load-bearing: the pattern below warms
// the cache in one render and reuses it in the next, which `createTestQueryClient`'s
// `gcTime: 0` would defeat — axe would then inspect a loading state and pass vacuously.
const client = new QueryClient({defaultOptions: {queries: {retry: false}}});

function Harness({initial, renderChips = true}: {initial: string[]; renderChips?: boolean}): ReactElement {
  const [value, setValue] = useState(initial);
  return (
    <AuthContext.Provider value={authValue()}>
      <QueryClientProvider client={client}>
        <UsernameChipsField
          label="Usernames"
          listLabel="Members to add"
          value={value}
          onChange={setValue}
          renderChips={renderChips}
        />
      </QueryClientProvider>
    </AuthContext.Provider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  client.clear();
  vi.mocked(getUserDirectory).mockResolvedValue({
    success: true,
    data: {usernames: ['alice', 'bob'], generatedAt: '2026-08-05T04:00:11Z'}
  });
});

async function renderThenAxe(ui: ReactElement, expectChips: number): Promise<void> {
  render(ui);
  if (expectChips > 0) await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(expectChips));
  cleanup();
  await expectNoA11yViolations(ui, COMPONENT_AXE_OPTIONS);
}

describe('UsernameChipsField a11y', () => {
  it('has no violations with zero chips', async () => {
    await renderThenAxe(<Harness initial={[]} />, 0);
  });

  it('has no violations with one chip', async () => {
    await renderThenAxe(<Harness initial={['alice']} />, 1);
  });

  it('has no violations with many chips', async () => {
    await renderThenAxe(<Harness initial={['alice', 'bob', 'carol', 'dan']} />, 4);
  });

  it('has no violations in renderChips={false} mode', async () => {
    await renderThenAxe(
      <Harness
        initial={['alice', 'bob']}
        renderChips={false}
      />,
      0
    );
  });

  it('has no violations at a phone width', async () => {
    Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
    try {
      await renderThenAxe(<Harness initial={['alice', 'bob']} />, 2);
    } finally {
      Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
    }
  });
});
