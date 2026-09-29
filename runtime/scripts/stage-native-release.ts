import { readFile, writeFile } from 'node:fs/promises';
import { Pool } from 'pg';
import { PostgresDownloadCatalog } from '../packages/data-access/src/download-catalog.ts';
import {
  stageNativeRelease,
  applyNativeReceipt,
  stagedDraftIdentity,
  type StagedNativeReceipt,
} from '../packages/data-access/src/native-release-staging.ts';
import { verifyPublicAsset } from '../packages/data-access/src/release-asset-verification.ts';
import { publishReleaseCatalog } from '../packages/data-access/src/release-catalog-publication.ts';
import { platformKeys, type PlatformKey } from '../deploy/download-page/manifest.mjs';

const [mode, source, pipeline] = process.argv.slice(2);
if (
  !['prepare', 'register', 'promote'].includes(mode ?? '') ||
  !/^[a-f0-9]{40}$/.test(source ?? '') ||
  !/^\d+-\d+$/.test(pipeline ?? '')
)
  throw new Error('Native release mode, reviewed source and run-attempt required');
const readJson = async (file: string) => JSON.parse(await readFile(file, 'utf8'));
const required = (name: string) => {
  if (!process.env[name]) throw new Error(`${name} required`);
  return process.env[name]!;
};
const pool = new Pool({ connectionString: required('DATABASE_URL'), max: 2 });
try {
  const catalog = new PostgresDownloadCatalog(pool);
  if (mode === 'prepare') {
    const current = await catalog.current();
    if (!current) throw new Error('Initialize the download catalog before native publication');
    const request = await readJson('/release/upload-request.json');
    if (request.sourceRevision !== source) throw new Error('Native request source mismatch');
    if (!platformKeys.includes(request.platform)) throw new Error('Explicit native platform required');
    if (request.nativeAcceptance !== 'passed')
      throw new Error('Accepted native artifact must carry a real native acceptance result');
    const plan = await readJson('/release/release-plan.json');
    if (plan.version !== request.artifact?.version && request.artifact?.version !== undefined)
      throw new Error('Release plan version differs from the accepted native artifact');
    const manifest = stageNativeRelease(current.manifest, plan, source!);
    await writeFile('/release/releases.json', JSON.stringify(manifest));
    await writeFile(
      '/release/draft.json',
      JSON.stringify({ manifest, expectedCurrent: current.digest, platform: request.platform }),
    );
  } else if (mode === 'register') {
    const candidate = await readJson('/release/accepted-artifact.json');
    const draft = await readJson('/release/draft.json');
    if (
      candidate.sourceRevision !== source ||
      candidate.platform !== draft.platform ||
      !platformKeys.includes(candidate.platform as PlatformKey) ||
      candidate.nativeAcceptance !== 'passed' ||
      candidate.version !== draft.manifest.currentVersion
    )
      throw new Error('Accepted native artifact provenance mismatch');
    await verifyPublicAsset(candidate.asset.url, candidate.size, candidate.sha256);
    const receipt: StagedNativeReceipt = {
      ...candidate,
      expectedCurrent: draft.expectedCurrent,
      draftIdentity: stagedDraftIdentity(draft),
      verifiedAt: new Date().toISOString(),
    };
    await writeFile('/release/receipt.json', JSON.stringify(receipt));
    process.stdout.write(
      JSON.stringify({
        phase: 'native-cos-registered',
        platform: receipt.platform,
        bytes: receipt.size,
        sha256: receipt.sha256,
      }) + '\n',
    );
  } else {
    const draft = await readJson('/release/draft.json');
    const receipt: StagedNativeReceipt = await readJson('/release/receipt.json');
    if (receipt.expectedCurrent !== draft.expectedCurrent)
      throw new Error('Native receipt observed a different catalog revision');
    const manifest = applyNativeReceipt(draft, receipt, source!);
    const digest = await publishReleaseCatalog({
      catalog,
      manifest,
      receipts: [receipt],
      sourceRevision: source!,
      pipelineId: pipeline!,
      expectedCurrent: draft.expectedCurrent,
      bootstrap: false,
      storage: {
        bucket: required('STORAGE_S3_BUCKET'),
        region: required('STORAGE_S3_REGION'),
        prefix: process.env.STORAGE_S3_PREFIX ?? 'workdude',
      },
    });
    await writeFile('/release/publication.json', JSON.stringify({ digest, source, pipeline }));
    process.stdout.write(JSON.stringify({ phase: 'native-catalog-published', digest }) + '\n');
  }
} finally {
  await pool.end();
}
