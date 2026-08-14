import {describe, it, expect} from 'vitest';
import {LIST_GAP, MAX_LIST_HEIGHT, MIN_LIST_HEIGHT, listPlacement} from './comboboxPlacement';

// SPEC-186 FR-003. The property is numeric — the list's far edge must not pass the edge of the
// box that clips it — so it is asserted as arithmetic rather than through jsdom, which has no
// layout engine and reports every rect as zero.
//
// Every case derives the list's own far edge from the returned placement and compares it with
// the clip, so a wrong flip or a wrong cap fails here and not by inspection.

/** Where the rendered list's far edge lands, given a placement. */
function listEdge(field: {fieldTop: number; fieldBottom: number}, p: {dropUp: boolean; maxHeight: number}) {
  return p.dropUp ? field.fieldTop - LIST_GAP - p.maxHeight : field.fieldBottom + LIST_GAP + p.maxHeight;
}

describe('listPlacement (SPEC-186 FR-003)', () => {
  // The measurement that produced the defect: Add members at 1400x900, field bottom at y=472,
  // dialog bottom at y=585. The old rule compared against window.innerHeight (900), found 428px
  // of "room", and rendered a 240px list from 472 to 682 — 97px past the panel.
  it('keeps the list inside the DIALOG in the case that was measured live', () => {
    const field = {fieldTop: 440, fieldBottom: 472};
    const clip = {clipTop: 240, clipBottom: 585};
    const placement = listPlacement({...field, ...clip});

    expect(listEdge(field, placement)).toBeLessThanOrEqual(clip.clipBottom);
    // Below is 109px — over the flip floor — so it stays below and is capped, not flipped.
    expect(placement.dropUp).toBe(false);
    expect(placement.maxHeight).toBe(585 - 472 - LIST_GAP);
    // For contrast, the behaviour that was measured: the list rendered its natural 210px of
    // content from 472 to 682, which is 97px past the panel. The cap above is what removes it.
    expect(682 - clip.clipBottom).toBe(97);
    expect(placement.maxHeight).toBeLessThan(210);
  });

  it('flips above and stays inside when the field sits at the bottom of the dialog', () => {
    const field = {fieldTop: 520, fieldBottom: 552};
    const clip = {clipTop: 100, clipBottom: 585};
    const placement = listPlacement({...field, ...clip});

    expect(placement.dropUp).toBe(true);
    expect(listEdge(field, placement)).toBeGreaterThanOrEqual(clip.clipTop);
    expect(placement.maxHeight).toBe(MAX_LIST_HEIGHT);
  });

  it('stays below when below is cramped and above is no better — reading order wins the tie', () => {
    const field = {fieldTop: 120, fieldBottom: 152};
    const clip = {clipTop: 100, clipBottom: 200};
    expect(listPlacement({...field, ...clip}).dropUp).toBe(false);
  });

  it('never exceeds its cap where there is room to spare (a page, not a dialog)', () => {
    const placement = listPlacement({fieldTop: 100, fieldBottom: 132, clipTop: 0, clipBottom: 900});
    expect(placement).toEqual({dropUp: false, maxHeight: MAX_LIST_HEIGHT});
  });

  it('never collapses below the floor, so the list always shows it is scrollable', () => {
    const placement = listPlacement({fieldTop: 500, fieldBottom: 532, clipTop: 496, clipBottom: 540});
    expect(placement.maxHeight).toBe(MIN_LIST_HEIGHT);
  });

  // A sweep rather than three hand-picked rows: the containment property has to hold for every
  // field position in a realistic dialog, not only the ones an author thought of.
  it('holds containment for every field position in a 600px dialog', () => {
    const clip = {clipTop: 100, clipBottom: 700};
    for (let fieldBottom = 140; fieldBottom <= 690; fieldBottom += 10) {
      const field = {fieldTop: fieldBottom - 32, fieldBottom};
      const placement = listPlacement({...field, ...clip});
      const edge = listEdge(field, placement);
      if (placement.dropUp) expect(edge).toBeGreaterThanOrEqual(clip.clipTop);
      else expect(edge).toBeLessThanOrEqual(clip.clipBottom);
    }
  });
});
