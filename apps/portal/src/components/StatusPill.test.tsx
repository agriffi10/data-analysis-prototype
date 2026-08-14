import {describe, it, expect} from 'vitest';
import {render, screen} from '@testing-library/react';
import {StatusPill} from './StatusPill';

// SPEC-186 FR-010 pattern A. Seven sites each wrote out this shape and each wrote out, in a
// comment, the rule that the LABEL carries the meaning. The component is what makes that rule
// structural instead of a convention seven authors happened to keep.

describe('StatusPill (SPEC-186 FR-010)', () => {
  it('always renders the text label, which is what carries the meaning', () => {
    render(<StatusPill tone="success">Uploaded</StatusPill>);
    expect(screen.getByText('Uploaded')).toBeInTheDocument();
  });

  it('hides the dot from the accessibility tree — it is a redundant signal, not information', () => {
    const {container} = render(<StatusPill tone="warning">Pending</StatusPill>);
    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot).not.toBeNull();
    expect(dot!.className).toContain('h-[7px]');
  });

  it('pulses only when asked', () => {
    const {container, rerender} = render(<StatusPill tone="warning">Uploading</StatusPill>);
    expect(container.querySelector('.animate-pulse')).toBeNull();
    rerender(
      <StatusPill
        tone="warning"
        pulse>
        Uploading
      </StatusPill>
    );
    expect(container.querySelector('.animate-pulse')).not.toBeNull();
  });

  it('can drop the dot without losing the label', () => {
    const {container} = render(
      <StatusPill
        tone="neutral"
        dot={false}>
        Cancelled
      </StatusPill>
    );
    expect(container.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
  });

  it('maps each tone to one token pair, and never to colour alone', () => {
    for (const [tone, token] of [
      ['success', 'text-success'],
      ['warning', 'text-warning'],
      ['danger', 'text-danger'],
      ['neutral', 'text-text-2']
    ] as const) {
      const {container, unmount} = render(<StatusPill tone={tone}>Label</StatusPill>);
      expect(container.firstElementChild!.className).toContain(token);
      unmount();
    }
  });
});
