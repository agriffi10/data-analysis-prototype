import {S3Client} from '@aws-sdk/client-s3';
import {fetchAuthSession} from 'aws-amplify/auth';
import type {ServiceResult} from '../types/service.types';

const accessKeyId = import.meta.env.VITE_AWS_ACCESS_KEY_ID as string | undefined;

// AWS SDK v3 defaults to adding a CRC32 integrity checksum on every request
// (requestChecksumCalculation: 'WHEN_SUPPORTED'). In the browser that breaks
// @aws-sdk/lib-storage MULTIPART uploads (SPEC-016): the per-part checksums don't
// make it into CompleteMultipartUpload, so S3 rejects large files with
// "checksum ... missing for part 1". Opt out so multipart works — S3 still has
// ETag/MD5 integrity and everything is over TLS.
const CHECKSUM_OPTS = {
  requestChecksumCalculation: 'WHEN_REQUIRED',
  responseChecksumValidation: 'WHEN_REQUIRED'
} as const;

// Every authenticated S3 read hits a STABLE URL (SigV4 auth is in headers, not the
// query string), and S3 returns no `Cache-Control`. The browser therefore applies
// heuristic HTTP caching and can serve a stale body for the SAME key indefinitely —
// the ETag never changes across fetches, so a re-read of a mutated object (the
// shared-connections cache, notifications inbox, query history/saved queries, and
// `ListObjectsV2` listings) silently returns the old contents. `cache: 'no-store'`
// on the fetch handler forces every request to the network, so re-reads reflect the
// current object. These are all live-data reads (no static-asset caching to lose).
const REQUEST_HANDLER = {cache: 'no-store'} as const;

// Dev-only anonymous/static client (SPEC-002): omitting credentials uses unsigned
// requests for public buckets. This path stays in place for the test bucket until
// SPEC-013 switches the browser onto the authenticated user-space bucket.
export const s3Client = new S3Client({
  region: import.meta.env.VITE_AWS_REGION,
  ...CHECKSUM_OPTS,
  requestHandler: REQUEST_HANDLER,
  ...(accessKeyId
    ? {
        credentials: {
          accessKeyId,
          secretAccessKey: import.meta.env.VITE_AWS_SECRET_ACCESS_KEY as string
        }
      }
    : {})
});

// Authenticated S3 client (SPEC-011). Credentials come from the Cognito Identity
// Pool via Amplify's fetchAuthSession() — no STS SDK, no role ARN in app code.
// The Identity Pool stamps the `username` principal tag server-side; SPEC-013's
// role policy scopes S3 access to the user's own prefix with it.
//
// On an S3 call failing with a credential-expiry error, callers retry once with
// getS3Client(true) — Amplify refreshes the underlying session and credentials.
// Never throws — returns the ServiceResult error shape instead.
export async function getS3Client(forceRefresh = false): Promise<ServiceResult<S3Client>> {
  try {
    const session = await fetchAuthSession({forceRefresh});
    if (!session.credentials) {
      return {
        success: false,
        error: {message: 'No AWS credentials — sign in required'}
      };
    }
    return {
      success: true,
      data: new S3Client({
        region: import.meta.env.VITE_AWS_REGION,
        credentials: session.credentials,
        ...CHECKSUM_OPTS,
        requestHandler: REQUEST_HANDLER
      })
    };
  } catch (err) {
    const e = err as {message?: string; name?: string};
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain AWS credentials',
        code: e.name
      }
    };
  }
}
