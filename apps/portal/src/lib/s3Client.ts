import { S3Client } from '@aws-sdk/client-s3';

const accessKeyId = import.meta.env.VITE_AWS_ACCESS_KEY_ID as string | undefined;

// Dev-only anonymous fallback: omitting credentials uses unsigned requests for public
// buckets. Production auth uses STS-issued credentials obtained via the auth flow (future spec).
export const s3Client = new S3Client({
  region: import.meta.env.VITE_AWS_REGION,
  ...(accessKeyId
    ? {
        credentials: {
          accessKeyId,
          secretAccessKey: import.meta.env.VITE_AWS_SECRET_ACCESS_KEY as string,
        },
      }
    : {}),
});
