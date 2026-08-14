import {describe, it, expect, vi} from 'vitest';
import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {Chip, ChipList} from './Chip';

// SPEC-186 FR-009. Three byte-identical `<li>` copies that had already drifted — the remove
// target was 24x24 in one and 20x20 in the other two, under WCAG 2.2 SC 2.5.8's minimum — now
// have one implementation. Width is bounded here, which none of the copies did.

const MAX_USERNAME = `a${'x'.repeat(62)}`; // 63 chars: the ceiling of ^[a-z][a-z0-9_]{2,62}$

function renderChip(over: Partial<Parameters<typeof Chip>[0]> = {}) {
  return render(
    <ChipList
      ariaLabel="Recipients"
      className="mb-2">
      <Chip
        name="malathi"
        removeLabel="Remove malathi"
        onRemove={vi.fn()}
        {...over}
      />
    </ChipList>
  );
}

describe('Chip (SPEC-186 FR-009)', () => {
  it('meets the 24x24 minimum target size on the remove control', () => {
    renderChip();
    const remove = screen.getByRole('button', {name: 'Remove malathi'});
    // The classes ARE the size — jsdom computes no layout, so the token is the assertion.
    expect(remove.className).toMatch(/\bh-6\b/);
    expect(remove.className).toMatch(/\bw-6\b/);
    // `flex-none` is what keeps it 24x24 next to a name long enough to want the space.
    expect(remove.className).toMatch(/\bflex-none\b/);
  });

  it('keeps the full username as the remove button’s accessible name', () => {
    // SPEC-163's registry and every removal test query these by name, and SPEC-172 forbids a
    // reason becoming one — so the label is supplied whole by the caller and never derived.
    renderChip({name: MAX_USERNAME, removeLabel: `Remove ${MAX_USERNAME}`});
    expect(screen.getByRole('button', {name: `Remove ${MAX_USERNAME}`})).toBeInTheDocument();
  });

  it('bounds a maximal-length name inside its container rather than overflowing it', () => {
    // The measured case: ~62px of chrome + ~8.7px per monospaced character puts a 63-character
    // name at roughly 610px — wider than the 448px dialog around it. Truncation is what stops
    // that, and `max-w-full` + `min-w-0` are what let it happen inside a flex row.
    renderChip({name: MAX_USERNAME, removeLabel: `Remove ${MAX_USERNAME}`});
    const chip = screen.getByRole('listitem');
    expect(chip.className).toMatch(/\bmax-w-full\b/);
    expect(chip.className).toMatch(/\bmin-w-0\b/);

    const value = within(chip).getByTitle(MAX_USERNAME);
    expect(value).toHaveTextContent(MAX_USERNAME);
    expect(value.className).toMatch(/\btruncate\b/);
    expect(value.className).toMatch(/\bmin-w-0\b/);
  });

  it('flows left to right and wraps at the container width', () => {
    renderChip();
    const list = screen.getByRole('list', {name: 'Recipients'});
    expect(list.className).toMatch(/\bflex\b/);
    expect(list.className).toMatch(/\bflex-wrap\b/);
    // The caller's own margin survives — positional, not drift to normalise away.
    expect(list.className).toMatch(/\bmb-2\b/);
  });

  it('renders an optional kind tag before the name', () => {
    renderChip({tag: 'SPACE', name: 'salesteam', removeLabel: 'Remove space salesteam'});
    expect(within(screen.getByRole('listitem')).getByText('SPACE')).toBeInTheDocument();
  });

  it('removes on click, and does nothing while disabled', async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    const {rerender} = renderChip({onRemove});
    await user.click(screen.getByRole('button', {name: 'Remove malathi'}));
    expect(onRemove).toHaveBeenCalledTimes(1);

    rerender(
      <ChipList ariaLabel="Recipients">
        <Chip
          name="malathi"
          removeLabel="Remove malathi"
          disabled
          onRemove={onRemove}
        />
      </ChipList>
    );
    expect(screen.getByRole('button', {name: 'Remove malathi'})).toBeDisabled();
  });
});
