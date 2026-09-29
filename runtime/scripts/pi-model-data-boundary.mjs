import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { basename, resolve } from 'node:path';

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function sortedRecord(entries) {
  return Object.fromEntries(
    [...entries].sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
  );
}

async function exactModelDataFiles(root, enforcePlain = true) {
  const entries = await readdir(root, { withFileTypes: true });
  if (
    enforcePlain &&
    entries.some(
      (entry) => !entry.isFile() || (!entry.name.endsWith('.json') && entry.name !== '.manifest.json'),
    )
  ) {
    throw new Error('The pinned Pi model-data cache must contain plain JSON files only');
  }
  return entries
    .filter((entry) => entry.isFile() && (entry.name.endsWith('.json') || entry.name === '.manifest.json'))
    .map(({ name }) => name)
    .sort();
}

export async function verifyPiModelDataCache({ cacheRoot, officialRoot, verifyIntegrity = true } = {}) {
  const root = resolve(cacheRoot);
  const manifest = JSON.parse(await readFile(resolve(root, '.manifest.json'), 'utf8'));
  if (
    !isRecord(manifest) ||
    manifest.schemaVersion !== 3 ||
    typeof manifest.generatedAt !== 'string' ||
    Number.isNaN(Date.parse(manifest.generatedAt)) ||
    !/^[a-f0-9]{64}$/u.test(String(manifest.structureHash)) ||
    !isRecord(manifest.files)
  ) {
    throw new Error('The pinned Pi model-data cache manifest is invalid');
  }

  const manifestDataNames = Object.keys(manifest.files).sort();
  if (
    manifestDataNames.some(
      (name) =>
        basename(name) !== name ||
        !name.endsWith('.json') ||
        !/^[a-f0-9]{64}$/u.test(String(manifest.files[name])),
    )
  ) {
    throw new Error('The pinned Pi model-data cache manifest entry is invalid');
  }
  const actualNames = await exactModelDataFiles(root, verifyIntegrity);
  const actualDataNames = actualNames.filter((name) => name !== '.manifest.json');
  const expectedNames = ['.manifest.json', ...manifestDataNames].sort();
  if (verifyIntegrity && JSON.stringify(actualNames) !== JSON.stringify(expectedNames)) {
    throw new Error('The pinned Pi model-data cache does not match its manifest file list');
  }

  if (officialRoot) {
    const officialNames = await exactModelDataFiles(resolve(officialRoot));
    if (JSON.stringify(officialNames) !== JSON.stringify(expectedNames)) {
      throw new Error('The pinned Pi model-data cache does not match the official Pi source file list');
    }
  }

  const structureEntries = [];
  const providers = new Set();
  const endpoints = new Set();
  const dataNames = verifyIntegrity ? manifestDataNames : actualDataNames;
  for (const name of dataNames) {
    const content = await readFile(resolve(root, name));
    if (verifyIntegrity && sha256(content) !== manifest.files[name]) {
      throw new Error(`The pinned Pi model-data cache manifest SHA-256 mismatch: ${name}`);
    }
    if (officialRoot) {
      const officialContent = await readFile(resolve(officialRoot, name));
      if (!content.equals(officialContent)) {
        throw new Error(`The pinned Pi model-data cache differs from the official Pi source: ${name}`);
      }
    }

    const groups = JSON.parse(content.toString('utf8'));
    if (!isRecord(groups)) throw new Error(`The pinned Pi model-data cache file is invalid: ${name}`);
    const modelApis = new Map();
    for (const [api, models] of Object.entries(groups)) {
      if (!isRecord(models)) throw new Error(`The pinned Pi model-data API group is invalid: ${name}/${api}`);
      for (const [modelId, model] of Object.entries(models)) {
        if (modelApis.has(modelId))
          throw new Error(`The pinned Pi model-data model is duplicated: ${name}/${modelId}`);
        modelApis.set(modelId, api);
        if (isRecord(model)) {
          if (typeof model.provider === 'string' && model.provider) providers.add(model.provider);
          if (typeof model.baseUrl === 'string' && /^https:\/\//u.test(model.baseUrl))
            endpoints.add(model.baseUrl);
        }
      }
    }
    if (modelApis.size === 0) throw new Error(`The pinned Pi model-data file has no models: ${name}`);
    structureEntries.push([name.slice(0, -'.json'.length), sortedRecord(modelApis)]);
  }
  const actualStructureHash = sha256(JSON.stringify(sortedRecord(structureEntries)));
  if (verifyIntegrity && actualStructureHash !== manifest.structureHash) {
    throw new Error('The pinned Pi model-data structure hash does not match the generated catalog');
  }
  if (providers.size === 0 || endpoints.size === 0) {
    throw new Error('The pinned Pi model-data cache has no provider endpoint inventory');
  }
  return {
    manifest,
    providers: [...providers].sort(),
    endpoints: [...endpoints].sort(),
    fileCount: dataNames.length,
  };
}
