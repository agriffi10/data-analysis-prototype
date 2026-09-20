import {act, renderHook} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {useExplorationTabs} from './useExplorationTabs';
import {EXPLORATION_TABS_MAX, EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {FILTER_OPERATORS, operatorTakesValue, operatorTakesValues} from './explorationQueryOps';
import type {ExplorationSource} from './dataExplorer.types';

const TABLE: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const OTHER: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'customers'};
const KEY = `${EXPLORATION_TABS_STORAGE_PREFIX}alice`;

const setup = (username = 'alice') => renderHook(() => useExplorationTabs(username));

beforeEach(() => {
  sessionStorage.clear();
});

describe('useExplorationTabs — opening and the cap (FR-008)', () => {
  it('opens a tab over a source, labels it from the source and activates it', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    expect(id).toBeTruthy();
    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.activeTabId).toBe(id);
    expect(result.current.activeTab?.label).toBe('orders');
    expect(result.current.activeTab?.exploration.source).toEqual(TABLE);
    // FR-001 AC4: an empty query description.
    expect(result.current.activeTab?.exploration.query).toEqual({
      filters: [],
      expression: null,
      ordering: [],
      grouping: null
    });
  });

  it('takes an explicit label over the source’s own name', () => {
    const {result} = setup();
    act(() => {
      result.current.openTab(TABLE, {label: 'Q3 orders'});
    });
    expect(result.current.activeTab?.label).toBe('Q3 orders');
  });

  it('returns NULL at the cap rather than throwing or silently dropping', () => {
    // The caller needs a value it can branch on to raise the cap dialog (SPEC-179).
    const {result} = setup();
    act(() => {
      for (let i = 0; i < EXPLORATION_TABS_MAX; i += 1) result.current.openTab(TABLE);
    });
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);

    let refused: string | null = 'not-null';
    act(() => {
      refused = result.current.openTab(TABLE);
    });
    expect(refused).toBeNull();
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);
  });

  it('frees capacity again after a close', () => {
    // The counter must track closes as well as opens, or the cap becomes a high-water mark
    // and a user who closes a tab can never open another.
    const {result} = setup();
    act(() => {
      for (let i = 0; i < EXPLORATION_TABS_MAX; i += 1) result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab(result.current.tabs[0].id));

    let reopened: string | null = null;
    act(() => {
      reopened = result.current.openTab(OTHER);
    });
    expect(reopened).toBeTruthy();
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);
  });
});

describe('useExplorationTabs — closing keeps the invariant (FR-008 AC4)', () => {
  it('activates the tab to the LEFT when the active one closes', () => {
    const {result} = setup();
    let first: string | null = null;
    let second: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      second = result.current.openTab(OTHER);
    });
    expect(result.current.activeTabId).toBe(second);

    act(() => result.current.closeTab(second as unknown as string));
    expect(result.current.activeTabId).toBe(first);
    expect(result.current.tabs).toHaveLength(1);
  });

  it('ignores a close for an id that is not open', () => {
    const {result} = setup();
    act(() => {
      result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab('nope'));
    expect(result.current.tabs).toHaveLength(1);
  });
});

describe('useExplorationTabs — persistence (FR-008 AC2/AC3)', () => {
  it('persists under a prefix + username key and survives a reload', () => {
    const first = setup();
    act(() => {
      first.result.current.openTab(TABLE, {label: 'Q3 orders'});
    });
    expect(sessionStorage.getItem(KEY)).toBeTruthy();

    // A fresh hook is what a reload looks like to this module.
    const second = setup();
    expect(second.result.current.tabs).toHaveLength(1);
    expect(second.result.current.activeTab?.label).toBe('Q3 orders');
    expect(second.result.current.activeTab?.exploration.source).toEqual(TABLE);
  });

  it('restores a grouping written before SPEC-182 rather than discarding the document', () => {
    // The flags did not exist when such a document was written. Requiring them would fail
    // `isValidTabsState`, which discards the WHOLE state — every tab, over one absent
    // boolean — so they are accepted absent and normalised to false on the way out.
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'orders',
            exploration: {
              id: 'e',
              source: TABLE,
              query: {
                filters: [],
                expression: null,
                ordering: [],
                grouping: {columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]}
              },
              presentation: {}
            },
            scannedByExecution: {},
            history: {
              past: [
                {
                  filters: [],
                  expression: null,
                  ordering: [],
                  grouping: {columns: ['id'], aggregates: []}
                }
              ],
              future: []
            }
          }
        ],
        activeTabId: 'a'
      })
    );

    const {result} = setup();
    expect(result.current.tabs).toHaveLength(1);
    const grouping = result.current.activeTab?.exploration.query.grouping;
    expect(grouping?.columns).toEqual(['status']);
    // Normalised, not left undefined: `sameQuery` compares descriptions on a canonical
    // form, so an absent flag would compare unequal to the identical grouping the panel
    // builds — and the first apply after a reload would push a history entry for a change
    // nobody made.
    expect(grouping?.duplicatesOnly).toBe(false);
    expect(grouping?.showPercentage).toBe(false);
    // History entries render SQL too, so they are normalised on the same pass.
    expect(result.current.activeTab?.history.past[0].grouping?.duplicatesOnly).toBe(false);
  });

  it('keeps each user’s tabs separate', () => {
    const alice = setup('alice');
    act(() => {
      alice.result.current.openTab(TABLE);
    });
    expect(setup('bob').result.current.tabs).toEqual([]);
  });

  it('discards a malformed document entirely rather than applying it partially', () => {
    // A half-restored exploration is worse than none: it renders SQL from a description
    // the user never built.
    const cases = [
      'not json at all',
      JSON.stringify({version: 2, tabs: [], activeTabId: '', nextExplorationNumber: 1}),
      JSON.stringify({version: 1, tabs: 'nope', activeTabId: '', nextExplorationNumber: 1}),
      // A tab whose exploration has no source.
      JSON.stringify({
        version: 1,
        tabs: [{id: 'a', label: 'x', exploration: {id: 'e'}, scannedByExecution: {}}],
        activeTabId: 'a',
        nextExplorationNumber: 2
      }),
      // A tab whose source has an unknown kind.
      JSON.stringify({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'x',
            exploration: {
              id: 'e',
              source: {kind: 'elsewhere'},
              query: {filters: [], expression: null, ordering: [], grouping: null},
              presentation: {hiddenColumns: [], columnOrder: [], pinnedColumns: [], columnWidths: {}}
            },
            scannedByExecution: {}
          }
        ],
        activeTabId: 'a',
        nextExplorationNumber: 2
      }),
      // activeTabId referencing a tab that is not there — the invariant, violated.
      JSON.stringify({version: 1, tabs: [], activeTabId: 'ghost', nextExplorationNumber: 1})
    ];

    for (const raw of cases) {
      sessionStorage.setItem(KEY, raw);
      const {result} = setup();
      expect(result.current.tabs).toEqual([]);
      expect(result.current.activeTabId).toBe('');
    }
  });

  it('discards a document that is well-SHAPED but would render garbage', () => {
    // "Restorable" is not "renderable", and the stored document is the only untrusted
    // input this model has. Each of these passes a shape-only check and then does damage:
    // an unknown operator renders `"a" undefined 'x'` — invalid SQL sent to
    // StartQueryExecution rather than refused; a `grouping` of `{}` throws a raw TypeError
    // out of the renderer instead of an ExplorationRenderError; and a non-numeric ledger
    // value breaks the never-NaN invariant FR-007 AC4 exists to hold.
    const tab = (over: Record<string, unknown>) => ({
      version: 1,
      tabs: [
        {
          id: 'a',
          label: 'orders',
          exploration: {
            id: 'e',
            source: {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'},
            query: {filters: [], expression: null, ordering: [], grouping: null},
            presentation: {hiddenColumns: [], columnOrder: [], pinnedColumns: [], columnWidths: {}},
            ...(over.exploration as object)
          },
          scannedByExecution: over.scannedByExecution ?? {}
        }
      ],
      activeTabId: 'a'
    });

    const hostile = [
      tab({
        exploration: {
          query: {
            filters: [{column: 'a', operator: 'DROP', value: 'x'}],
            expression: null,
            ordering: [],
            grouping: null
          }
        }
      }),
      tab({
        exploration: {
          query: {
            filters: [{column: 'a', operator: '=', value: 'x', valueKind: 'raw'}],
            expression: null,
            ordering: [],
            grouping: null
          }
        }
      }),
      tab({exploration: {query: {filters: [], expression: null, ordering: [], grouping: {}}}}),
      tab({
        exploration: {
          query: {
            filters: [],
            expression: null,
            ordering: [],
            grouping: {columns: ['a'], aggregates: [{fn: 'EXEC', column: 'b'}]}
          }
        }
      }),
      tab({
        exploration: {
          query: {
            filters: [],
            expression: null,
            ordering: [{column: 'a', direction: 'sideways', priority: 0}],
            grouping: null
          }
        }
      }),
      tab({scannedByExecution: {'exec-1': '0x'}}),
      tab({scannedByExecution: {'exec-1': null}})
    ];

    for (const document of hostile) {
      sessionStorage.setItem(KEY, JSON.stringify(document));
      const {result} = setup();
      expect(result.current.tabs).toEqual([]);
    }
  });

  it('restores a well-formed document, so the discard test above is not vacuous', () => {
    // Without this pair, a validator that rejected EVERYTHING would pass every case above.
    const first = setup();
    act(() => {
      first.result.current.openTab(TABLE);
    });
    const stored = sessionStorage.getItem(KEY) as string;

    sessionStorage.clear();
    sessionStorage.setItem(KEY, stored);
    expect(setup().result.current.tabs).toHaveLength(1);
  });
});

describe('useExplorationTabs — the operators a stored document may carry (SPEC-238)', () => {
  const documentWith = (over: Record<string, unknown>) => ({
    version: 1,
    tabs: [
      {
        id: 'a',
        label: 'orders',
        exploration: {
          id: 'e',
          source: {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'},
          query: {filters: [], expression: null, ordering: [], grouping: null},
          presentation: {hiddenColumns: [], columnOrder: [], pinnedColumns: [], columnWidths: {}},
          ...over
        },
        scannedByExecution: {}
      }
    ],
    activeTabId: 'a'
  });

  const restoredQuery = (over: Record<string, unknown>) => {
    sessionStorage.setItem(KEY, JSON.stringify(documentWith(over)));
    return setup().result.current.tabs[0]?.exploration.query ?? null;
  };

  it('restores a tab carrying EVERY operator the app offers', () => {
    // The guard on the one derivation that is not compile-checked. A hand-written set here
    // — which is what this used to be — silently discarded a whole session's tabs over an
    // operator it had not heard of. The length is asserted so the loop cannot be vacuous.
    expect(FILTER_OPERATORS).toHaveLength(16);
    const filters = FILTER_OPERATORS.map((operator, index) => ({
      column: `c${index}`,
      operator,
      ...(operatorTakesValue(operator) ? {value: 'x'} : {}),
      ...(operatorTakesValues(operator) ? {values: ['a', 'b']} : {})
    }));
    const query = restoredQuery({query: {filters, expression: null, ordering: [], grouping: null}});
    expect(query?.filters).toEqual(filters);
  });

  it('restores a list filter with its values in their stored order', () => {
    const filters = [{column: 'state', operator: 'in', values: ['NY', 'NJ']}];
    const query = restoredQuery({query: {filters, expression: null, ordering: [], grouping: null}});
    expect(query?.filters).toEqual(filters);
  });

  it('discards a document whose filter is shaped wrong', () => {
    // Each of these is a shape the one-value-per-line field cannot express, so a filter
    // carrying one could never be edited back into the form it came from.
    const bad = [
      {column: 'a', operator: 'contains', value: 7},
      {column: 'a', operator: 'in', values: ['a', 7]},
      {column: 'a', operator: 'in', values: ['a', null]},
      {column: 'a', operator: 'in', values: ['a', '']},
      {column: 'a', operator: 'in', values: ['a', 'b\nc']},
      {column: 'a', operator: 'in', values: ['a', 'b\rc']},
      {column: 'a', operator: 'in', values: 'NY'},
      {column: 'a', operator: 'toString', value: 'x'}
    ];
    for (const filter of bad) {
      sessionStorage.setItem(
        KEY,
        JSON.stringify(documentWith({query: {filters: [filter], expression: null, ordering: [], grouping: null}}))
      );
      expect(setup().result.current.tabs, JSON.stringify(filter)).toEqual([]);
    }
  });

  it('restores an is-empty COLOUR RULE into the formatting it belongs to', () => {
    // Asserted on the rule itself, not on the tab: the formatting check swaps an invalid
    // block for the empty state rather than refusing the document, so "the tab restored"
    // would pass with the rule silently gone.
    const rules = [{id: 'r1', column: 'last_name', operator: 'isEmpty', value: '', background: 'warning-soft'}];
    sessionStorage.setItem(
      KEY,
      JSON.stringify(
        documentWith({
          presentation: {
            hiddenColumns: [],
            columnOrder: [],
            pinnedColumns: [],
            columnWidths: {},
            formatting: {rules, colourByType: false, stripeColumns: [], transformers: {}}
          }
        })
      )
    );
    const restored = setup().result.current.tabs[0]?.exploration.presentation.formatting.rules;
    expect(restored).toEqual(rules);
  });
});

describe('useExplorationTabs — cumulative cost (FR-007 AC2/AC3)', () => {
  it('accumulates bytes across distinct executions', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    expect(result.current.activeTabBytesScanned).toBe(1024);

    act(() => result.current.recordScan(id as unknown as string, 'exec-2', 2048));
    expect(result.current.activeTabBytesScanned).toBe(3072);
  });

  it('counts a zero-byte execution without turning the total into NaN', () => {
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 0));
    expect(result.current.activeTabBytesScanned).toBe(0);
  });
});

describe('useExplorationTabs — editing the active exploration', () => {
  it('replaces only the active tab’s exploration', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });

    act(() =>
      result.current.updateActiveExploration((exploration) => ({
        ...exploration,
        query: {...exploration.query, expression: 'qty > 0'}
      }))
    );

    expect(result.current.activeTab?.exploration.query.expression).toBe('qty > 0');
    const untouched = result.current.tabs.find((t) => t.id === first);
    expect(untouched?.exploration.query.expression).toBeNull();
  });

  it('is a no-op with no tabs open', () => {
    const {result} = setup();
    act(() => result.current.updateActiveExploration((e) => e));
    expect(result.current.tabs).toEqual([]);
  });
});

describe('useExplorationTabs — a stored formatting block (SPEC-184 FR-007 AC2)', () => {
  /** Seeds one tab whose presentation carries `formatting` verbatim. */
  const seedFormatting = (formatting: unknown) =>
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'orders',
            exploration: {
              id: 'e',
              source: TABLE,
              query: {filters: [], expression: null, ordering: [], grouping: null},
              presentation: {formatting}
            },
            scannedByExecution: {},
            history: {past: [], future: []}
          }
        ],
        activeTabId: 'a'
      })
    );

  const EMPTY = {rules: [], colourByType: false, stripeColumns: [], transformers: {}};

  const good = {
    rules: [{id: 'r', column: 'status', operator: '=', value: 'ok', foreground: 'danger'}],
    colourByType: true,
    stripeColumns: ['id'],
    transformers: {id: {kind: 'numeric', precision: 2, lenient: true}}
  };

  it('discards the block WHOLE when any part of it is wrong, and keeps the tab', () => {
    // Never partially: a rule that survived while the one meant to override it was dropped
    // paints the opposite of what was intended, and the user has no way to tell.
    for (const broken of [
      {...good, rules: [{...good.rules[0], operator: 'sounds-like'}]},
      {...good, rules: 'not an array'},
      {...good, colourByType: 'yes'},
      {...good, stripeColumns: [1, 2]},
      {...good, transformers: {id: {kind: 'unknown'}}},
      {...good, transformers: [{kind: 'numeric', precision: 2, lenient: true}]},
      {...good, transformers: {id: {kind: 'numeric', precision: 99, lenient: true}}},
      {...good, transformers: {id: {kind: 'binary', encoding: 'rot13', maxLength: 8}}},
      'not an object'
    ]) {
      sessionStorage.clear();
      seedFormatting(broken);
      const {tabs} = setup().result.current;
      expect(tabs, JSON.stringify(broken)).toHaveLength(1);
      expect(tabs[0].exploration.presentation.formatting, JSON.stringify(broken)).toEqual(EMPTY);
    }
  });

  it('refuses a colour that is not in the palette', () => {
    // The palette is bounded so its contrast can be MEASURED; a stored `#ff0000` would be
    // rendered verbatim as an inline style, and nothing downstream would question it.
    for (const rule of [
      {id: 'r', operator: '=', value: 'ok', foreground: '#ff0000'},
      {id: 'r', operator: '=', value: 'ok', background: 'rebeccapurple'},
      {id: 'r', operator: '=', value: 'ok', foreground: 'warning'},
      {id: 'r', operator: '=', value: 'ok', gradient: {min: 0, max: 1, from: '#fff', to: 'danger-soft'}}
    ]) {
      sessionStorage.clear();
      seedFormatting({...good, rules: [rule]});
      expect(setup().result.current.tabs[0].exploration.presentation.formatting, JSON.stringify(rule)).toEqual(EMPTY);
    }
  });
});
