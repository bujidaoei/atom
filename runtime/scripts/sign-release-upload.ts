import { createCipheriv, createPublicKey, publicEncrypt, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  HeadObjectCommand,
  S3Client,
  UploadPartCommand,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { releaseAssetObjectKey } from '../packages/data-access/src/object-storage.ts';
import { verifyPublicAsset } from '../packages/data-access/src/release-asset-verification.ts';
import { platformKeys, validateManifest, type PlatformKey } from '../deploy/download-page/manifest.mjs';

const manifest = validateManifest(JSON.parse(readFileSync('/release/releases.json', 'utf8')));
const release = manifest.releases.find((item) => item.version === manifest.currentVersion)!;
const request = JSON.parse(readFileSync('/release/upload-request.json', 'utf8'));
if (!platformKeys.includes(request.platform)) throw new Error('Explicit native platform required');
const platform = request.platform as PlatformKey;
let asset = release.platforms[platform];
if (request.artifact) {
  const artifact = request.artifact;
  const suffix = {
    windows: 'Windows-x64-Setup.exe',
    linux: 'Linux-x64.deb',
    macosIntel: 'macOS-x64.dmg',
    macosArm: 'macOS-arm64.dmg',
  }[platform];
  if (
    artifact.file !== `QoderWake-${release.version}-${suffix}` ||
    !Number.isSafeInteger(artifact.size) ||
    artifact.size <= 0 ||
    !/^[a-f0-9]{64}$/.test(artifact.sha256) ||
    !/^[a-f0-9]{40}$/.test(request.sourceRevision) ||
    request.nativeAcceptance !== 'passed'
  )
    throw new Error('Exact accepted native artifact identity required');
  if (
    asset.status === 'available' &&
    ['file', 'size', 'sha256'].some((key) => asset[key as keyof typeof asset] !== artifact[key])
  )
    throw new Error('Published installer identity is immutable');
  asset = { ...asset, file: artifact.file, size: artifact.size, sha256: artifact.sha256 };
}
if (!asset.file || !asset.size || !asset.sha256) throw new Error('Reviewed native installer is required');
const publicKey = createPublicKey({
  key: Buffer.from(request.publicKey, 'base64'),
  format: 'der',
  type: 'spki',
});
if (publicKey.asymmetricKeyType !== 'rsa' || (publicKey.asymmetricKeyDetails?.modulusLength ?? 0) < 2048)
  throw new Error('RSA recipient key required');
const partSize = 8 * 1024 * 1024;
if (
  !Array.isArray(request.partMD5) ||
  request.partMD5.length !== Math.ceil(asset.size! / partSize) ||
  request.partMD5.some((digest: string) => !/^[A-Za-z0-9+/]{22}==$/.test(digest))
)
  throw new Error('Exact per-part MD5 values required');
function required(name: string) {
  if (!process.env[name]) throw new Error(`${name} is required`);
  return process.env[name]!;
}
const bucket = required('STORAGE_S3_BUCKET');
const region = required('STORAGE_S3_REGION');
// A previously registered asset keeps its exact frozen object identity; a newly
// staged asset derives a content-addressed destination from the reviewed digest.
const key =
  asset.objectKey ??
  releaseAssetObjectKey(
    process.env.STORAGE_S3_PREFIX ?? 'workdude',
    release.version,
    asset.file!,
    asset.sha256!,
  );
const publicUrl = `https://${bucket}.cos.${region}.myqcloud.com/${key}`;
if (asset.objectKey && publicUrl !== asset.url)
  throw new Error('Server COS configuration differs from reviewed destination');
release.platforms[platform] = {
  ...asset,
  status: 'available',
  storage: 'cos',
  url: publicUrl,
  objectKey: key,
};
validateManifest(manifest);
if (request.artifact) {
  // Server-derived metadata is retained separately from the encrypted authority.
  // Registration must verify the actual public bytes before issuing a receipt.
  writeFileSync(
    '/release/accepted-artifact.json',
    JSON.stringify({
      platform,
      version: release.version,
      sourceRevision: request.sourceRevision,
      nativeAcceptance: request.nativeAcceptance,
      file: asset.file,
      size: asset.size,
      sha256: asset.sha256,
      asset: release.platforms[platform],
    }),
  );
}
const client = new S3Client({
  // Presigning has no body: an automatic CRC32 would describe empty bytes.
  // Bind each real part with its precomputed Content-MD5 instead.
  requestChecksumCalculation: 'WHEN_REQUIRED',
  endpoint: required('STORAGE_S3_ENDPOINT'),
  region,
  credentials: {
    accessKeyId: required('STORAGE_S3_ACCESS_KEY'),
    secretAccessKey: required('STORAGE_S3_SECRET_KEY'),
  },
});
client.middlewareStack.add(
  (next, context) => async (args) => {
    if (
      ['CreateMultipartUploadCommand', 'CompleteMultipartUploadCommand'].includes(context.commandName ?? '')
    )
      (args.request as { headers: Record<string, string> }).headers['x-cos-forbid-overwrite'] = 'true';
    return next(args);
  },
  { step: 'build' },
);
let existing = false;
try {
  await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
  existing = true;
} catch (error) {
  if ((error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode !== 404) throw error;
}
let payload: string;
if (existing) {
  await verifyPublicAsset(publicUrl, asset.size!, asset.sha256!);
  payload = JSON.stringify({
    verifiedExisting: true,
    publicUrl,
    file: asset.file,
    size: asset.size,
    sha256: asset.sha256,
    expiresAt: Date.now() + 1800_000,
  });
} else {
  const initiated = await client.send(
    new CreateMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      ContentType:
        platform === 'windows'
          ? 'application/vnd.microsoft.portable-executable'
          : platform === 'linux'
            ? 'application/vnd.debian.binary-package'
            : 'application/x-apple-diskimage',
      ContentDisposition: 'attachment; filename="' + asset.file + '"',
      CacheControl: 'public, max-age=31536000, immutable',
      Metadata: { sha256: asset.sha256! },
    }),
  );
  const uploadId = initiated.UploadId;
  if (!uploadId) throw new Error('COS did not return upload identity');
  try {
    const parts = await Promise.all(
      request.partMD5.map(async (md5: string, index: number) => {
        const size = Math.min(partSize, asset.size! - index * partSize);
        const url = await getSignedUrl(
          client,
          new UploadPartCommand({
            Bucket: bucket,
            Key: key,
            UploadId: uploadId,
            PartNumber: index + 1,
            ContentLength: size,
            ContentMD5: md5,
          }),
          { expiresIn: 1800 },
        );
        return { number: index + 1, offset: index * partSize, size, md5, url };
      }),
    );
    const completeUrl = await getSignedUrl(
      client,
      new CompleteMultipartUploadCommand({ Bucket: bucket, Key: key, UploadId: uploadId, IfNoneMatch: '*' }),
      { expiresIn: 1800 },
    );
    const abortUrl = await getSignedUrl(
      client,
      new AbortMultipartUploadCommand({ Bucket: bucket, Key: key, UploadId: uploadId }),
      { expiresIn: 1800 },
    );
    payload = JSON.stringify({
      uploadId,
      parts,
      completeUrl,
      abortUrl,
      publicUrl,
      file: asset.file,
      size: asset.size,
      sha256: asset.sha256,
      expiresAt: Date.now() + 1800_000,
    });
  } catch (error) {
    await client.send(new AbortMultipartUploadCommand({ Bucket: bucket, Key: key, UploadId: uploadId }));
    throw error;
  }
}
const secret = randomBytes(32);
const iv = randomBytes(12);
const cipher = createCipheriv('aes-256-gcm', secret, iv);
const ciphertext = Buffer.concat([cipher.update(payload, 'utf8'), cipher.final()]);
writeFileSync(
  '/release/upload-authorization.json',
  JSON.stringify({
    key: publicEncrypt({ key: publicKey, oaepHash: 'sha256' }, secret).toString('base64'),
    iv: iv.toString('base64'),
    tag: cipher.getAuthTag().toString('base64'),
    ciphertext: ciphertext.toString('base64'),
  }),
);
console.log(
  JSON.stringify({
    phase: 'upload-authorization',
    file: asset.file,
    bytes: asset.size,
    reused: existing,
    expiresInSeconds: 1800,
    encrypted: true,
  }),
);
