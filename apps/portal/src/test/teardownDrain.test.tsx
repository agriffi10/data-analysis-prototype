import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderWithProviders} from './renderWithProviders';

/**
 * The per-test drain in `src/test-setup.ts` holds a `setTimeout` captured before any fake clock
 * could replace it. Without that capture the drain awaits a timer nothing advances, and a test
 * leaving fake timers installed fails on the hook timeout rather than on anything it asserted.
 * Nothing in the suite leaves a fake clock behind today, which is exactly why this is written
 * down: the capture would otherwise be free to rot.
 */
describe('the teardown drain and a fake clock', () => {
  it('completes for a test that leaves fake timers installed', () => {
    renderWithProviders(<span>rendered under a fake clock</span>);
    expect(screen.getByText('rendered under a fake clock')).toBeInTheDocument();
    // Deliberately NOT restored: the drain has to survive this, and the next line is the last
    // thing this file does, so the leftover clock reaches teardown.
    vi.useFakeTimers();
  });
});
