import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useState} from 'react';
import {render, screen, cleanup, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import type {ReactElement} from 'react';
import {expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';
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

/**
 * Drive the component into the state under test, then hand **that container** to axe.
 *
 * It must be the driven container, not a fresh render of the same element. `open` is internal
 * state initialised `false`, so re-rendering discards it and the `<ul role="listbox">` is never
 * in the tree axe inspects — the open-state cases would silently check the closed state. That is
 * not hypothetical: an `<img>` with no `alt` inside every option passed all four cases before
 * this changed.
 */
async function renderThenAxe(typed: string, expectation: 'options' | 'none'): Promise<void> {
  const {container} = render(<Harness initial={typed} />);
  const user = userEvent.setup();
  if (typed) {
    await user.click(screen.getByRole('combobox'));
    // Retype the last character so the list opens on a real change event.
    await user.keyboard('{Backspace}' + typed.slice(-1));
  }
  if (expectation === 'options') await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  else expect(screen.queryAllByRole('option')).toHaveLength(0);
  await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  cleanup();
}

/** Guards the guard: the open-state cases must actually contain a listbox when axe runs. */
async function expectListboxWasInspected(typed: string): Promise<void> {
  const {container} = render(<Harness initial={typed} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox'));
  await user.keyboard('{Backspace}' + typed.slice(-1));
  await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  expect(container.querySelector('[role="listbox"]')).not.toBeNull();
  cleanup();
}

describe('UsernameCombobox a11y', () => {
  it('has no violations closed', async () => {
    await renderThenAxe('', 'none');
  });

  it('has no violations open with results', async () => {
    await renderThenAxe('ali', 'options');
  });

  it('really did hand axe an open listbox', async () => {
    await expectListboxWasInspected('ali');
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
