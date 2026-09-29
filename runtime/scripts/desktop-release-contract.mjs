import { pathToFileURL } from 'node:url';

export const DESKTOP_RELEASE_LABELS = Object.freeze(['Windows-x64', 'Linux-x64', 'macOS-x64', 'macOS-arm64']);

const packageSuffixesByLabel = Object.freeze({
  'Windows-x64': Object.freeze(['-Setup.exe', '-full.nupkg', '.zip']),
  'Linux-x64': Object.freeze(['.deb', '.zip']),
  'macOS-x64': Object.freeze(['.dmg', '.zip']),
  'macOS-arm64': Object.freeze(['.dmg', '.zip']),
});

function assertVersion(version) {
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$/u.test(version)) {
    throw new Error(`Invalid Desktop release version: ${version}`);
  }
}

function assertLabel(label) {
  if (!DESKTOP_RELEASE_LABELS.includes(label)) {
    throw new Error(`Unsupported Desktop release label: ${label}`);
  }
}

function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
}

export function hasExactDesktopReleaseVersion(name, version) {
  assertVersion(version);
  if (typeof name !== 'string' || !name.toLocaleLowerCase('en-US').startsWith('qoderwake')) {
    return false;
  }
  const tokens = [version, version.replace('-beta.', '-beta'), version.replace('-', '~')];
  if (name.endsWith('.deb')) tokens.push(version.replace('-', '.'));
  return tokens.some((token) =>
    new RegExp(`${escapeRegularExpression(token)}(?![0-9A-Za-z])`, 'u').test(name),
  );
}

export function isDesktopReleaseCandidateForLabel(path, makeDirectory, label) {
  assertLabel(label);
  if (typeof path !== 'string' || typeof makeDirectory !== 'string') return false;
  const normalizedPath = path.replaceAll('\\', '/');
  const normalizedRoot = makeDirectory.replaceAll('\\', '/').replace(/\/+$/u, '');
  if (
    !normalizedPath.startsWith(`${normalizedRoot}/`) ||
    normalizedPath.includes(`${normalizedRoot}/release-assets/`)
  ) {
    return false;
  }
  const relative = normalizedPath.slice(normalizedRoot.length + 1);
  const expectedPath = {
    'Windows-x64': /^(?:squirrel\.windows|zip\/win32)\/x64\//u,
    'Linux-x64': /^(?:zip\/linux\/x64\/|deb\/x64\/[^/]+\.deb$)/u,
    'macOS-x64': /^(?:zip\/darwin\/x64\/|QoderWake-[^/]+-x64\.dmg$)/u,
    'macOS-arm64': /^(?:zip\/darwin\/arm64\/|QoderWake-[^/]+-arm64\.dmg$)/u,
  }[label];
  return expectedPath.test(relative);
}
export function desktopReleasePackageNames(version, label) {
  assertVersion(version);
  assertLabel(label);
  const prefix = `QoderWake-${version}-${label}`;
  return packageSuffixesByLabel[label].map((suffix) => `${prefix}${suffix}`);
}

export function assertDebianPackageIdentity(identity, expectedVersion) {
  if (
    identity.package !== 'qoderwake' ||
    identity.version !== expectedVersion ||
    identity.architecture !== 'amd64'
  )
    throw new Error('Debian package identity does not match qoderwake/current version/amd64');
}

export function selectNativeDesktopInstaller(files, makeDirectory, label, version) {
  assertLabel(label);
  assertVersion(version);
  if (label === 'Windows-x64') throw new Error('Windows uses its dedicated installed lifecycle');
  const extension = label === 'Linux-x64' ? '.deb' : '.dmg';
  const candidates = files.filter((path) => {
    const name = path.replaceAll('\\', '/').split('/').at(-1);
    return (
      path.endsWith(extension) &&
      isDesktopReleaseCandidateForLabel(path, makeDirectory, label) &&
      hasExactDesktopReleaseVersion(name, version)
    );
  });
  if (candidates.length !== 1)
    throw new Error(
      `Native verification requires exactly one current ${label} installer; found ${candidates.length}`,
    );
  return candidates[0];
}

export function desktopReleaseAssetNames(version) {
  assertVersion(version);
  const names = ['RELEASE-NOTES.md'];
  for (const label of DESKTOP_RELEASE_LABELS) {
    names.push(
      ...desktopReleasePackageNames(version, label),
      `SHA256SUMS-${label}.txt`,
      `SBOM-${label}.cyclonedx.json`,
      `PROVENANCE-${label}.json`,
    );
  }
  return names;
}

export function assertRemoteAssetDigests(remoteAssets, expectedAssets) {
  if (!Array.isArray(remoteAssets) || !Array.isArray(expectedAssets)) {
    throw new Error('Remote and expected release assets must be arrays.');
  }
  const expectedNames = new Set();
  for (const expected of expectedAssets) {
    if (
      !expected ||
      typeof expected.name !== 'string' ||
      !Number.isSafeInteger(expected.sizeBytes) ||
      expected.sizeBytes <= 0 ||
      !/^[a-f0-9]{64}$/u.test(expected.sha256) ||
      expectedNames.has(expected.name)
    ) {
      throw new Error('Expected release asset identity is invalid or duplicated.');
    }
    expectedNames.add(expected.name);
    const matches = remoteAssets.filter((asset) => asset?.name === expected.name);
    if (matches.length !== 1) {
      throw new Error(`Remote release asset must exist exactly once: ${expected.name}`);
    }
    const [remote] = matches;
    if (remote.state !== 'uploaded') {
      throw new Error(`Remote release asset is not uploaded: ${expected.name}`);
    }
    if (remote.size !== expected.sizeBytes) {
      throw new Error(`Remote release asset size does not match local bytes: ${expected.name}`);
    }
    if (remote.digest !== `sha256:${expected.sha256}`) {
      throw new Error(`Remote release asset digest does not match local bytes: ${expected.name}`);
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argument = process.argv.find((value) => value.startsWith('--version='));
  if (process.argv.length !== 3 || !argument) {
    throw new Error('Usage: node scripts/desktop-release-contract.mjs --version=<version>');
  }
  const version = argument.slice('--version='.length);
  process.stdout.write(
    `${JSON.stringify({
      version,
      assets: desktopReleaseAssetNames(version),
      packages: Object.fromEntries(
        DESKTOP_RELEASE_LABELS.map((label) => [label, desktopReleasePackageNames(version, label)]),
      ),
    })}\n`,
  );
}
