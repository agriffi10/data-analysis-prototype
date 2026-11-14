import {describe, it, expect, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {renderApp} from '../../test/appRouter';
import {authenticated} from '../../test/authFixtures';
import {wrappersOf} from '../../test/viewSource';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn().mockRejectedValue(new Error('no session in test'))
}));

const VIEW = Object.values(import.meta.glob('./explore.tsx', {query: '?raw', import: 'default', eager: true}))[0] as string;

describe('App routing', () => {
  // The path is `/explore`, it is not the 404, and the lazy chunk resolves — the picker is the
  // page's own first surface, so finding it proves the route matched and the view mounted behind
  // Suspense.
  it('renders the Data Explorer at /explore', async () => {
    renderApp('/explore', {auth: authenticated('alice')});

    expect(await screen.findByRole('region', {name: 'Choose a table to explore'})).toBeInTheDocument();
    expect(screen.queryByRole('heading', {name: 'Page not found'})).not.toBeInTheDocument();
    // The skip link's target: without it, "Skip to main content" does nothing on this page.
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
  });

  // A lazy view with no ErrorBoundary unmounts the tree on a chunk-load rejection, and `Suspense`
  // has no error path of its own (the accepted rollover race). What can only be checked here is
  // that this view is WRAPPED in one — and inside the gate, so the page cannot start fetching
  // before the flag answer arrives.
  it('wraps /explore in FeatureRoute → ErrorBoundary → Suspense, in that order', () => {
    expect(wrappersOf(VIEW, 'ExplorePage')).toEqual(['FeatureRoute', 'ErrorBoundary', 'Suspense']);
    // And the gate is the RIGHT flag. Without this line, changing it to `flag="query"` left the
    // whole suite green — a flag bypass no test could see.
    expect(VIEW).toContain('<FeatureRoute flag="dataExplorer">');
  });
});
