import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, it, expect, vi} from 'vitest';
import {RefreshIconButton} from './RefreshIconButton';

describe('RefreshIconButton', () => {
  it('names what it refreshes and spins only while busy', () => {
    const {rerender} = render(
      <RefreshIconButton
        label="Refresh notifications"
        onClick={vi.fn()}
      />
    );

    const button = screen.getByRole('button', {name: 'Refresh notifications'});
    expect(button).toBeEnabled();
    expect(button.querySelector('svg')).not.toHaveClass('animate-spin');

    rerender(
      <RefreshIconButton
        label="Refresh notifications"
        busy
        onClick={vi.fn()}
      />
    );
    expect(screen.getByRole('button', {name: 'Refresh notifications'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Refresh notifications'}).querySelector('svg')).toHaveClass(
      'animate-spin'
    );
  });

  it('does not fire while busy', async () => {
    const onClick = vi.fn();
    render(
      <RefreshIconButton
        label="Refresh history"
        busy
        onClick={onClick}
      />
    );
    await userEvent.click(screen.getByRole('button', {name: 'Refresh history'}));
    expect(onClick).not.toHaveBeenCalled();
  });
});
