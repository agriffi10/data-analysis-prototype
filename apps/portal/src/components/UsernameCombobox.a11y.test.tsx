import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useState} from 'react';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';
import {AuthContext} from '../features/auth/authContext';
import {authValue} from '../test/authFixtures';
import {UsernameCombobox} from './UsernameCombobox';
import {getUserDirectory} from '../features/user-directory';

vi.mock('../features/user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

// A SHARED client with default gcTime so the directory warmed by the first render is already
// resolved for the render inside `expectNoA11yViolations` — otherwise axe would inspect a
// combobox whose list has not opened yet (the StartQualityCheckDialog.a11y precedent).
const client = new QueryClient({defaultOptions: {queries: {retry: false}}});

function Harness({initial = ''}: {initial?: string}): ReactElement {
  const [value, setValue] = useState(initial);
  return (
    <AuthContext.Provider value={authValue()}>
      <QueryClientProvider client={client}>
        <UsernameCombobox
          label="Usernames"
          value={value}
          onChange={setValue}
          onCommit={() => {}}
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
    data: {usernames: ['alice', 'alicia', 'bob'], generatedAt: '2026-08-05T04:00:11Z'}
  });
});

/** Render, drive to the state under test, unmount — then hand the same tree to axe. */
async function renderThenAxe(typed: string, expectation: 'options' | 'none'): Promise<void> {
  const ui = <Harness initial={typed} />;
  const {container} = render(ui);
  const user = userEvent.setup();
  if (typed) {
    await user.click(screen.getByRole('combobox'));
    // Retype the last character so the list opens on a real change event.
    await user.keyboard('{Backspace}' + typed.slice(-1));
  }
  if (expectation === 'options') await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  else expect(screen.queryAllByRole('option')).toHaveLength(0);
  expect(container).toBeTruthy();
  cleanup();
  await expectNoA11yViolations(ui, COMPONENT_AXE_OPTIONS);
}

describe('UsernameCombobox a11y', () => {
  it('has no violations closed', async () => {
    await renderThenAxe('', 'none');
  });

  it('has no violations open with results', async () => {
    await renderThenAxe('ali', 'options');
  });

  it('has no violations open with no results', async () => {
    await renderThenAxe('zzz', 'none');
  });

  it('has no violations at a phone width', async () => {
    Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});
    try {
      await renderThenAxe('ali', 'options');
    } finally {
      Object.defineProperty(window, 'innerWidth', {value: 1024, writable: true, configurable: true});
    }
  });
});
