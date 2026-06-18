import { fetchAuthSession } from 'aws-amplify/auth';
import type { ServiceResult } from '../types/service.types';

// The Cognito Identity Pool credentials Amplify holds for the signed-in user.
type SessionCredentials = NonNullable<
  Awaited<ReturnType<typeof fetchAuthSession>>['credentials']
>;

// Fetch the signed-in user's scoped Identity Pool credentials (SPEC-011). Shared
// by the Athena and Glue client builders (SPEC-034 FR-001); `getS3Client` mirrors
// this inline because it additionally constructs a dev-only static client and sets
// checksum options. `forceRefresh` drives the credential-expiry retry path.
// Never throws — returns the ServiceResult error shape instead.
export async function getSessionCredentials(
  forceRefresh = false,
): Promise<ServiceResult<SessionCredentials>> {
  try {
    const session = await fetchAuthSession({ forceRefresh });
    if (!session.credentials) {
      return {
        success: false,
        error: { message: 'No AWS credentials — sign in required' },
      };
    }
    return { success: true, data: session.credentials };
  } catch (err) {
    const e = err as { message?: string; name?: string };
    return {
      success: false,
      error: {
        message: e.message ?? 'Failed to obtain AWS credentials',
        code: e.name,
      },
    };
  }
}
