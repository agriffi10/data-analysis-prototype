import {useEffect, useLayoutEffect} from 'react';
import {Link, useLocation, useNavigate, useNavigationType, useParams, type To} from '../lib/navigation';

/**
 * Pages for the seam's own tests: each says, on every commit, where it is and how it got there, and
 * offers the links a test lays out, served as a page through `renderApp`'s `pages`.
 */

/** What a page saw on one commit. */
export type Commit = {
  page: string;
  pathname: string;
  search: string;
  hash: string;
  type: string;
  key: string;
  state: unknown;
  params: Record<string, string | undefined>;
};

/** Every commit of every readout page, in order. */
export const commits: Commit[] = [];

/** Every mount of a readout page, by name, in order. */
export const mounts: string[] = [];

/** A link a test lays out on every readout page. */
export type FixtureLink = {label: string; to: To; state?: unknown; replace?: boolean};

/** What the readout pages offer, set by each test before it renders. */
export const fixture: {
  links: FixtureLink[];
  navigate: ((to: To, options?: {replace?: boolean; state?: unknown}) => void) | null;
} = {
  links: [],
  navigate: null
};

/** Forget every commit and mount, and lay out `links`. */
export function resetReadout(links: FixtureLink[] = []): void {
  commits.length = 0;
  mounts.length = 0;
  fixture.links = links;
  fixture.navigate = null;
}

/** The commits a page made, in order. */
export function commitsOf(page: string): Commit[] {
  return commits.filter((commit) => commit.page === page);
}

/** The latest commit of any readout page. */
export function lastCommit(): Commit {
  const commit = commits.at(-1);
  if (!commit) throw new Error('no readout page has committed');
  return commit;
}

function Readout({name}: {name: string}) {
  const location = useLocation();
  const type = useNavigationType();
  const params = useParams();
  const navigate = useNavigate();
  useLayoutEffect(() => {
    commits.push({page: name, ...location, type, params});
  });
  useEffect(() => {
    mounts.push(name);
    fixture.navigate = navigate;
  }, [name, navigate]);
  return (
    <main id="main">
      <h1>{`page ${name}`}</h1>
      <output aria-label="where">{`${location.pathname}${location.search}${location.hash}`}</output>
      {fixture.links.map((link) => (
        <Link
          key={link.label}
          to={link.to}
          state={link.state}
          replace={link.replace}>
          {link.label}
        </Link>
      ))}
      <a href="#section">In-page anchor</a>
      <p id="section">A section</p>
    </main>
  );
}

/**
 * A readout page component, for a mocked route page or a `renderApp` page.
 *
 * @param name - The page's name, as commits and mounts report it.
 * @returns The page.
 */
export function readoutPage(name: string) {
  return function ReadoutPage() {
    return <Readout name={name} />;
  };
}
