import {useState} from 'react';
import {describe, expect, it} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from '../test/renderWithProviders';
import {politeAnnouncements} from '../test/liveRegions';
import {Input} from './Input';

const NO_SLASH = 'Use no “/”.';

/** A name field validated as you type, beside a button that refuses the name the way a server would. */
function NameForm() {
  const [name, setName] = useState('');
  const [taken, setTaken] = useState(false);
  const error = taken ? 'That name is taken.' : name.includes('/') ? NO_SLASH : null;
  return (
    <>
      <Input
        label="Name"
        value={name}
        error={error}
        onChange={(e) => {
          setTaken(false);
          setName(e.target.value);
        }}
      />
      <button
        type="button"
        onClick={() => setTaken(true)}>
        Check
      </button>
    </>
  );
}

/** Two fields where typing in the first raises, and changes, the second's error. */
function RangeForm() {
  const [min, setMin] = useState('');
  const [max, setMax] = useState('5');
  const clash =
    min === ''
      ? null
      : Number(min) === Number(max)
        ? 'Must differ from Min.'
        : Number(min) > Number(max)
          ? 'Must be greater than Min.'
          : null;
  return (
    <>
      <Input
        label="Min"
        value={min}
        onChange={(e) => setMin(e.target.value)}
      />
      <Input
        label="Max"
        value={max}
        error={clash}
        onChange={(e) => setMax(e.target.value)}
      />
    </>
  );
}

describe('Input — its error', () => {
  it('is the field’s description while typing, and is spoken once when the field is left', async () => {
    const {user} = renderWithProviders(<NameForm />);

    await user.type(screen.getByLabelText('Name'), 'a/b');

    expect(screen.getByLabelText('Name')).toBeInvalid();
    expect(screen.getByLabelText('Name')).toHaveAccessibleDescription(NO_SLASH);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(politeAnnouncements()).toEqual([]);
    await user.tab();
    expect(politeAnnouncements()).toEqual([`Name: ${NO_SLASH}`]);
    await user.click(screen.getByLabelText('Name'));
    await user.tab();
    expect(politeAnnouncements()).toEqual([]);
  });

  it('is not spoken when typing in another field raises or changes it, and a spoken one is withdrawn', async () => {
    const {user} = renderWithProviders(<RangeForm />);
    await user.type(screen.getByLabelText('Min'), '10');
    await user.click(screen.getByLabelText('Max'));
    await user.click(screen.getByLabelText('Min'));

    await user.tripleClick(screen.getByLabelText('Min'));
    await user.keyboard('5');

    expect(screen.getByLabelText('Max')).toHaveAccessibleDescription('Must differ from Min.');
    expect(politeAnnouncements()).toEqual([]);
  });

  it('is spoken when an action raises it', async () => {
    const {user} = renderWithProviders(<NameForm />);

    await user.click(screen.getByRole('button', {name: 'Check'}));

    expect(politeAnnouncements()).toEqual(['Name: That name is taken.']);
  });

  it('is spoken again on each Enter, where a disabled submit would say nothing', async () => {
    const {user} = renderWithProviders(<NameForm />);
    await user.type(screen.getByLabelText('Name'), 'a/b');
    const region = () => screen.getByLabelText('Name').parentElement!.querySelector('[aria-live="polite"]')!;

    await user.keyboard('{Enter}');
    const first = region().textContent;
    await user.keyboard('{Enter}');

    expect(politeAnnouncements()).toEqual([`Name: ${NO_SLASH}`]);
    // Identical text is no change, and a reader speaks only a change.
    expect(region().textContent).not.toBe(first);
  });
});
