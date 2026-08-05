import {S3Client} from '@aws-sdk/client-s3';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';

// Gated at the READ, not in the consumer. Vite statically replaces
// `import.meta.env.VITE_*` with a literal at build time, so a build with these
// set would inline the secret into the bundle no matter which caller later
// checks `DEV`. `import.meta.env.DEV` is replaced with `false` in a production
// build, so the whole branch below dead-code-eliminates before the value can be
// substituted. The consumer's own DEV check (fileBrowser.service.ts) stays —
// it gates the dev-unauth FEATURE; this one gates the SECRET.
const accessKeyId = import.meta.env.DEV ? (import.meta.env.VITE_AWS_ACCESS_KEY_ID as string | undefined) : undefined;

// AWS SDK v3 defaults to adding a CRC32 integrity checksum on every request
// (requestChecksumCalculation: 'WHEN_SUPPORTED'). In the browser that breaks
// @aws-sdk/lib-storage MULTIPART uploads: the per-part checksums don't make it
// into CompleteMultipartUpload, so S3 rejects large files with "checksum ...
// missing for part 1". Opt out so multipart works — S3 still has ETag/MD5
// integrity and everything is over TLS.
const CHECKSUM_OPTS = {
  requestChecksumCalculation: 'WHEN_REQUIRED',
  responseChecksumValidation: 'WHEN_REQUIRED'
} as const;

// Every authenticated S3 read hits a STABLE URL (SigV4 auth is in headers, not
// the query string), and S3 returns no `Cache-Control` — so the browser's
// heuristic HTTP cache can serve a stale body for the same key indefinitely,
// silently returning old contents for mutated objects and listings.
// `cache: 'no-store'` forces every request to the network. These are all
// live-data reads (no static-asset caching to lose).
const REQUEST_HANDLER = {cache: 'no-store'} as const;

/**
 * Dev-only anonymous/static client for the unauthenticated test-bucket path.
 * Omitting credentials sends unsigned requests (public buckets only).
 */
export const s3Client = new S3Client({
  region: import.meta.env.VITE_AWS_REGION,
  ...CHECKSUM_OPTS,
  requestHandler: REQUEST_HANDLER,
  ...(import.meta.env.DEV && accessKeyId
    ? {
        credentials: {
          accessKeyId,
          secretAccessKey: import.meta.env.VITE_AWS_SECRET_ACCESS_KEY as string
        }
      }
    : {})
});

/**
 * Builds an S3Client from the signed-in user's Identity Pool credentials — no
 * STS SDK, no role ARN in app code.
 *
 * The Identity Pool stamps the `username` principal tag server-side and the
 * role policy scopes S3 access to the user's own prefix with it. On a
 * credential-expiry error, callers retry once with `getS3Client(true)` —
 * Amplify refreshes the underlying session. Never throws — returns a
 * ServiceResult.
 *
 * Credentials come from `getSessionCredentials`, like the Athena/Glue/SQS
 * builders, rather than a duplicated `fetchAuthSession`. That duplication is
 * what left the no-credentials failure without `code: 'NotAuthenticated'`, so a
 * lapsed session showed the generic message on every S3-backed screen while the
 * other three said "Sign in to continue."
 */
export async function getS3Client(forceRefresh = false): Promise<ServiceResult<S3Client>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new S3Client({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: creds.data,
      ...CHECKSUM_OPTS,
      requestHandler: REQUEST_HANDLER
    })
  };
}
