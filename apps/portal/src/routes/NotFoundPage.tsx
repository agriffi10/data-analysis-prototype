import {Link} from 'react-router';
import {usePageTitle} from '../hooks/usePageTitle';

/** Minimal not-found page for unknown routes. */
export default function NotFoundPage() {
  usePageTitle('Not Found');

  return (
    <main
      id="main"
      className="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <h1 className="text-3xl font-semibold text-text">Page not found</h1>
      <p className="mt-3 text-text-2">The page you&rsquo;re looking for doesn&rsquo;t exist.</p>
      <Link
        to="/"
        className="mt-8 font-medium text-text underline hover:text-text-2">
        Back to home
      </Link>
    </main>
  );
}
