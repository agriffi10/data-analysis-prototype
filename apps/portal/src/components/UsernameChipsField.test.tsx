import {describe, it, expect, vi, beforeEach} from 'vitest';
import {useState} from 'react';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {UsernameChipsField} from './UsernameChipsField';
import {getUserDirectory} from '../features/user-directory';

vi.mock('../features/user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

const DIRECTORY = ['alice', 'alicia', 'bob', 'bob_smith', 'carol'];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUserDirectory).mockResolvedValue({
    success: true,
    data: {usernames: DIRECTORY, generatedAt: '2026-08-05T04:00:11Z'}
  });
});

function Harness({
  initial = [],
  onChangeSpy,
  ...rest
}: {initial?: string[]; onChangeSpy?: (next: string[]) => void} & Partial<
  React.ComponentProps<typeof UsernameChipsField>
>) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <UsernameChipsField
      label="Usernames"
      listLabel="Members to add"
      value={value}
      onChange={(next) => {
        setValue(next);
        onChangeSpy?.(next);
      }}
      {...rest}
    />
  );
}

const field = () => screen.getByRole('combobox', {name: 'Usernames'});
const chips = () => screen.queryByRole('list', {name: 'Members to add'});
const chipNames = () =>
  chips()
    ? within(chips()!)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    : [];

describe('UsernameChipsField — chips', () => {
  it('renders committed names as removable chips', async () => {
    const {user} = renderWithProviders(<Harness />);
    await user.click(field());
    await user.keyboard('carol{Enter}');

    expect(chipNames()).toEqual(['carol']);
    expect(screen.getByRole('button', {name: 'Remove carol'})).toBeInTheDocument();
  });

  it('removes a chip through its remove control', async () => {
    const {user} = renderWithProviders(<Harness initial={['alice', 'bob']} />);

    await user.click(screen.getByRole('button', {name: 'Remove alice'}));

    expect(chipNames()).toEqual(['bob']);
  });

  it('takes a caller-supplied remove label', async () => {
    renderWithProviders(
      <Harness
        initial={['alice']}
        chipRemoveLabel={(name) => `Remove user ${name}`}
      />
    );

    expect(screen.getByRole('button', {name: 'Remove user alice'})).toBeInTheDocument();
  });

  it('ignores a duplicate silently rather than erroring', async () => {
    const {user} = renderWithProviders(<Harness initial={['carol']} />);
    await user.click(field());
    await user.keyboard('carol{Enter}');

    expect(chipNames()).toEqual(['carol']);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('hides already-committed names from the suggestions', async () => {
    const {user} = renderWithProviders(<Harness initial={['alice']} />);
    await user.click(field());
    await user.keyboard('ali');

    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(1));
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['alicia']);
  });

  it('removes the last chip on Backspace in an empty input', async () => {
    const {user} = renderWithProviders(<Harness initial={['alice', 'bob']} />);
    await user.click(field());

    await user.keyboard('{Backspace}');

    expect(chipNames()).toEqual(['alice']);
  });

  it('does NOT remove a chip when Backspace is pressed on a chip remove button', async () => {
    // The handler sits on the wrapper, which contains the chip list too. Ungated, a keyboard
    // user tabbing to "Remove alice" and pressing Backspace deleted the LAST chip instead —
    // silent, wrong, and invisible to axe.
    const {user} = renderWithProviders(<Harness initial={['alice', 'bob', 'carol']} />);

    screen.getByRole('button', {name: 'Remove alice'}).focus();
    await user.keyboard('{Backspace}');

    expect(chipNames()).toEqual(['alice', 'bob', 'carol']);
  });

  it('does NOT remove a chip when Backspace is deleting typed text', async () => {
    const {user} = renderWithProviders(<Harness initial={['alice']} />);
    await user.click(field());
    await user.keyboard('xy{Backspace}');

    expect(chipNames()).toEqual(['alice']);
    expect(field()).toHaveValue('x');
  });
});

describe('UsernameChipsField — renderChips={false}', () => {
  it('renders no internal list, leaving the caller to render committed values', async () => {
    const onChangeSpy = vi.fn();
    const {user} = renderWithProviders(
      <Harness
        renderChips={false}
        onChangeSpy={onChangeSpy}
      />
    );
    await user.click(field());
    await user.keyboard('carol{Enter}');

    expect(onChangeSpy).toHaveBeenCalledWith(['carol']);
    expect(chips()).not.toBeInTheDocument();
  });

  it('does not steal Backspace when the caller owns the list', async () => {
    // Removing from a list this component does not render would be a change behind the
    // caller's back.
    const onChangeSpy = vi.fn();
    const {user} = renderWithProviders(
      <Harness
        initial={['alice']}
        renderChips={false}
        onChangeSpy={onChangeSpy}
      />
    );
    await user.click(field());

    await user.keyboard('{Backspace}');

    expect(onChangeSpy).not.toHaveBeenCalled();
  });
});

describe('UsernameChipsField — paste', () => {
  it('commits the valid tokens and keeps the invalid ones in the input', async () => {
    const {user} = renderWithProviders(<Harness />);
    await user.click(field());

    await user.paste('bob, carol, alice@corp.com');

    expect(chipNames()).toEqual(['bob', 'carol']);
    expect(field()).toHaveValue('alice@corp.com');
    expect(screen.getByRole('alert')).toHaveTextContent('Use 3–63 characters');
  });

  it('handles a paste mixing valid, invalid, duplicate and excluded names', async () => {
    const {user} = renderWithProviders(
      <Harness
        initial={['bob']}
        exclude={new Set(['alice'])}
        excludeReason={(name) => `${name} is already a member.`}
      />
    );
    await user.click(field());

    await user.paste('carol bob alice 9lives');

    // carol committed; bob a silent duplicate; alice refused; 9lives left to fix.
    expect(chipNames()).toEqual(['bob', 'carol']);
    expect(field()).toHaveValue('9lives');
    expect(screen.getByRole('alert')).toHaveTextContent('Use 3–63 characters');
  });

  it('leaves a single-name paste in the input to be edited', async () => {
    const {user} = renderWithProviders(<Harness />);
    await user.click(field());

    await user.paste('carol');

    expect(chipNames()).toEqual([]);
    expect(field()).toHaveValue('carol');
  });
});

describe('UsernameChipsField — exclusions', () => {
  it('refuses an excluded name with the caller-supplied reason', async () => {
    const {user} = renderWithProviders(
      <Harness
        exclude={new Set(['alice'])}
        excludeReason={(name) => `${name} is already a member.`}
      />
    );
    await user.click(field());
    await user.keyboard('alice{Enter}');

    expect(chipNames()).toEqual([]);
    expect(screen.getByRole('alert')).toHaveTextContent('alice is already a member.');
  });

  it('keeps excluded names out of the suggestions', async () => {
    const {user} = renderWithProviders(<Harness exclude={new Set(['alice', 'alicia'])} />);
    await user.click(field());
    await user.keyboard('ali');

    await waitFor(() => expect(field()).toHaveValue('ali'));
    expect(screen.queryAllByRole('option')).toHaveLength(0);
  });
});
