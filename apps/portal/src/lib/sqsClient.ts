import {SQSClient} from '@aws-sdk/client-sqs';
import {getSessionCredentials} from './awsCredentials';
import type {ServiceResult} from '../types/service.types';

// SQS client for the shared-space control plane (SPEC-051). The browser's ONLY
// privileged shared-space action is sqs:SendMessage to the request queue (SPEC-056
// portal-role grant); all provisioning happens server-side in the pipeline. Built
// from the signed-in user's Identity Pool credentials, mirroring the S3/Athena/Glue
// client builders (SPEC-034). `forceRefresh` drives the credential-expiry retry
// path (withCredentialRetry). Never throws — returns the ServiceResult error shape.
export async function getSqsClient(forceRefresh = false): Promise<ServiceResult<SQSClient>> {
  const creds = await getSessionCredentials(forceRefresh);
  if (!creds.success) return creds;
  return {
    success: true,
    data: new SQSClient({
      region: import.meta.env.VITE_AWS_REGION,
      credentials: creds.data
    })
  };
}
