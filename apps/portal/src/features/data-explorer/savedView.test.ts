import {describe, expect, it} from 'vitest';
import {appendViewLine, parseViewLine} from '../../lib/savedViewLine';
import {emptyExplorationPresentation, newExploration} from './exploration';
import {buildSavedView, readSavedView, stripForSharedFolder} from './savedView';
import type {SavedView} from './savedView';
import type {Exploration} from './dataExplorer.types';

/** A tab with every part of a view set, the way this build's own panels set them. */
function fullExploration(): Exploration {
  const base = newExploration({kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'});
  return {
    ...base,
    query: {
      filters: [
        {column: 'name', operator: 'contains', value: 'acme', valueKind: 'string'},
        {column: 'amount', operator: '>', value: '10', valueKind: 'number'}
      ],
      expression: "status <> 'void'",
      ordering: [{column: 'region', direction: 'asc', priority: 0}],
      grouping: {
        columns: ['region'],
        aggregates: [{fn: 'COUNT', column: '*'}],
        duplicatesOnly: false,
        showPercentage: true
      }
    },
    presentation: {
      ...emptyExplorationPresentation(),
      hiddenColumns: ['notes'],
      pinnedColumns: ['region'],
      columnOrder: ['region', 'name'],
      columnWidths: {region: 180},
      presentation: 'record',
      valuePanelOpen: true,
      recordRowIndex: 4,
      formatting: {
        rules: [
          {id: 'r1', column: 'name', operator: 'regex', value: '^ac', background: 'accent-soft'},
          {id: 'r2', column: 'region', operator: 'like', value: '%west%', foreground: 'danger'},
          {
            id: 'r3',
            column: 'amount',
            operator: 'regex',
            value: '',
            gradient: {min: 0, max: 9, from: 'accent-soft', to: 'danger-soft'}
          }
        ],
        colourByType: true,
        stripeColumns: ['region'],
        transformers: {
          name: {kind: 'url', template: 'https://example.test/{value}'},
          amount: {kind: 'numeric', precision: 2, lenient: false}
        }
      }
    }
  };
}

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

    expect(readSavedView(unknownOperator)).toBeNull();
    expect(readSavedView(extraField)).toBeNull();
    expect(readSavedView(unrenderable)).toBeNull();
    expect(readSavedView(undefined)).toBeNull();
  });

  it('loses its link columns and pattern rules, and says how many, when it comes from a shared space', () => {
    const view = buildSavedView(fullExploration());

    const {presentation, leftOut} = stripForSharedFolder(view!.presentation);

    expect(leftOut).toEqual({links: 1, patterns: 2});
    expect(Object.keys(presentation.formatting.transformers)).toEqual(['amount']);
    // The gradient rule ignores its operator, so it stays.
    expect(presentation.formatting.rules.map((rule) => rule.id)).toEqual(['r3']);
  });
});
