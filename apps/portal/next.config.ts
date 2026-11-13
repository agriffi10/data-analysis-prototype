import path from 'node:path';
import type {NextConfig} from 'next';
import {LOCKDOWN_POLICY, SECURITY_HEADERS} from './src/lib/securityHeaders';

/**
 * The floor for a request that carries a body: the security headers and a policy that runs nothing.
 *
 * Such a request never reaches the proxy (see `src/proxy.ts` for why), so the proxy's headers never
 * reach its response. No page takes a body, so nothing it answers needs to run script.
 */
const BODIED_REQUEST_HEADERS = [
  ...Object.entries(SECURITY_HEADERS).map(([key, value]) => ({key, value})),
  {key: 'Content-Security-Policy', value: LOCKDOWN_POLICY}
];

/**
 * The portal's Next.js configuration.
 *
 * `typescript.ignoreBuildErrors` does not lower the type gate: `npm run build` runs `tsc -b` first.
 * Next's own check runs `tsc --project tsconfig.json`, and that file is a solution with no files of
 * its own, so the check passes a planted type error while printing that it ran.
 */
const nextConfig: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.join(import.meta.dirname, '../..'),
  poweredByHeader: false,
  agentRules: false,
  typescript: {ignoreBuildErrors: true},
  async headers() {
    return [
      {source: '/:path*', has: [{type: 'header', key: 'content-length'}], headers: BODIED_REQUEST_HEADERS},
      {source: '/:path*', has: [{type: 'header', key: 'transfer-encoding'}], headers: BODIED_REQUEST_HEADERS}
    ];
  }
};

export default nextConfig;
