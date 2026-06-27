import { AthenaClient } from '@aws-sdk/client-athena';
import { getSessionCredentials } from './awsCredentials';
import type { ServiceResult } from '../types/service.types';

// Authenticated Athena client (SPEC-034 FR-001). Built from the same Cognito
// Identity Pool credentials as getS3Client (via getSessionCredentials): the
// Identity Pool stamps the `username` principal tag server-side, and the portal
// role's analytics policy (SPEC-032 FR-006) scopes Athena to the shared workgroup
// and Glue to `database/${aws:PrincipalTag/username}`. On a call failing with a
// credential-expiry error, callers retry via withCredentialRetry(getAthenaClient,
// ...). Never throws — returns the ServiceResult error shape.
export async function getAthenaClient(forceRefresh = false): Promise<ServiceResult<AthenaClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new AthenaClient({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: creds.data,
    }),
  };
}
