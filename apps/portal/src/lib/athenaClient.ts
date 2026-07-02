import {AthenaClient} from '@aws-sdk/client-athena';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';

/**
 * Builds an AthenaClient from the signed-in user's Identity Pool credentials.
 *
 * IAM (not app code) scopes access: the Identity Pool stamps the `username`
 * principal tag server-side and the portal role restricts Athena/Glue with it.
 * Pass `forceRefresh` on credential expiry (callers wrap calls in
 * `withCredentialRetry(getAthenaClient, …)`). Never throws — returns a
 * ServiceResult.
 */
export async function getAthenaClient(forceRefresh = false): Promise<ServiceResult<AthenaClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new AthenaClient({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: creds.data
    })
  };
}
