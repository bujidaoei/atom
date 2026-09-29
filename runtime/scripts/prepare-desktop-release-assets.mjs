import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createReadStream } from 'node:fs';
import { copyFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { basename, extname, resolve, sep } from 'node:path';

import { inspectWindowsReleaseBuildIdentity } from './windows-release-build-identity.mjs';
import {
  DESKTOP_RELEASE_LABELS,
  hasExactDesktopReleaseVersion,
  isDesktopReleaseCandidateForLabel,
} from './desktop-release-contract.mjs';

const argument = (name) => {
  const prefix = `--${name}=`;
  const value = process.argv.find((item) => item.startsWith(prefix))?.slice(prefix.length);
  if (!value) throw new Error(`Missing ${prefix}<value>`);
  return value;
};

const label = argument('label');
if (!DESKTOP_RELEASE_LABELS.includes(label)) {
  throw new Error(`Unsupported desktop release label: ${label}`);
}
const extensions = new Set(
  argument('extensions')
    .split(',')
    .map((value) => value.trim()),
);
const makeDirectory = resolve('apps/desktop/out/make');
const releaseDirectory = resolve(makeDirectory, 'release-assets', label);
if (!releaseDirectory.startsWith(`${makeDirectory}${sep}`)) {
  throw new Error('Refusing to prepare assets outside the Desktop make directory.');
}

const walk = async (directory) => {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = resolve(directory, entry.name);
      return entry.isDirectory() ? walk(path) : [path];
    }),
  );
  return nested.flat();
};

const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const candidates = (await walk(makeDirectory))
  .filter(
    (path) =>
      !path.startsWith(`${resolve(makeDirectory, 'release-assets')}${sep}`) &&
      extensions.has(extname(path).toLowerCase()) &&
      isDesktopReleaseCandidateForLabel(path, makeDirectory, label),
  )
  .sort((left, right) => left.localeCompare(right));
const versionedCandidates = candidates.filter((path) =>
  hasExactDesktopReleaseVersion(basename(path), desktopPackage.version),
);
const packages = versionedCandidates;
if (packages.length === 0) {
  throw new Error(`No current-version ${label} desktop package was produced.`);
}
const extensionCounts = new Map();
for (const path of packages) {
  const extension = extname(path).toLowerCase();
  extensionCounts.set(extension, (extensionCounts.get(extension) ?? 0) + 1);
}
const duplicateExtension = [...extensionCounts].find(([, count]) => count > 1)?.[0];
if (duplicateExtension) {
  throw new Error(`Multiple ${label} ${duplicateExtension} packages were produced.`);
}

let buildIdentity;
if (label === 'Windows-x64') {
  const packageByExtension = new Map(packages.map((path) => [extname(path).toLowerCase(), path]));
  for (const extension of ['.zip', '.exe', '.nupkg']) {
    if (!packageByExtension.has(extension)) {
      throw new Error(`Windows-x64 release staging requires one current ${extension} package.`);
    }
  }
  buildIdentity = await inspectWindowsReleaseBuildIdentity({
    sevenZipPath: 'node_modules/electron-winstaller/vendor/7z.exe',
    packageRoot: 'apps/desktop/out/QoderWake-win32-x64',
    zipPath: packageByExtension.get('.zip'),
    setupPath: packageByExtension.get('.exe'),
    nupkgPath: packageByExtension.get('.nupkg'),
  });
}

await rm(releaseDirectory, { recursive: true, force: true });
await mkdir(releaseDirectory, { recursive: true });
const releasedPackages = [];
for (const path of packages) {
  const extension = extname(path).toLowerCase();
  const suffix = extension === '.exe' ? '-Setup' : extension === '.nupkg' ? '-full' : '';
  const destination = resolve(
    releaseDirectory,
    `QoderWake-${desktopPackage.version}-${label}${suffix}${extension}`,
  );
  await copyFile(path, destination);
  releasedPackages.push(destination);
}

const checksum = resolve(releaseDirectory, `SHA256SUMS-${label}.txt`);
const checksumLines = [];
for (const path of releasedPackages) {
  const hash = await new Promise((resolveHash, reject) => {
    const digest = createHash('sha256');
    const stream = createReadStream(path);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.once('error', reject);
    stream.once('end', () => resolveHash(digest.digest('hex')));
  });
  checksumLines.push(`${hash}  ${basename(path)}`);
}
await writeFile(checksum, `${checksumLines.join('\n')}\n`, 'ascii');

const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error('npm_execpath is required to generate the release SBOM.');
const sbomContent = execFileSync(process.execPath, [npmCli, 'sbom', '--sbom-format=cyclonedx'], {
  encoding: 'utf8',
  maxBuffer: 32 * 1024 * 1024,
});
const sbom = resolve(releaseDirectory, `SBOM-${label}.cyclonedx.json`);
await writeFile(sbom, sbomContent, 'utf8');

const provenance = resolve(releaseDirectory, `PROVENANCE-${label}.json`);
await writeFile(
  provenance,
  `${JSON.stringify(
    {
      schema: 'https://workdude.local/schemas/release-provenance/v1',
      repository: process.env.GITHUB_REPOSITORY ?? 'local/workdude',
      commit: process.env.GITHUB_SHA ?? 'local',
      tag: process.env.GITHUB_REF_NAME ?? 'local',
      version: desktopPackage.version,
      label,
      workflowRunId: process.env.GITHUB_RUN_ID ?? 'local',
      workflowRunAttempt: process.env.GITHUB_RUN_ATTEMPT ?? 'local',
      runner: {
        name: process.env.RUNNER_NAME ?? 'local',
        environment: process.env.RUNNER_ENVIRONMENT ?? 'local',
        os: process.env.RUNNER_OS ?? process.platform,
        arch: process.env.RUNNER_ARCH ?? process.arch,
      },
      generatedAtUtc: new Date().toISOString(),
      checksumManifest: basename(checksum),
      sbom: basename(sbom),
      packages: releasedPackages.map((path) => basename(path)),
      ...(buildIdentity ? { buildIdentity } : {}),
    },
    null,
    2,
  )}\n`,
  'utf8',
);

process.stdout.write(
  `${JSON.stringify({ label, packages: releasedPackages.map((path) => basename(path)), checksum, sbom, provenance })}\n`,
);
