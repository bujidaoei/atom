import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';

import {
  publishPiBuildCacheGeneration,
  removePiBuildCacheScratch,
  resolveSafePiCacheLayout,
} from './pi-cache-publication.mjs';
import { verifyPiModelDataCache } from './pi-model-data-boundary.mjs';
import {
  capturePiSourceSnapshot,
  verifyIsolatedPiSourceTree,
  verifyPiSourceBoundary,
  verifyPiSourceSnapshot,
} from './pi-source-boundary.mjs';

const root = process.cwd();
const modelDataCacheRoot = resolve(root, 'deploy', 'compose', 'pi-model-data');
const piRoot = resolve(root, 'pi');

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function isMissing(error) {
  return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

async function runNpm(directory, args, label) {
  const npmCli =
    process.env.npm_execpath ||
    (process.platform === 'win32'
      ? resolve(dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
      : undefined);
  const command = npmCli ? process.execPath : 'npm';
  const commandArguments = [...(npmCli ? [npmCli] : []), ...args];
  await new Promise((resolvePromise, reject) => {
    const child = spawn(command, commandArguments, {
      cwd: directory,
      // Apply upstream npm defaults in the isolated upstream build. Product npm run
      // exports engine-strict=true; Pi's eval-only dependencies declare pnpm engines.
      // Keep the official lock unchanged and do not inherit that product policy.
      env: { ...process.env, npm_config_engine_strict: 'false', CI: '1' },
      stdio: 'inherit',
      windowsHide: true,
    });
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolvePromise();
        return;
      }
      reject(new Error(`${label} failed (${signal ?? `exit ${code}`})`));
    });
  });
}

async function installIsolatedDependencies(directory) {
  await runNpm(directory, ['ci', '--ignore-scripts'], 'The isolated Pi dependency install');
}

async function runOfflineBuild(directory) {
  await runNpm(directory, ['run', 'build:offline'], 'The isolated Pi offline build');
}

async function pruneRuntimeDependencies(directory) {
  await runNpm(
    directory,
    ['prune', '--omit=dev', '--ignore-scripts'],
    'The isolated Pi runtime dependency prune',
  );
}

async function discoverPackageManifests(stagedPiRoot) {
  const manifests = [];
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    const packageJson = entries.find((entry) => entry.isFile() && entry.name === 'package.json');
    if (packageJson) {
      const manifest = JSON.parse(await readFile(resolve(directory, packageJson.name), 'utf8'));
      if (typeof manifest.name === 'string' && manifest.name.length > 0) {
        manifests.push({
          name: manifest.name,
          relativeDirectory: relative(stagedPiRoot, directory).replaceAll('\\', '/'),
        });
      }
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || ['dist', 'node_modules'].includes(entry.name)) continue;
      await visit(resolve(directory, entry.name));
    }
  }
  await visit(resolve(stagedPiRoot, 'packages'));
  return manifests;
}

async function copyBuiltPackages(stagedPiRoot, publicationRoot, packageManifests) {
  const builtPackages = [];
  for (const packageManifest of packageManifests) {
    const stagedPackage = resolve(stagedPiRoot, packageManifest.relativeDirectory);
    const stagedDist = resolve(stagedPackage, 'dist');
    const distMetadata = await stat(stagedDist).catch((error) => {
      if (isMissing(error)) return undefined;
      throw error;
    });
    if (!distMetadata?.isDirectory()) continue;

    const publishedPackage = resolve(publicationRoot, packageManifest.relativeDirectory);
    await mkdir(publishedPackage, { recursive: true });
    await cp(resolve(stagedPackage, 'package.json'), resolve(publishedPackage, 'package.json'));
    await cp(stagedDist, resolve(publishedPackage, 'dist'), { recursive: true });
    builtPackages.push(packageManifest);
  }
  if (!builtPackages.some(({ name }) => name === '@earendil-works/pi-coding-agent')) {
    throw new Error('The isolated Pi build did not produce the coding-agent package');
  }
  return builtPackages;
}

async function hashPublishedArtifacts(publicationRoot) {
  const files = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.name === 'source-lock.json') continue;
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        files.push(relative(publicationRoot, path).replaceAll('\\', '/'));
      } else {
        throw new Error(`Unsupported entry in the Pi build cache: ${entry.name}`);
      }
    }
  }
  await visit(publicationRoot);
  const artifacts = {};
  const sortedFiles = files.sort();
  for (let offset = 0; offset < sortedFiles.length; offset += 64) {
    const batch = sortedFiles.slice(offset, offset + 64);
    const hashes = await Promise.all(
      batch.map(async (path) => [path, sha256(await readFile(resolve(publicationRoot, path)))]),
    );
    for (const [path, hash] of hashes) artifacts[path] = hash;
  }
  return artifacts;
}

function packageNameSegments(name) {
  const segments = name.split('/');
  const valid =
    (segments.length === 1 && !segments[0].startsWith('@')) ||
    (segments.length === 2 && segments[0].startsWith('@'));
  if (
    !valid ||
    segments.some((segment) => !segment || segment === '.' || segment === '..' || segment.includes('\\'))
  ) {
    throw new Error(`Unsafe package name in the Pi dependency graph: ${name}`);
  }
  return segments;
}

async function copyRuntimeDependencies(stagedPiRoot, publicationRoot, packageManifests, builtPackages) {
  const sourceNodeModules = resolve(stagedPiRoot, 'node_modules');
  const publishedNodeModules = resolve(publicationRoot, 'node_modules');
  const workspacePaths = new Set(packageManifests.map(({ name }) => packageNameSegments(name).join('/')));
  await cp(sourceNodeModules, publishedNodeModules, {
    recursive: true,
    dereference: true,
    filter(source) {
      const path = relative(sourceNodeModules, source).replaceAll('\\', '/');
      if (!path) return true;
      if (path === '.bin' || path.startsWith('.bin/') || path === '.package-lock.json') return false;
      return ![...workspacePaths].some(
        (workspacePath) => path === workspacePath || path.startsWith(`${workspacePath}/`),
      );
    },
  });

  for (const builtPackage of builtPackages) {
    const destination = resolve(publishedNodeModules, ...packageNameSegments(builtPackage.name));
    await mkdir(dirname(destination), { recursive: true });
    await cp(resolve(publicationRoot, builtPackage.relativeDirectory), destination, { recursive: true });
  }
}

const pinnedPiSource = await verifyPiSourceBoundary({ root, quiet: true });
const { fileCount: modelFileCount } = await verifyPiModelDataCache({
  cacheRoot: modelDataCacheRoot,
  officialRoot: resolve(piRoot, 'packages', 'ai', 'src', 'providers', 'data'),
});
const cacheLayout = await resolveSafePiCacheLayout({ repositoryRoot: root });

const temporaryBase = resolve(tmpdir());
const temporaryRoot = await mkdtemp(join(temporaryBase, 'workdude-pi-offline-build-'));
const temporaryRelative = relative(temporaryBase, temporaryRoot);
if (!temporaryRelative || temporaryRelative.startsWith('..') || isAbsolute(temporaryRelative)) {
  throw new Error('The isolated Pi build directory is outside the operating-system temporary directory');
}
const publicationRoot = await mkdtemp(join(cacheLayout.cacheParent, 'pi-build-stage-'));

try {
  const stagedPiRoot = resolve(temporaryRoot, 'pi');
  await cp(piRoot, stagedPiRoot, { recursive: true });
  await verifyIsolatedPiSourceTree(stagedPiRoot, pinnedPiSource);
  const stagedSourceSnapshot = await capturePiSourceSnapshot(stagedPiRoot);
  await installIsolatedDependencies(stagedPiRoot);
  const packageManifests = await discoverPackageManifests(stagedPiRoot);
  await runOfflineBuild(stagedPiRoot);
  await verifyPiSourceSnapshot(stagedPiRoot, stagedSourceSnapshot);

  const builtPackages = await copyBuiltPackages(stagedPiRoot, publicationRoot, packageManifests);
  await pruneRuntimeDependencies(stagedPiRoot);
  await verifyPiSourceSnapshot(stagedPiRoot, stagedSourceSnapshot);
  await copyRuntimeDependencies(stagedPiRoot, publicationRoot, packageManifests, builtPackages);
  const artifacts = await hashPublishedArtifacts(publicationRoot);
  await writeFile(
    resolve(publicationRoot, 'source-lock.json'),
    `${JSON.stringify({ schemaVersion: 1, source: pinnedPiSource, artifacts }, undefined, 2)}\n`,
  );
  await publishPiBuildCacheGeneration(cacheLayout, publicationRoot);
  const gatewayRuntime =
    process.env.WORKDUDE_SKIP_PI_GATEWAY_BUNDLE === '1'
      ? undefined
      : await import('./pi-gateway-runtime.mjs').then(({ buildPiGatewayRuntime }) =>
          buildPiGatewayRuntime({ repositoryRoot: root }),
        );
  console.log(
    `Verified ${modelFileCount} pinned Pi model-data files and published ${Object.keys(artifacts).length} source-locked build artifacts${gatewayRuntime ? ` plus gateway runtime ${gatewayRuntime.generation}` : ''}`,
  );
} finally {
  await removePiBuildCacheScratch(cacheLayout, publicationRoot);
  await rm(temporaryRoot, { recursive: true, force: true });
}
