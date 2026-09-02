import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, renderHook} from '@testing-library/react';
import {useRef} from 'react';
import {useListPlacement} from './useListPlacement';
import {MAX_LIST_HEIGHT, MIN_LIST_HEIGHT} from './comboboxPlacement';

/**
 * jsdom lays nothing out, so the geometry is stubbed: a wrapper inside a scrolling panel, each
 * with the rectangle the browser would have measured. The arithmetic itself is
 * `comboboxPlacement.test.ts`'s subject; what is asserted here is the measuring — which box
 * clips, and that the hook re-measures when the panel scrolls.
 */
function build(fieldTop: number, panelHeight = 400) {
  const panel = document.createElement('div');
  panel.style.overflowY = 'auto';
  const wrapper = document.createElement('div');
  panel.appendChild(wrapper);
  document.body.appendChild(panel);
  panel.getBoundingClientRect = () => ({top: 100, bottom: 100 + panelHeight, height: panelHeight}) as DOMRect;
  let top = fieldTop;
  wrapper.getBoundingClientRect = () => ({top, bottom: top + 36, height: 36}) as DOMRect;
  const rendered = renderHook(({open}: {open: boolean}) => useListPlacement(useRef(wrapper), open), {
    initialProps: {open: true}
  });
  return {...rendered, panel, moveFieldTo: (next: number) => (top = next)};
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('useListPlacement', () => {
  it('measures against the scrolling ancestor, not the viewport, and flips up when the panel is what clips', () => {
    // A 400px panel from 100 to 500; the field near its foot leaves ~24px below it inside the
    // panel, while the viewport (stubbed tall) would have said there was plenty.
    vi.stubGlobal('innerHeight', 2000);
    const {result} = build(440);

    expect(result.current.dropUp).toBe(true);
    expect(result.current.maxHeight).toBe(MAX_LIST_HEIGHT);
  });

  it('re-measures when the panel scrolls, and stops listening once the list is closed', () => {
    const {result, panel, moveFieldTo, rerender} = build(120);
    expect(result.current.dropUp).toBe(false);
    expect(result.current.maxHeight).toBe(MAX_LIST_HEIGHT);

    moveFieldTo(440);
    act(() => {
      panel.dispatchEvent(new Event('scroll'));
    });
    expect(result.current.dropUp).toBe(true);

    moveFieldTo(120);
    rerender({open: false});
    act(() => {
      panel.dispatchEvent(new Event('scroll'));
    });
    // Closed: the last answer stands, because nothing listens any more.
    expect(result.current.dropUp).toBe(true);
    expect(result.current.maxHeight).toBeGreaterThanOrEqual(MIN_LIST_HEIGHT);
  });
});
