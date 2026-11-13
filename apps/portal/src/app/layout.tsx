import type {ReactNode} from 'react';
import {headers} from 'next/headers';
import '../index.css';

/**
 * Every route renders per request, because only a dynamically rendered page carries a nonce: a
 * prerendered one is built before any request exists, and its scripts are blocked by the policy.
 */
export const dynamic = 'force-dynamic';

/**
 * The root layout: the document every page renders into, in place of the old `index.html`.
 *
 * `theme-init.js` is a blocking script in `<head>` so the page never paints light on its way to
 * dark. It stamps `data-theme` on `<html>` before React hydrates, which is why `<html>` suppresses
 * the hydration warning for its own attributes. It carries the request's nonce, read from the
 * header the request proxy sets; Next stamps the same nonce on every script it emits.
 *
 * @param props.children - The matched page.
 * @returns The document.
 */
export default async function RootLayout({children}: {children: ReactNode}) {
  const nonce = (await headers()).get('x-nonce') ?? undefined;
  return (
    <html
      lang="en"
      suppressHydrationWarning>
      <head>
        <link
          rel="icon"
          type="image/svg+xml"
          href="/favicon.svg"
        />
        <title>Data Quarry</title>
        <script
          src="/theme-init.js"
          nonce={nonce}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
