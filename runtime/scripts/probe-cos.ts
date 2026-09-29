import { S3ObjectStorage } from '../packages/data-access/src/object-storage.ts';

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const storage = new S3ObjectStorage({
  endpoint: required('STORAGE_S3_ENDPOINT'),
  accessKeyId: required('STORAGE_S3_ACCESS_KEY'),
  secretAccessKey: required('STORAGE_S3_SECRET_KEY'),
  bucket: required('STORAGE_S3_BUCKET'),
  region: required('STORAGE_S3_REGION'),
  prefix: process.env.STORAGE_S3_PREFIX ?? 'workdude',
  ...(process.env.STORAGE_PUBLIC_URL_BASE ? { publicUrlBase: process.env.STORAGE_PUBLIC_URL_BASE } : {}),
});

await storage.probe();
process.stdout.write('COS probe completed\n');
