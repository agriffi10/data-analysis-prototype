import {describe, expect, it} from 'vitest';

/**
 * Fixture for the viewport-width reset in `src/test-setup.ts`. Tests do leave a phone width for the
 * reset to remove, but no test after one of them fails at that width, so without this the reset
 * could be deleted and the suite would stay green. It would stay green until a phone-width test
 * timed out on a loaded machine and the rest of its file rendered the mobile layout.
 *
 * The first test leaves a phone width set, as a test Vitest times out does, and the second must
 * start at jsdom's default. They rely on running in order in one file, which Vitest does unless the
 * config shuffles.
 */
describe('the viewport-width reset before every test', () => {
  it('leaves a phone width set, as a timed-out test would', () => {
    Object.defineProperty(window, 'innerWidth', {value: 400, writable: true, configurable: true});

    expect(window.matchMedia('(min-width: 640px)').matches).toBe(false);
  });

  it('starts the next test at the default width, which the media queries read as wide', () => {
    expect(window.innerWidth).toBe(1024);
    expect(window.matchMedia('(min-width: 640px)').matches).toBe(true);
  });
});
