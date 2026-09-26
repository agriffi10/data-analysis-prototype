import {Route, Routes} from 'react-router';
import {appendViewLine} from '../../lib/savedViewLine';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {DataExplorerWorkspace} from './DataExplorerWorkspace';
import {emptyExplorationPresentation, newExploration} from './exploration';
import {renderExplorationSql} from './renderExplorationSql';
import {buildSavedView} from './savedView';
import type {QueryClient} from '@tanstack/react-query';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {Exploration} from './dataExplorer.types';

/**
 * Fixtures for the saved-view journeys: a tab with every part of a view set, the file this build
 * writes for it, and the workspace rendered beside a stub of the Query route a refusal hands to.
 */

/** A tab with every part of a view set, the way this build's own panels set them. */
export function fullExploration(database = 'alice'): Exploration {
  const base = newExploration({kind: 'table', spaceId: 'personal', database, table: 'orders'});
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

/** The statement a tab renders, which is what a save writes above the view line. */
export function renderedSql(exploration: Exploration): string {
  return renderExplorationSql(exploration.source, exploration.query);
}

/** The body this build's save writes for a tab. */
export function savedFileText(exploration: Exploration): string {
  return appendViewLine(renderedSql(exploration), buildSavedView(exploration)) as string;
}

/** One listed saved query, in the personal space or the shared `teamspace`. */
export function savedFile(name: string, space: 'alice' | 'teamspace' = 'alice'): SavedQuery {
  const shared = space === 'teamspace';
  return {
    spaceId: shared ? 'teamspace' : 'personal',
    bucket: shared ? 'shared-space' : 'user-space',
    key: `${space}/saved_queries/${name}.sql`,
    name,
    updatedAt: '2026-09-20T00:00:00.000Z',
    size: 400
  };
}

/** The workspace at `/explore`, beside a stub `/query` to land a hand-off on, on jsdom's history. */
export function renderExplorer(options: {queryClient?: QueryClient} = {}) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/explore"
        element={<DataExplorerWorkspace />}
      />
      <Route
        path="/query"
        element={<p>Query workspace</p>}
      />
    </Routes>,
    {route: '/explore', auth: authenticated('alice'), browserRouter: true, ...options}
  );
}
