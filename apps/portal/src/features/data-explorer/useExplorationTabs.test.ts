import {act, renderHook} from '@testing-library/react';
import {beforeEach, describe, expect, it} from 'vitest';
import {useExplorationTabs} from './useExplorationTabs';
import {EXPLORATION_TABS_MAX, EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import type {ExplorationSource} from './dataExplorer.types';

const TABLE: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const OTHER: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'customers'};
const KEY = `${EXPLORATION_TABS_STORAGE_PREFIX}alice`;

const setup = (username = 'alice') => renderHook(() => useExplorationTabs(username));

beforeEach(() => {
  sessionStorage.clear();
});

describe('useExplorationTabs — opening and the cap (FR-008)', () => {
  it('starts with no tabs — an exploration needs a source and there is none to guess', () => {
    const {result} = setup();
    expect(result.current.tabs).toEqual([]);
    expect(result.current.activeTab).toBeNull();
    expect(result.current.activeTabId).toBe('');
  });

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

  it('refuses within a BATCH — an id is never returned for a tab that is not created', () => {
    // The shape a multi-select "open these tables" produces in SPEC-179. Checked against
    // this render's state alone, three opens two below the cap each see room, each return
    // an id, and only two tabs appear — so the caller believes it opened three and raises
    // no cap dialog. Every returned id must name a real tab.
    const {result} = setup();
    act(() => {
      for (let i = 0; i < EXPLORATION_TABS_MAX - 2; i += 1) result.current.openTab(TABLE);
    });
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX - 2);

    const returned: (string | null)[] = [];
    act(() => {
      returned.push(result.current.openTab(TABLE));
      returned.push(result.current.openTab(TABLE));
      returned.push(result.current.openTab(TABLE));
    });

    expect(returned.filter(Boolean)).toHaveLength(2);
    expect(returned[2]).toBeNull();
    expect(result.current.tabs).toHaveLength(EXPLORATION_TABS_MAX);
    const openIds = new Set(result.current.tabs.map((t) => t.id));
    for (const id of returned.filter(Boolean)) expect(openIds.has(id as string)).toBe(true);
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

  it('leaves a VALID state when the last tab closes', () => {
    // `activeTabId` must never dangle. Unlike the Query workspace this surface has a
    // legitimate zero-tab state, so the answer is '' rather than a kept-alive tab.
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab(id as unknown as string));

    expect(result.current.tabs).toEqual([]);
    expect(result.current.activeTabId).toBe('');
    expect(result.current.activeTab).toBeNull();
  });

  it('ignores a close for an id that is not open', () => {
    const {result} = setup();
    act(() => {
      result.current.openTab(TABLE);
    });
    act(() => result.current.closeTab('nope'));
    expect(result.current.tabs).toHaveLength(1);
  });

  it('keeps the active tab when a DIFFERENT tab closes', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });
    const active = result.current.activeTabId;
    act(() => result.current.closeTab(first as unknown as string));
    expect(result.current.activeTabId).toBe(active);
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

  it('discards a document whose grouping flags are the wrong TYPE', () => {
    // Absent is a version difference; a string is a corrupt document, and the renderer
    // branches on these.
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
                grouping: {columns: ['status'], aggregates: [], duplicatesOnly: 'yes'}
              },
              presentation: {}
            },
            scannedByExecution: {}
          }
        ],
        activeTabId: 'a'
      })
    );

    expect(setup().result.current.tabs).toEqual([]);
  });

  it('keeps each user’s tabs separate', () => {
    const alice = setup('alice');
    act(() => {
      alice.result.current.openTab(TABLE);
    });
    expect(setup('bob').result.current.tabs).toEqual([]);
  });

  it('persists NOTHING for an empty username (the dev-unauth path)', () => {
    const {result} = setup('');
    act(() => {
      result.current.openTab(TABLE);
    });
    expect(result.current.tabs).toHaveLength(1);
    expect(sessionStorage.length).toBe(0);
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

  it('restores the same document once its one hostile field is corrected', () => {
    // The pair that keeps the test above honest: these documents are rejected for the
    // field named, not because the fixture is malformed in some other way.
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
              source: {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'},
              query: {
                filters: [{column: 'a', operator: '=', value: 'x', valueKind: 'number'}],
                expression: null,
                ordering: [{column: 'a', direction: 'asc', priority: 0}],
                grouping: {columns: ['a'], aggregates: [{fn: 'COUNT', column: '*'}]}
              },
              presentation: {hiddenColumns: [], columnOrder: [], pinnedColumns: [], columnWidths: {}}
            },
            scannedByExecution: {'exec-1': 1024}
          }
        ],
        activeTabId: 'a'
      })
    );
    const {result} = setup();
    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.activeTabBytesScanned).toBe(1024);
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

  it('adds NOTHING for a cache hit — the same execution recorded twice', () => {
    // FR-007 AC3, true by construction: the ledger is keyed by execution id, so a
    // re-rendered identical statement resolves to an id already present. A running total
    // would have to DETECT a cache hit, and a detector can be wrong in the direction that
    // overcharges the user.
    const {result} = setup();
    let id: string | null = null;
    act(() => {
      id = result.current.openTab(TABLE);
    });

    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));
    act(() => result.current.recordScan(id as unknown as string, 'exec-1', 1024));

    expect(result.current.activeTabBytesScanned).toBe(1024);
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

  it('keeps each tab’s ledger to itself', () => {
    const {result} = setup();
    let first: string | null = null;
    act(() => {
      first = result.current.openTab(TABLE);
      result.current.openTab(OTHER);
    });

    act(() => result.current.recordScan(first as unknown as string, 'exec-1', 500));
    // The second tab is the active one and has run nothing.
    expect(result.current.activeTabBytesScanned).toBe(0);

    act(() => result.current.setActiveTab(first as unknown as string));
    expect(result.current.activeTabBytesScanned).toBe(500);
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

  it('restores a whole, valid block', () => {
    seedFormatting(good);
    expect(setup().result.current.tabs[0].exploration.presentation.formatting).toEqual(good);
  });

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

  it('defaults a document written before SPEC-184, which carries no block at all', () => {
    seedFormatting(undefined);
    expect(setup().result.current.tabs[0].exploration.presentation.formatting).toEqual(EMPTY);
  });
});
