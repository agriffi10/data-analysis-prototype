import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MobileActionBar} from './MobileActionBar';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';

describe('MobileActionBar', () => {
  it('renders caller-supplied actions in a labelled toolbar', () => {
    render(
      <MobileActionBar ariaLabel="File actions">
        <button type="button">New folder</button>
        <button type="button">Upload</button>
      </MobileActionBar>
    );
    const bar = screen.getByRole('toolbar', {name: 'File actions'});
    expect(bar).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'New folder'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Upload'})).toBeInTheDocument();
  });

  it('is fixed to the bottom, hidden at tablet, and honors the safe-area inset', () => {
    render(
      <MobileActionBar>
        <button type="button">Go</button>
      </MobileActionBar>
    );
    const bar = screen.getByRole('toolbar');
    expect(bar).toHaveClass('fixed', 'bottom-0', 'tablet:hidden');
    expect(bar.className).toContain('env(safe-area-inset-bottom)');
  });

  it('has no a11y violations', async () => {
    await expectNoA11yViolations(
      <MobileActionBar ariaLabel="Actions">
        <button type="button">Upload</button>
      </MobileActionBar>,
      COMPONENT_AXE_OPTIONS
    );
  });
});
