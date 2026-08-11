import {Link} from 'react-router';
import {usePageTitle} from '../hooks/usePageTitle';

export type FeatureUnavailablePageProps = {
  /** What the user was trying to reach, in their words ("Query"). Omitted when nothing is on. */
  feature?: string;
  /** Where to go instead: the first enabled destination. Omitted when there is none. */
  fallback?: {to: string; label: string};
};

/**
 * "This feature is not available here" — the landing place for a route whose flag is off.
 *
 * **NOT the 404 page, deliberately.** The route exists; the feature does not. A user who
 * follows a colleague's link or an old notification into a disabled feature has not mistyped
 * anything, and telling them the page does not exist would send them looking for a URL that
 * is perfectly correct. The wording says "not available in this environment" for the same
 * reason — it is a property of the deployment, not of them.
 *
 * It names no reason and offers no way to ask for access: a flag is presentation, the person
 * who can change it is not reachable from here, and inventing an appeal route would imply a
 * permission model that does not exist.
 *
 * `feature` and `fallback` are both optional because of the one case where neither is true:
 * every feature off. Then it names nothing and offers nothing, which is honest — the
 * alternative is a link to a page that would render this same component.
 *
 * @example
 * <FeatureUnavailablePage feature="Query" fallback={{to: '/files', label: 'Files'}} />
 */
export function FeatureUnavailablePage({feature, fallback}: FeatureUnavailablePageProps) {
  usePageTitle(feature ? `${feature} unavailable` : 'Not available');

  return (
    <main
      id="main"
      className="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <h1 className="text-3xl font-semibold text-text">{feature ? `${feature} isn’t available` : 'Nothing to show'}</h1>
      <p className="mt-3 max-w-prose text-text-2">
        {feature ? `${feature} isn’t available in this environment.` : 'No features are available in this environment.'}
      </p>
      {fallback && (
        <Link
          to={fallback.to}
          className="mt-8 font-medium text-accent-text underline hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Go to {fallback.label}
        </Link>
      )}
    </main>
  );
}
