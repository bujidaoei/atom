import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { basename, resolve, sep } from 'node:path';

import { DESKTOP_RELEASE_LABELS, desktopReleasePackageNames } from './desktop-release-contract.mjs';
import { githubRelease, verifyRemoteReleaseAssetDigests } from './verify-github-release-asset-digests.mjs';

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
const tag = process.env.GITHUB_REF_NAME;
const repository = process.env.GITHUB_REPOSITORY;
const commit = process.env.GITHUB_SHA;
if (!tag || !repository || !commit || !process.env.GH_TOKEN) {
  throw new Error('GITHUB_REF_NAME, GITHUB_REPOSITORY, GITHUB_SHA, and GH_TOKEN are required.');
}

const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
if (tag !== `desktop-v${desktopPackage.version}`) {
  throw new Error(`Desktop release tag ${tag} does not match version ${desktopPackage.version}.`);
}

const makeDirectory = resolve('apps/desktop/out/make');
const releaseDirectory = resolve(makeDirectory, 'release-assets', label);
if (!releaseDirectory.startsWith(`${makeDirectory}${sep}`)) {
  throw new Error('Refusing to publish assets outside the Desktop make directory.');
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

const assets = (await walk(releaseDirectory)).sort((left, right) => left.localeCompare(right));
if (assets.length === 0) throw new Error(`No ${label} GitHub Release assets were found.`);

const names = assets.map((path) => basename(path));
const duplicates = names.filter((name, index) => names.indexOf(name) !== index);
if (duplicates.length > 0) throw new Error(`Duplicate release asset names: ${duplicates.join(', ')}`);

const requiredMetadata = [
  `SHA256SUMS-${label}.txt`,
  `SBOM-${label}.cyclonedx.json`,
  `PROVENANCE-${label}.json`,
];
for (const required of requiredMetadata) {
  if (!names.includes(required)) throw new Error(`Required release asset is missing: ${required}`);
}
const packagePrefix = `QoderWake-${desktopPackage.version}-${label}`;
const allowedPackageNames = desktopReleasePackageNames(desktopPackage.version, label);
const packageNames = names.filter((name) => allowedPackageNames.includes(name));
if (packageNames.length === 0) throw new Error(`No ${label} package asset is ready to publish.`);
const unexpected = names.filter((name) => !requiredMetadata.includes(name) && !packageNames.includes(name));
if (unexpected.length > 0) throw new Error(`Unexpected release assets: ${unexpected.join(', ')}`);

const sameNames = (left, right) => {
  if (!Array.isArray(left) || left.length !== right.length) return false;
  const sortedLeft = [...left].sort();
  const sortedRight = [...right].sort();
  return sortedLeft.every((name, index) => name === sortedRight[index]);
};
const validWindowsBuildIdentity = (identity) => {
  const sha256 = /^[a-f0-9]{64}$/u;
  const critical = ['executable', 'appAsar', 'nativeHost', 'uninstallHelper'];
  if (!identity || typeof identity !== 'object') return false;
  if (!identity.unpacked || !identity.zip || !identity.nupkg) return false;
  if (
    !critical.every(
      (name) =>
        sha256.test(identity.unpacked[name]) &&
        identity.unpacked[name] === identity.zip[name] &&
        identity.unpacked[name] === identity.nupkg[name],
    )
  ) {
    return false;
  }
  return (
    sha256.test(identity.setupSha256) &&
    sha256.test(identity.zipSha256) &&
    sha256.test(identity.nupkgSha256) &&
    identity.nupkgSha256 === identity.setupEmbeddedNupkgSha256
  );
};
const assetByName = new Map(assets.map((path) => [basename(path), path]));
const checksumName = `SHA256SUMS-${label}.txt`;
const checksumLines = (await readFile(assetByName.get(checksumName), 'ascii'))
  .trim()
  .split('\n')
  .map((line) => line.replace(/\r$/, ''));
const checksums = new Map();
for (const line of checksumLines) {
  const match = /^([a-f0-9]{64})[ ]{2}([^/\\]+)$/.exec(line);
  if (!match || checksums.has(match[2])) {
    throw new Error(`Invalid checksum manifest entry: ${line}`);
  }
  checksums.set(match[2], match[1]);
}
if (!sameNames([...checksums.keys()], packageNames)) {
  throw new Error('Checksum manifest does not match the release package set.');
}
for (const name of packageNames) {
  const actual = createHash('sha256')
    .update(await readFile(assetByName.get(name)))
    .digest('hex');
  if (checksums.get(name) !== actual) {
    throw new Error(`Checksum mismatch for release asset: ${name}`);
  }
}

const sbomName = `SBOM-${label}.cyclonedx.json`;
let sbomDocument;
try {
  sbomDocument = JSON.parse(await readFile(assetByName.get(sbomName), 'utf8'));
} catch {
  throw new Error('Invalid CycloneDX SBOM release asset.');
}
if (
  sbomDocument.bomFormat !== 'CycloneDX' ||
  typeof sbomDocument.specVersion !== 'string' ||
  !Number.isInteger(sbomDocument.version) ||
  typeof sbomDocument.metadata !== 'object' ||
  !Array.isArray(sbomDocument.components)
) {
  throw new Error('Invalid CycloneDX SBOM release asset.');
}

const provenanceName = `PROVENANCE-${label}.json`;
let provenanceDocument;
try {
  provenanceDocument = JSON.parse(await readFile(assetByName.get(provenanceName), 'utf8'));
} catch {
  throw new Error('Invalid release provenance asset.');
}
if (
  provenanceDocument.schema !== 'https://workdude.local/schemas/release-provenance/v1' ||
  provenanceDocument.repository !== repository ||
  provenanceDocument.commit !== commit ||
  provenanceDocument.tag !== tag ||
  provenanceDocument.version !== desktopPackage.version ||
  provenanceDocument.label !== label ||
  provenanceDocument.checksumManifest !== checksumName ||
  provenanceDocument.sbom !== sbomName ||
  !sameNames(provenanceDocument.packages, packageNames) ||
  (label === 'Windows-x64' &&
    (!validWindowsBuildIdentity(provenanceDocument.buildIdentity) ||
      provenanceDocument.buildIdentity.setupSha256 !== checksums.get(`${packagePrefix}-Setup.exe`) ||
      provenanceDocument.buildIdentity.nupkgSha256 !== checksums.get(`${packagePrefix}-full.nupkg`) ||
      provenanceDocument.buildIdentity.zipSha256 !== checksums.get(`${packagePrefix}.zip`)))
) {
  throw new Error('Release provenance does not match the current release context.');
}

const release = githubRelease(tag, repository);
if (release.draft !== true || release.tag_name !== tag) {
  throw new Error('Refusing to upload assets to a non-draft GitHub Release.');
}

execFileSync('gh', ['release', 'upload', tag, '--repo', repository, '--clobber', ...assets], {
  stdio: 'inherit',
});
await verifyRemoteReleaseAssetDigests({ tag, repository, assets });
