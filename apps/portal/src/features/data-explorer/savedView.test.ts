import {describe, expect, it} from 'vitest';
import {appendViewLine, parseViewLine} from '../../lib/savedViewLine';
import {buildSavedView, readSavedView, stripForSharedFolder} from './savedView';
import {fullExploration} from './savedView.testkit';
import type {SavedView} from './savedView';

describe('a saved view', () => {
  it('comes back whole from the file this build writes, minus only the panel and record row', () => {
    const exploration = fullExploration();
    const parsed = parseViewLine(appendViewLine('SELECT 1', buildSavedView(exploration)) as string);

    const view = readSavedView(parsed.kind === 'ok' ? parsed.payload : null);

    expect(view).toEqual({
      source: {database: 'alice', table: 'orders'},
      query: exploration.query,
      presentation: {...exploration.presentation, valuePanelOpen: undefined, recordRowIndex: undefined}
    });
    expect(view && Object.hasOwn(view.presentation, 'valuePanelOpen')).toBe(false);
  });

  it('is refused whole, not repaired, when any part is something this build would have to fix', () => {
    const view = buildSavedView(fullExploration()) as SavedView;
    const unknownOperator = structuredClone(view);
    Object.assign(unknownOperator.presentation.formatting.rules[0], {operator: 'soundsLike'});
    const extraField = structuredClone(view);
    Object.assign(extraField.presentation, {zoom: 2});
    const unrenderable = structuredClone(view);
    unrenderable.query.grouping = {...view.query.grouping!, aggregates: [{fn: 'SUM', column: '*'}]};
    const nestedExtra = structuredClone(view);
    Object.assign(nestedExtra.query.filters[0], {caseSensitive: true});
    const hiddenByWidth = structuredClone(view);
    hiddenByWidth.presentation.columnWidths = {region: 0};
    const tooLong = structuredClone(view);
    tooLong.query.expression = `note = '${'x'.repeat(270_000)}'`;

    expect(readSavedView(unknownOperator)).toBeNull();
    expect(readSavedView(extraField)).toBeNull();
    expect(readSavedView(unrenderable)).toBeNull();
    expect(readSavedView(tooLong)).toBeNull();
    expect(readSavedView(nestedExtra)).toBeNull();
    expect(readSavedView(hiddenByWidth)).toBeNull();
    expect(readSavedView(undefined)).toBeNull();
  });

  it('loses its link columns and pattern rules, and says how many, when it comes from a shared space', () => {
    const view = buildSavedView(fullExploration());

    const {presentation, leftOut} = stripForSharedFolder(view!.presentation);

    expect(leftOut).toEqual({links: 1, patterns: 3});
    expect(Object.keys(presentation.formatting.transformers)).toEqual(['amount', 'payload']);
    // The gradient rule ignores its operator, so it stays.
    expect(presentation.formatting.rules.map((rule) => rule.id)).toEqual(['r3']);
  });
});
