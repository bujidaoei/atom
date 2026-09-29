import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { open, readFile } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  HeadObjectCommand,
  S3Client,
  UploadPartCommand,
} from '@aws-sdk/client-s3';
import { Pool } from 'pg';
import { PostgresDownloadCatalog } from '../packages/data-access/src/download-catalog.ts';
import { releaseAssetObjectKey } from '../packages/data-access/src/object-storage.ts';
import {
  assembleNativePublication,
  nativeInstallerFileName,
} from '../packages/data-access/src/native-release-staging.ts';
import { publishReleaseCatalog } from '../packages/data-access/src/release-catalog-publication.ts';
import { platformKeys, type PlatformKey } from '../deploy/download-page/manifest.mjs';

const partSize = 8 * 1024 * 1024;
const workers = 4;

const { values } = parseArgs({
  options: {
    file: { type: 'string' },
    platform: { type: 'string', default: 'windows' },
    source: { type: 'string' },
    pipeline: { type: 'string' },
    notes: { type: 'string' },
  },
});

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function isMissingObject(error: unknown): boolean {
  const named = error as { name?: string; $metadata?: { httpStatusCode?: number } };
  return named.name === 'NotFound' || named.name === 'NoSuchKey' || named.$metadata?.httpStatusCode === 404;
}

function installerVersion(fileName: string, platform: PlatformKey): string {
  const suffix = nativeInstallerFileName('VERSION', platform).slice('QoderWake-VERSION'.length);
  if (!fileName.startsWith('QoderWake-') || !fileName.endsWith(suffix)) {
    throw new Error('Installer file name does not match the selected platform');
  }
  return fileName.slice('QoderWake-'.length, fileName.length - suffix.length);
}

async function hashFile(file: string): Promise<{ sha256: string; size: number }> {
  const hash = createHash('sha256');
  let size = 0;
  for await (const chunk of createReadStream(file)) {
    size += chunk.length;
    hash.update(chunk);
  }
  return { sha256: hash.digest('hex'), size };
}

async function uploadInstaller(input: {
  client: S3Client;
  bucket: string;
  key: string;
  file: string;
  size: number;
  sha256: string;
}): Promise<'uploaded' | 'reused'> {
  try {
    const head = await input.client.send(new HeadObjectCommand({ Bucket: input.bucket, Key: input.key }));
    if (head.ContentLength !== input.size)
      throw new Error('Existing COS object does not match this installer');
    return 'reused';
  } catch (error) {
    if (!isMissingObject(error)) throw error;
  }
  const created = await input.client.send(
    new CreateMultipartUploadCommand({
      Bucket: input.bucket,
      Key: input.key,
      ContentType: 'application/octet-stream',
      ContentDisposition: `attachment; filename="${basename(input.file)}"`,
      CacheControl: 'public, max-age=31536000, immutable',
      Metadata: { sha256: input.sha256 },
    }),
  );
  if (!created.UploadId) throw new Error('COS did not return an upload id');
  const uploadId = created.UploadId;
  const partCount = Math.ceil(input.size / partSize);
  const completed: Array<{ PartNumber: number; ETag: string }> = [];
  let next = 0;
  const started = Date.now();
  try {
    async function worker() {
      while (next < partCount) {
        const index = next++;
        const offset = index * partSize;
        const size = Math.min(partSize, input.size - offset);
        const bytes = Buffer.alloc(size);
        const handle = await open(input.file, 'r');
        try {
          let received = 0;
          while (received < size) {
            const { bytesRead } = await handle.read(bytes, received, size - received, offset + received);
            if (!bytesRead) throw new Error('Installer changed while it was uploading');
            received += bytesRead;
          }
        } finally {
          await handle.close();
        }
        const uploaded = await input.client.send(
          new UploadPartCommand({
            Bucket: input.bucket,
            Key: input.key,
            UploadId: uploadId,
            PartNumber: index + 1,
            Body: bytes,
            ContentLength: size,
          }),
        );
        if (!uploaded.ETag) throw new Error('COS part upload did not return an ETag');
        completed.push({ PartNumber: index + 1, ETag: uploaded.ETag });
      }
    }
    await Promise.all(Array.from({ length: Math.min(workers, partCount) }, () => worker()));
    completed.sort((left, right) => left.PartNumber - right.PartNumber);
    await input.client.send(
      new CompleteMultipartUploadCommand({
        Bucket: input.bucket,
        Key: input.key,
        UploadId: uploadId,
        MultipartUpload: { Parts: completed },
      }),
    );
  } catch (error) {
    await input.client
      .send(new AbortMultipartUploadCommand({ Bucket: input.bucket, Key: input.key, UploadId: uploadId }))
      .catch(() => undefined);
    throw error;
  }
  process.stdout.write(
    `${JSON.stringify({ phase: 'cos-upload', bytes: input.size, parts: partCount, elapsedSeconds: (Date.now() - started) / 1000 })}\n`,
  );
  return 'uploaded';
}

const platform = values.platform as PlatformKey;
if (!values.file || !values.source || !values.notes || !platformKeys.includes(platform)) {
  throw new Error(
    'Required: --file=<installer> --source=<40-character git sha> --notes=<release-notes.json> [--platform=windows]',
  );
}
if (!/^[a-f0-9]{40}$/.test(values.source))
  throw new Error('Source must be the 40-character commit that built the installer');
const pipeline = values.pipeline ?? `${Date.now()}-1`;
if (!/^\d+-\d+$/.test(pipeline)) throw new Error('Pipeline id must look like <number>-<attempt>');

const notes = JSON.parse(await readFile(values.notes, 'utf8')) as {
  date?: string;
  summary?: string;
  changes?: unknown;
  fixes?: unknown;
  notesBasis?: string;
};
if (typeof notes.summary !== 'string' || !notes.summary.trim())
  throw new Error('Release notes need a summary');
if (!Array.isArray(notes.changes) || !Array.isArray(notes.fixes))
  throw new Error('Release notes need changes and fixes arrays');
if ([...notes.changes, ...notes.fixes].some((item) => typeof item !== 'string' || !item.trim())) {
  throw new Error('Release notes must be non-empty text');
}
if (notes.changes.length + notes.fixes.length === 0)
  throw new Error('Release notes need at least one change or fix');
const date =
  notes.date && /^\d{4}-\d{2}-\d{2}$/.test(notes.date) ? notes.date : new Date().toISOString().slice(0, 10);

const file = resolve(values.file);
const version = installerVersion(basename(file), platform);
const identity = await hashFile(file);
const bucket = required('STORAGE_S3_BUCKET');
const region = required('STORAGE_S3_REGION');
const prefix = process.env.STORAGE_S3_PREFIX ?? 'workdude';
const client = new S3Client({
  requestChecksumCalculation: 'WHEN_REQUIRED',
  endpoint: required('STORAGE_S3_ENDPOINT'),
  region,
  credentials: {
    accessKeyId: required('STORAGE_S3_ACCESS_KEY'),
    secretAccessKey: required('STORAGE_S3_SECRET_KEY'),
  },
});
const pool = new Pool({ connectionString: required('DATABASE_URL'), max: 2 });
try {
  const catalog = new PostgresDownloadCatalog(pool);
  const current = await catalog.current();
  if (!current) throw new Error('Initialize the download catalog before publishing');
  const plan = {
    version,
    date,
    summary: notes.summary,
    changes: notes.changes as string[],
    fixes: notes.fixes as string[],
    notesBasis: notes.notesBasis ?? `Compared with ${current.manifest.currentVersion}`,
  };
  const storage = { bucket, region, prefix };
  const key = releaseAssetObjectKey(prefix, version, basename(file), identity.sha256);
  const upload = await uploadInstaller({
    client,
    bucket,
    key,
    file,
    size: identity.size,
    sha256: identity.sha256,
  });
  const assembled = assembleNativePublication({
    current: current.manifest,
    plan,
    sourceRevision: values.source,
    expectedCurrent: current.digest,
    platform,
    size: identity.size,
    sha256: identity.sha256,
    storage,
    verifiedAt: new Date().toISOString(),
  });
  if (assembled.receipt.asset.objectKey !== key)
    throw new Error('Catalog destination differs from the uploaded object');
  const digest = await publishReleaseCatalog({
    catalog,
    manifest: assembled.manifest,
    receipts: [assembled.receipt],
    sourceRevision: values.source,
    pipelineId: pipeline,
    expectedCurrent: current.digest,
    bootstrap: false,
    storage,
  });
  process.stdout.write(
    `${JSON.stringify({ phase: 'native-release-published', version, platform, upload, digest, sha256: identity.sha256, bytes: identity.size })}\n`,
  );
} finally {
  client.destroy();
  await pool.end();
}
