import {beforeEach, describe, expect, it, vi} from 'vitest';
import {useState} from 'react';
import type {ReactElement} from 'react';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {UsernameCombobox} from './UsernameCombobox';
import {useUsernameSuggestions} from './useUsernameSuggestions';
import type {UsernameSearchResult} from './userDirectory.types';
import {Modal} from '../../components/Modal';
import {Drawer} from '../../components/Drawer';
import {getUserDirectory} from './userDirectory.service';
import {QueryClientProvider} from '@tanstack/react-query';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {AuthContext} from '../auth/authContext';
import {authValue} from '../../test/authFixtures';
import userEvent from '@testing-library/user-event';

// ─── from UsernameCombobox.test.tsx ───
vi.mock('./userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

describe('UsernameCombobox', () => {
  const DIRECTORY = ['alice', 'alicia', 'bob', 'bob_smith', 'carol'];

  const resolved = (usernames: string[] = DIRECTORY) => ({
    success: true as const,
    data: {usernames, generatedAt: '2026-08-05T04:00:11Z'}
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUserDirectory).mockResolvedValue(resolved());
  });

  /**
   * The component is controlled; every test needs the value wired to state.
   *
   * The suggestion source is a PROP since SPEC-158, so the harness supplies it — from
   * `useUsernameSuggestions`, which is what the shipping consumers pass, so the mocked service
   * boundary below still drives every case this suite pinned.
   */
  function Harness({
    onCommit = vi.fn(),
    onCommitMany,
    ...rest
  }: Partial<React.ComponentProps<typeof UsernameCombobox>> = {}) {
    const [value, setValue] = useState('');
    const suggestions = useUsernameSuggestions();
    return (
      <UsernameCombobox
        {...suggestions}
        label="Usernames"
        value={value}
        onChange={setValue}
        onCommit={onCommit}
        onCommitMany={onCommitMany}
        {...rest}
      />
    );
  }

  const field = () => screen.getByRole('combobox', {name: 'Usernames'});
  const options = () => screen.queryAllByRole('option');

  async function typeReady(user: ReturnType<typeof renderWithProviders>['user'], text: string) {
    await user.click(field());
    await user.keyboard(text);
    await waitFor(() => expect(options().length).toBeGreaterThan(0));
  }

  describe('UsernameCombobox — the ARIA pattern', () => {
    it('exposes combobox role, state and the listbox it controls', async () => {
      const {user} = renderWithProviders(<Harness />);
      expect(field()).toHaveAttribute('aria-expanded', 'false');
      expect(field()).toHaveAttribute('aria-autocomplete', 'list');

      await typeReady(user, 'ali');

      expect(field()).toHaveAttribute('aria-expanded', 'true');
      const listbox = screen.getByRole('listbox');
      expect(field()).toHaveAttribute('aria-controls', listbox.id);
      expect(
        within(listbox)
          .getAllByRole('option')
          .map((o) => o.textContent)
      ).toEqual(['alice', 'alicia']);
    });

    it('keeps DOM focus in the input and moves a virtual cursor instead', async () => {
      // The property that makes this a combobox rather than a menu. If focus moved to the
      // option, a screen reader would lose the text the user is typing.
      const {user} = renderWithProviders(<Harness />);
      await typeReady(user, 'ali');

      await user.keyboard('{ArrowDown}');

      expect(document.activeElement).toBe(field());
      expect(field()).toHaveAttribute('aria-activedescendant', options()[0].id);
      expect(options()[0]).toHaveAttribute('aria-selected', 'true');
    });

    it('omits aria-activedescendant entirely when nothing is highlighted', async () => {
      // Absent, not empty: an empty value is a broken reference some readers announce as one.
      const {user} = renderWithProviders(<Harness />);
      await typeReady(user, 'ali');

      expect(field()).not.toHaveAttribute('aria-activedescendant');
    });

    it('wraps the highlight in both directions', async () => {
      const {user} = renderWithProviders(<Harness />);
      await typeReady(user, 'ali');

      await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}');
      expect(field()).toHaveAttribute('aria-activedescendant', options()[0].id);

      await user.keyboard('{ArrowUp}');
      expect(field()).toHaveAttribute('aria-activedescendant', options()[1].id);
    });

    it('jumps to first and last with Home and End', async () => {
      const {user} = renderWithProviders(<Harness />);
      await typeReady(user, 'ali');

      await user.keyboard('{End}');
      expect(field()).toHaveAttribute('aria-activedescendant', options()[1].id);

      await user.keyboard('{Home}');
      expect(field()).toHaveAttribute('aria-activedescendant', options()[0].id);
    });

    it('never points aria-activedescendant at an option that is gone', async () => {
      // `suggestions` can shrink for a reason the input never sees — a caller changing `exclude`,
      // which is exactly what SPEC-148 does with a refetchable member list. Before the clamp, the
      // input kept pointing at option 3 of a list that now had two, no option reported itself
      // active, and Enter committed the raw typed text instead of the announced option.
      // Driven through `rerender` rather than an in-page button: clicking anything outside the
      // wrapper closes the list, which would make the assertion vacuous.
      const onCommit = vi.fn();
      const {user, rerender} = renderWithProviders(<Harness onCommit={onCommit} />);
      await typeReady(user, 'ali');
      await user.keyboard('{ArrowDown}{ArrowDown}');
      expect(field()).toHaveAttribute('aria-activedescendant', options()[1].id);

      rerender(
        <Harness
          onCommit={onCommit}
          exclude={new Set(['alicia'])}
        />
      );

      expect(options()).toHaveLength(1);
      const active = field().getAttribute('aria-activedescendant');
      expect(active === null || document.getElementById(active)).toBeTruthy();

      // And Enter commits the visible option rather than falling through to the typed text.
      await user.keyboard('{ArrowDown}{Enter}');
      expect(onCommit).toHaveBeenCalledWith('alice');
    });

    it('announces "No matches" when a ready directory has none', async () => {
      const {user} = renderWithProviders(<Harness />);
      await user.click(field());
      await user.keyboard('zzz');

      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('No matches'));
    });

    it('announces the result count politely', async () => {
      const {user} = renderWithProviders(<Harness />);
      await typeReady(user, 'ali');

      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('2 matches'));
    });
  });

  describe('UsernameCombobox — the source is a prop (SPEC-158 FR-001)', () => {
    /**
     * Rendered with a PLAIN STUB and NO providers — no QueryClient, no AuthProvider, no mocked
     * service. That is the whole claim of the prop lift: the component is source-agnostic, and it
     * would fail here the moment it reached for a hook of its own.
     */
    function StubHarness({search}: {search: (query: string, limit?: number) => UsernameSearchResult[]}) {
      const [value, setValue] = useState('');
      return (
        <UsernameCombobox
          status="ready"
          search={search}
          label="Names"
          value={value}
          onChange={setValue}
          onCommit={() => {}}
        />
      );
    }

    it('suggests from a plain stub, with no provider beyond its own chrome', async () => {
      const search = vi.fn((query: string): UsernameSearchResult[] => [{username: `${query}team`, match: 'prefix'}]);
      render(<StubHarness search={search} />);
      const user = userEvent.setup();

      await user.click(screen.getByRole('combobox', {name: 'Names'}));
      await user.keyboard('sales');

      await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['salesteam']));
      expect(search).toHaveBeenCalled();
      cleanup();
    });

    it('renders the caller’s unlisted-name wording instead of the directory sentence', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(
        <Harness
          onCommit={onCommit}
          unlistedNote={(names) => `${names.join(', ')} may exist and simply not be one of yours.`}
        />
      );
      await user.click(field());
      await user.keyboard('newthing{Enter}');

      expect(onCommit).toHaveBeenCalledWith('newthing');
      expect(await screen.findByText(/may exist and simply not be one of yours/)).toBeInTheDocument();
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
    });
  });

  describe('UsernameCombobox — committing', () => {
    it('commits the highlighted option on Enter', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await typeReady(user, 'ali');

      await user.keyboard('{ArrowDown}{Enter}');

      expect(onCommit).toHaveBeenCalledWith('alice');
      expect(field()).toHaveValue('');
    });

    it('commits the typed text when nothing is highlighted', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await user.click(field());
      await user.keyboard('carol{Enter}');

      expect(onCommit).toHaveBeenCalledWith('carol');
    });

    it('commits every valid token of a multi-token entry through onCommitMany', async () => {
      // TableShareDialog's user entry is a BULK field today (`e.g. bob, cara`); a single-value
      // combobox would silently remove that shipped capability.
      const onCommitMany = vi.fn();
      const {user} = renderWithProviders(<Harness onCommitMany={onCommitMany} />);
      await user.click(field());
      await user.keyboard('bob, carol{Enter}');

      expect(onCommitMany).toHaveBeenCalledWith(['bob', 'carol']);
    });

    it('commits only the first token when the consumer omits onCommitMany', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await user.click(field());
      await user.keyboard('bob, carol{Enter}');

      expect(onCommit).toHaveBeenCalledTimes(1);
      expect(onCommit).toHaveBeenCalledWith('bob');
    });

    it('leaves invalid tokens in the input with the standard rule sentence', async () => {
      // `alice@corp.com` and `9lives` genuinely fail the rule. Note that a token like `Bad` does
      // NOT — it lowercases to `bad`, which is catalog-safe — so a test written with those would
      // pass while asserting nothing.
      const onCommitMany = vi.fn();
      const {user} = renderWithProviders(<Harness onCommitMany={onCommitMany} />);
      await user.click(field());
      await user.keyboard('bob alice@corp.com 9lives{Enter}');

      expect(onCommitMany).toHaveBeenCalledWith(['bob']);
      expect(field()).toHaveValue('alice@corp.com 9lives');
      expect(screen.getByRole('alert')).toHaveTextContent('Use 3–63 characters');
    });

    it('commits an option on click', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await typeReady(user, 'bob');

      await user.click(screen.getByRole('option', {name: 'bob_smith'}));

      expect(onCommit).toHaveBeenCalledWith('bob_smith');
    });

    it('closes the list on an outside click', async () => {
      const {user} = renderWithProviders(
        <div>
          <Harness />
          <button type="button">elsewhere</button>
        </div>
      );
      await typeReady(user, 'ali');

      await user.click(screen.getByRole('button', {name: 'elsewhere'}));

      await waitFor(() => expect(options()).toHaveLength(0));
    });

    it('closes the list on Tab and commits nothing, keeping the typed text', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await typeReady(user, 'ali');

      await user.tab();

      expect(onCommit).not.toHaveBeenCalled();
      expect(field()).toHaveValue('ali');
      expect(options()).toHaveLength(0);
    });

    it('filters excluded names out of the suggestions and refuses them on commit', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(
        <Harness
          onCommit={onCommit}
          exclude={new Set(['alice'])}
          excludeReason={(name) => `${name} is already a member.`}
        />
      );
      await typeReady(user, 'ali');

      expect(options().map((o) => o.textContent)).toEqual(['alicia']);

      await user.clear(field());
      await user.keyboard('alice{Enter}');

      expect(onCommit).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent('alice is already a member.');
    });
  });

  describe('UsernameCombobox — an unlisted name is always accepted (FR-005)', () => {
    it('commits a valid unlisted name and notes it neutrally when the directory is ready', async () => {
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await user.click(field());
      await user.keyboard('newperson{Enter}');

      expect(onCommit).toHaveBeenCalledWith('newperson');
      const note = await screen.findByText(/not in the directory/i);
      // Neutral, not an error: `role="alert"` is the error channel and must stay empty here.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(note).toBeInTheDocument();
    });

    it('commits an unlisted name with NO note while the directory is loading', async () => {
      // A note arriving a second after the name was accepted reads as a delayed rejection.
      let release: (value: unknown) => void = () => {};
      vi.mocked(getUserDirectory).mockReturnValue(
        new Promise((resolve) => {
          release = resolve;
        }) as never
      );
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await user.click(field());
      await user.keyboard('newperson{Enter}');

      expect(onCommit).toHaveBeenCalledWith('newperson');
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
      release(resolved());
    });

    it('commits an unlisted name with NO note and no suggestions when the directory is unavailable', async () => {
      // Telling a user their colleague "was not found" because a background fetch failed is
      // worse than saying nothing.
      vi.mocked(getUserDirectory).mockResolvedValue({success: false, error: {message: 'boom'}});
      const onCommit = vi.fn();
      const {user} = renderWithProviders(<Harness onCommit={onCommit} />);
      await user.click(field());
      await user.keyboard('alice{Enter}');

      await waitFor(() => expect(onCommit).toHaveBeenCalledWith('alice'));
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
      expect(options()).toHaveLength(0);
    });

    it('does not note a name that IS in the directory', async () => {
      const {user} = renderWithProviders(<Harness />);
      await user.click(field());
      await user.keyboard('carol{Enter}');

      await waitFor(() => expect(field()).toHaveValue(''));
      expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
    });
  });

  describe('UsernameCombobox — Escape in the real composition', () => {
    /**
     * Mirrors `ManageMembersDrawer`: a Modal inside a Drawer, exactly as it ships — no
     * `closeOnEscape` gate, because since SPEC-155 FR-006 `useEscapeKey` dispatches by
     * TREE DEPTH, so the nested modal owns Escape and the drawer stays put.
     *
     * That layering is not decoration for this test: both `Modal` and `Drawer` register
     * document-level Escape listeners, and if the wrong one won, one keydown would close
     * both and the combobox would get blamed for something it does not control.
     */
    function DrawerFixture({onDrawerClose, onModalClose}: {onDrawerClose: () => void; onModalClose: () => void}) {
      const [modalOpen, setModalOpen] = useState(true);
      return (
        <Drawer
          open
          title="Members"
          onClose={onDrawerClose}>
          {modalOpen && (
            <Modal
              ariaLabel="Add members"
              onDismiss={() => {
                setModalOpen(false);
                onModalClose();
              }}>
              <Harness />
            </Modal>
          )}
        </Drawer>
      );
    }

    it('closes the list, then the dialog, then the drawer — one Escape each', async () => {
      const onDrawerClose = vi.fn();
      const onModalClose = vi.fn();
      const {user} = renderWithProviders(
        <DrawerFixture
          onDrawerClose={onDrawerClose}
          onModalClose={onModalClose}
        />
      );
      await typeReady(user, 'ali');

      await user.keyboard('{Escape}');
      expect(options()).toHaveLength(0);
      expect(onModalClose).not.toHaveBeenCalled();
      expect(onDrawerClose).not.toHaveBeenCalled();

      await user.keyboard('{Escape}');
      expect(onModalClose).toHaveBeenCalledTimes(1);
      expect(onDrawerClose).not.toHaveBeenCalled();

      await user.keyboard('{Escape}');
      expect(onDrawerClose).toHaveBeenCalledTimes(1);
    });

    it('does not clear the input when Escape closes the list', async () => {
      const {user} = renderWithProviders(
        <DrawerFixture
          onDrawerClose={vi.fn()}
          onModalClose={vi.fn()}
        />
      );
      await typeReady(user, 'ali');

      await user.keyboard('{Escape}');

      expect(field()).toHaveValue('ali');
    });

    it('leaves Escape alone when the list is closed', async () => {
      // Not intercepted at all, so the enclosing surface dismisses normally.
      const onModalClose = vi.fn();
      const {user} = renderWithProviders(
        <DrawerFixture
          onDrawerClose={vi.fn()}
          onModalClose={onModalClose}
        />
      );
      await user.click(field());

      await user.keyboard('{Escape}');

      expect(onModalClose).toHaveBeenCalledTimes(1);
    });
  });
});

// ─── from UsernameCombobox.a11y.test.tsx ───

describe('UsernameCombobox.a11y', () => {
  // A SHARED client with default gcTime so the directory warmed by the first render is already
  // resolved for the render inside `expectNoA11yViolations` — otherwise axe would inspect a
  // combobox whose list has not opened yet (the StartQualityCheckDialog.a11y precedent).
  // Bespoke tree, kept deliberately (SPEC-154 FR-007): `expectNoA11yViolations` takes a
  // COMPOSED ELEMENT and renders it itself, so there is no `renderWithProviders` result to
  // hand it. The QueryClient is still the harness's, so retry behaviour cannot drift.
  const client = createTestQueryClient();

  function Field({initial}: {initial: string}): ReactElement {
    const [value, setValue] = useState(initial);
    return (
      <UsernameCombobox
        {...useUsernameSuggestions()}
        label="Usernames"
        value={value}
        onChange={setValue}
        onCommit={() => {}}
      />
    );
  }

  function Harness({initial = ''}: {initial?: string}): ReactElement {
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <Field initial={initial} />
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
});
