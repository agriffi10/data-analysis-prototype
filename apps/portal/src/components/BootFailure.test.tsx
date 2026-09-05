import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {BootFailure} from './BootFailure';
import {expectNoA11yViolations} from '../test/axe';

describe('BootFailure', () => {
  it('renders one alert with the authored wording', () => {
    render(<BootFailure />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Data Quarry could not start');
    expect(alert).toHaveTextContent('Contact the Administrator.');
  });

  it('names no key, no value and no URL', () => {
    // The user's sentence. The operator's diagnostic is the single console line the
    // bootstrap writes, and putting a key name on screen would tell every visitor
    // which part of the deployment is wrong.
    render(<BootFailure />);

    const text = screen.getByRole('alert').textContent ?? '';
    expect(text).not.toMatch(/config\.json|VITE_|bucket|https?:/i);
  });

  it('has no accessibility violations', async () => {
    // Correct on first paint — nothing to drive into — so the render-and-check helper is
    // the right one here.
    await expectNoA11yViolations(<BootFailure />);
  });
});
