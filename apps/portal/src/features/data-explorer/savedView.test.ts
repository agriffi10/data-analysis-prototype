import {describe, expect, it} from 'vitest';
import {appendViewLine, parseViewLine} from '../../lib/savedViewLine';
import {buildSavedView, readSavedView, stripForSharedFolder} from './savedView';
import {fullExploration} from './savedView.testkit';
import type {SavedView} from './savedView';
import type {FilterItem} from './dataExplorer.types';

describe('a saved view', () => {
  it('comes back whole from the file this build writes, minus only the panel', () => {
    const exploration = fullExploration();
    const parsed = parseViewLine(appendViewLine('SELECT 1', buildSavedView(exploration)) as string);

    const view = readSavedView(parsed.kind === 'ok' ? parsed.payload : null);

    expect(view).toEqual({
      source: {database: 'alice', table: 'orders'},
      query: exploration.query,
      presentation: {...exploration.presentation, valuePanelOpen: undefined}
    });
    expect(view && Object.hasOwn(view.presentation, 'valuePanelOpen')).toBe(false);
  });

  it('keeps a list that holds the empty string and names NULL', () => {
    const exploration = fullExploration();
    exploration.query.filters = [{column: 'region', operator: 'in', values: ['', 'north'], includesNull: true}];
    const parsed = parseViewLine(appendViewLine('SELECT 1', buildSavedView(exploration)) as string);

    const view = readSavedView(parsed.kind === 'ok' ? parsed.payload : null);

    expect(view?.query.filters).toEqual(exploration.query.filters);
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

  // The explorer used to offer Grid, Record and Text, and every view saved then records the
  // choice. Those files must still open, and a page loaded before this build — which refuses a
  // view without the key — must still open what this build saves.
  it('opens a view that records a Record or Text choice, and still writes the key older pages read', () => {
    const written = buildSavedView(fullExploration())!;
    expect(written.presentation.presentation).toBeNull();

    const current = readSavedView(structuredClone(written));
    expect(current).not.toBeNull();
    expect(current && Object.hasOwn(current.presentation, 'presentation')).toBe(false);
    for (const choice of ['grid', 'record', 'text']) {
      const legacy = structuredClone(written);
      Object.assign(legacy.presentation, {presentation: choice});
      expect(readSavedView(legacy)).toEqual(current);
    }
    const withoutKey = structuredClone(written) as {presentation: Record<string, unknown>};
    delete withoutKey.presentation.presentation;
    expect(readSavedView(withoutKey)).toEqual(current);

    // A value no build ever wrote is still a stranger, and refused whole.
    const unknownChoice = structuredClone(written);
    Object.assign(unknownChoice.presentation, {presentation: 'cards'});
    expect(readSavedView(unknownChoice)).toBeNull();
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

describe('a saved view carrying groups', () => {
  const leaf = (value: string): FilterItem => ({column: 'region', operator: '=', value, valueKind: 'string'});
  // A group at the top level holding a group: the deepest nesting the builder can make.
  const twoDeep: FilterItem = {join: 'or', items: [leaf('EU'), {join: 'and', items: [leaf('US'), leaf('CA')]}]};
  const withFilters = (filters: unknown[]) => {
    const view = structuredClone(buildSavedView(fullExploration()) as SavedView);
    (view.query as {filters: unknown[]}).filters = filters;
    return view;
  };

  it('comes back whole with a group nested two deep', () => {
    const exploration = fullExploration();
    exploration.query.filters = [leaf('x'), twoDeep];
    const parsed = parseViewLine(appendViewLine('SELECT 1', buildSavedView(exploration)) as string);

    expect(readSavedView(parsed.kind === 'ok' ? parsed.payload : null)?.query.filters).toEqual([leaf('x'), twoDeep]);
  });

  it.each([
    {
      name: 'a group nested three deep',
      item: {join: 'or', items: [{join: 'and', items: [{join: 'or', items: [leaf('EU')]}]}]}
    },
    {name: 'a group with no items', item: {join: 'or', items: []}},
    {name: 'a join that is neither and nor or', item: {join: 'xor', items: [leaf('EU')]}},
    {
      name: 'a prototype-key operator inside a group',
      item: {join: 'or', items: [{column: 'a', operator: 'toString', value: 'x'}]}
    },
    {name: 'a group carrying a key of its own', item: {join: 'or', items: [leaf('EU')], label: 'mine'}}
  ])('is refused whole for $name', ({item}) => {
    expect(readSavedView(withFilters([item]))).toBeNull();
  });
});
