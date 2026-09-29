import { readFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { Pool } from 'pg';
import { PostgresDownloadCatalog } from '../packages/data-access/src/download-catalog.ts';
import { publishReleaseCatalog } from '../packages/data-access/src/release-catalog-publication.ts';

const { values } = parseArgs({
  options: {
    manifest: { type: 'string' },
    receipts: { type: 'string' },
    source: { type: 'string' },
    pipeline: { type: 'string' },
    expected: { type: 'string' },
    bootstrap: { type: 'boolean', default: false },
    rollback: { type: 'string' },
  },
});
if (!values.expected || !(values.expected === 'empty' || /^[a-f0-9]{64}$/.test(values.expected)))
  throw new Error('--expected must be empty or the observed catalog digest');
function required(name: string): string {
  if (!process.env[name]) throw new Error(`${name} is required`);
  return process.env[name]!;
}
const pool = new Pool({ connectionString: required('DATABASE_URL'), max: 2 });
try {
  const catalog = new PostgresDownloadCatalog(pool);
  const initialized = values.bootstrap ? await catalog.current() : undefined;
  let digest: string;
  if (initialized) {
    // Bootstrap is initialize-if-empty; later deployments must not rewind the
    // database to an older JSON file bundled with application source.
    digest = initialized.digest;
  } else if (values.rollback) {
    await catalog.rollback(values.rollback, values.expected);
    digest = values.rollback;
  } else {
    if (!values.manifest || !values.source || !values.pipeline || (!values.bootstrap && !values.receipts))
      throw new Error('--manifest, --source, --pipeline and native --receipts required');
    digest = await publishReleaseCatalog({
      catalog,
      manifest: JSON.parse(await readFile(values.manifest, 'utf8')),
      sourceRevision: values.source,
      pipelineId: values.pipeline,
      expectedCurrent: values.expected === 'empty' ? null : values.expected,
      bootstrap: values.bootstrap,
      receipts: values.receipts ? JSON.parse(await readFile(values.receipts, 'utf8')) : [],
      storage: {
        bucket: required('STORAGE_S3_BUCKET'),
        region: required('STORAGE_S3_REGION'),
        prefix: process.env.STORAGE_S3_PREFIX ?? 'workdude',
      },
    });
  }
  process.stdout.write(JSON.stringify({ phase: 'catalog-published', digest }) + '\n');
} finally {
  await pool.end();
}
