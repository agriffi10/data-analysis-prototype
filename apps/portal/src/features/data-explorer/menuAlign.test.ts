import {describe, expect, it} from 'vitest';
import {MENU_MIN_WIDTH_PX} from '../../components/Menu';
import {contentBottomOf, contentRightOf, MENU_MIN_HEIGHT_PX, menuAlignFor, menuMaxHeightFor} from './menuAlign';

describe('menuAlignFor', () => {
  it('opens leftward when opening rightward would pass the grid box’s content edge', () => {
    expect(menuAlignFor(800 - MENU_MIN_WIDTH_PX + 1, 800)).toBe('right');
    expect(menuAlignFor(800 - MENU_MIN_WIDTH_PX, 800)).toBe('left');
  });

  it('measures to the content edge, inside the scrollbar gutter, and keeps the default when unmeasured', () => {
    const box = document.createElement('div');
    box.getBoundingClientRect = () => new DOMRect(100, 0, 815, 400);
    Object.defineProperty(box, 'clientLeft', {value: 1});
    Object.defineProperty(box, 'clientWidth', {value: 798});

    expect(contentRightOf(box)).toBe(899);
    expect(contentRightOf(document.createElement('div'))).toBeUndefined();
    expect(menuAlignFor(700, undefined)).toBe('left');
  });

  // The grid scrolls in a box bounded to the viewport, so a menu reaching past its bottom lost
  // its last items — "Clear filter" and "Hide column" among them — on a laptop-height screen.
  it('caps the menu to the room left below its button, and never below two items', () => {
    const box = document.createElement('div');
    box.getBoundingClientRect = () => new DOMRect(0, 200, 800, 340);
    Object.defineProperty(box, 'clientTop', {value: 1});
    Object.defineProperty(box, 'clientHeight', {value: 329});

    expect(contentBottomOf(box)).toBe(530);
    expect(menuMaxHeightFor(230, 530)).toBe(292);
    expect(menuMaxHeightFor(500, 530)).toBe(MENU_MIN_HEIGHT_PX);
    expect(menuMaxHeightFor(230, undefined)).toBeUndefined();
  });
});
