import {S3Client} from '@aws-sdk/client-s3';
import {fetchAuthSession} from 'aws-amplify/auth';
import type {ServiceResult} from '../types/service.types';

const accessKeyId = import.meta.env.VITE_AWS_ACCESS_KEY_ID as string | undefined;

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
  ...(accessKeyId
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
 */
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
