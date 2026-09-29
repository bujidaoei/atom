import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { open, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { HeadObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { releaseAssetObjectKey } from '../packages/data-access/src/object-storage.ts';
import { verifyPublicAsset } from '../packages/data-access/src/release-asset-verification.ts';
import { platformKeys, validateManifest, type PlatformKey } from '../deploy/download-page/manifest.mjs';

const { values } = parseArgs({
  options: {
    file: { type: 'string' },
    version: { type: 'string' },
    platform: { type: 'string' },
    sha256: { type: 'string' },
    manifest: { type: 'string', default: 'deploy/download-page/data/releases.json' },
    verify: { type: 'boolean', default: false },
  },
});
const manifestPath = resolve(values.manifest);
const lockPath = `${manifestPath}.publish.lock`;
const lock = values.verify ? undefined : await open(lockPath, 'wx', 0o600);
try {
  const original = await readFile(manifestPath, 'utf8');
  const manifest = validateManifest(JSON.parse(original));
  if (values.verify) {
    for (const release of manifest.releases) {
      for (const asset of Object.values(release.platforms)) {
        if (asset.status !== 'available') continue;
        await verifyPublicAsset(asset.url!, asset.size!, asset.sha256!);
        process.stdout.write(`Verified ${release.version} ${asset.file}\n`);
      }
    }
  } else {
    if (
      !values.file ||
      !values.version ||
      !values.platform ||
      !platformKeys.includes(values.platform as PlatformKey) ||
      !/^[a-f0-9]{64}$/.test(values.sha256 ?? '')
    ) {
      throw new Error(
        'Required: --file=<native-package> --version=<version> --platform=windows|linux|macosIntel|macosArm --sha256=<verified-build-digest>; or --verify',
      );
    }
    const release = manifest.releases.find((item) => item.version === values.version);
    if (!release) throw new Error('Add reviewed release notes and platform metadata before publishing');
    const file = resolve(values.file);
    const info = await stat(file);
    if (!info.isFile() || info.size <= 0) throw new Error('Expected a nonempty native package');
    const sha256 = await hashStream(createReadStream(file));
    if (sha256 !== values.sha256) throw new Error('Source package differs from reviewed build digest');
    const platform = values.platform as PlatformKey;
    const extensions = { windows: '.exe', linux: '.deb', macosIntel: '.dmg', macosArm: '.dmg' };
    if (
      !basename(file).endsWith(extensions[platform]) ||
      !(
        basename(file).includes(release.version) ||
        (platform === 'linux' && basename(file).includes(release.version.replace('-', '.')))
      )
    )
      throw new Error('Package platform/version mismatch');
    const bucket = required('STORAGE_S3_BUCKET');
    const region = required('STORAGE_S3_REGION');
    const client = new S3Client({
      requestChecksumCalculation: 'WHEN_REQUIRED',
      endpoint: required('STORAGE_S3_ENDPOINT'),
      region,
      credentials: {
        accessKeyId: required('STORAGE_S3_ACCESS_KEY'),
        secretAccessKey: required('STORAGE_S3_SECRET_KEY'),
      },
    });
    const key = releaseAssetObjectKey(
      process.env.STORAGE_S3_PREFIX ?? 'workdude',
      release.version,
      basename(file),
      sha256,
    );
    const url = `https://${bucket}.cos.${region}.myqcloud.com/${key}`;
    const nextAsset = {
      ...release.platforms[platform],
      status: 'available' as const,
      file: basename(file),
      size: info.size,
      sha256,
      storage: 'cos',
      objectKey: key,
      url,
    };
    const previousAsset = release.platforms[platform];
    delete nextAsset.reason;
    if (
      previousAsset.status === 'available' &&
      (previousAsset.sha256 !== sha256 || previousAsset.url !== url)
    )
      throw new Error('Published identity is immutable; use a new version');
    release.platforms[platform] = nextAsset;
    validateManifest(manifest);
    let exists = false;
    try {
      const head = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
      exists = true;
      if (head.ContentLength !== info.size || (head.Metadata?.sha256 && head.Metadata.sha256 !== sha256))
        throw new Error('Existing object identity conflict');
    } catch (error) {
      if ((error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode !== 404)
        throw error;
    }
    if (!exists) {
      const started = Date.now();
      await client.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: key,
          Body: createReadStream(file),
          ContentLength: info.size,
          ContentType: contentType(platform),
          ContentDisposition: `attachment; filename="${basename(file)}"`,
          CacheControl: 'public, max-age=31536000, immutable',
          Metadata: { sha256 },
          IfNoneMatch: '*',
        }),
      );
      process.stdout.write(
        `${JSON.stringify({ phase: 'server-to-cos-upload', file: basename(file), bytes: info.size, elapsedSeconds: (Date.now() - started) / 1000 })}\n`,
      );
    }
    await verifyPublicAsset(url, info.size, sha256);
    if ((await readFile(manifestPath, 'utf8')) !== original)
      throw new Error('Manifest changed during publication; rerun against the new revision');
    manifest.generatedAt = new Date().toISOString();
    const temporary = `${manifestPath}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' });
    await rename(temporary, manifestPath);
    process.stdout.write(
      `${JSON.stringify({ file: basename(file), version: release.version, platform, bytes: info.size, sha256, key, uploaded: !exists })}\n`,
    );
  }
} finally {
  if (lock) {
    await lock.close();
    await unlink(lockPath);
  }
}
function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}
async function hashStream(stream: AsyncIterable<Uint8Array>): Promise<string> {
  const hash = createHash('sha256');
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest('hex');
}
function contentType(platform: PlatformKey): string {
  return platform === 'windows'
    ? 'application/vnd.microsoft.portable-executable'
    : platform === 'linux'
      ? 'application/vnd.debian.binary-package'
      : 'application/x-apple-diskimage';
}
