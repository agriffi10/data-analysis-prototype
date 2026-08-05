import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useState} from 'react';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {UsernameCombobox} from './UsernameCombobox';
import {Modal} from './Modal';
import {Drawer} from './Drawer';
import {getUserDirectory} from '../features/user-directory';

vi.mock('../features/user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

const DIRECTORY = ['alice', 'alicia', 'bob', 'bob_smith', 'carol'];

const resolved = (usernames: string[] = DIRECTORY) => ({
  success: true as const,
  data: {usernames, generatedAt: '2026-08-05T04:00:11Z'}
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUserDirectory).mockResolvedValue(resolved());
});

/** The component is controlled; every test needs the value wired to state. */
function Harness({
  onCommit = vi.fn(),
  onCommitMany,
  ...rest
}: Partial<React.ComponentProps<typeof UsernameCombobox>> = {}) {
  const [value, setValue] = useState('');
  return (
    <UsernameCombobox
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

  it('announces the result count politely', async () => {
    const {user} = renderWithProviders(<Harness />);
    await typeReady(user, 'ali');

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('2 matches'));
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
   * Mirrors `ManageMembersDrawer`: a Modal inside a Drawer, with the drawer's `closeOnEscape`
   * GATED on the modal being open.
   *
   * The gate is not decoration. Both `Modal` and `Drawer` register **document-level** Escape
   * listeners through `useEscapeKey`, so with a bare Modal inside a bare Drawer one keydown
   * closes both and the stated order is unreachable. The shipped order exists only because
   * `ManageMembersDrawer` passes `closeOnEscape={!addOpen && !removing}` — so a fixture without
   * that gate would fail, and the combobox would get blamed for something it does not control.
   */
  function DrawerFixture({onDrawerClose, onModalClose}: {onDrawerClose: () => void; onModalClose: () => void}) {
    const [modalOpen, setModalOpen] = useState(true);
    return (
      <Drawer
        open
        title="Members"
        onClose={onDrawerClose}
        closeOnEscape={!modalOpen}>
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
