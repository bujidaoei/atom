import { createHash } from 'node:crypto';
import { lstat, open, readdir, realpath } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';

const trustedPiSourceLocks = new WeakSet();

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isMissing(error) {
  return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

export function normalizePiSourceLock(value) {
  const stringFields = ['version', 'releaseTag', 'upstreamRepository', 'upstreamCommit', 'sourceArchive'];
  const hashFields = ['sourceArchiveSha256', 'manifestSha256'];
  if (
    !isRecord(value) ||
    stringFields.some((field) => typeof value[field] !== 'string' || value[field].length === 0) ||
    hashFields.some((field) => !/^[a-f0-9]{64}$/u.test(String(value[field]))) ||
    !Number.isSafeInteger(value.fileCount) ||
    value.fileCount <= 0
  ) {
    throw new Error('The pinned Pi source lock is invalid');
  }
  return Object.fromEntries(
    [...stringFields, ...hashFields, 'fileCount'].map((field) => [field, value[field]]),
  );
}

function manifestPiDependencies(manifest) {
  const sections = [
    manifest.dependencies,
    manifest.devDependencies,
    manifest.optionalDependencies,
    manifest.peerDependencies,
  ].filter(isRecord);
  const bundledDependencies = [
    ...(Array.isArray(manifest.bundledDependencies) ? manifest.bundledDependencies : []),
    ...(Array.isArray(manifest.bundleDependencies) ? manifest.bundleDependencies : []),
  ];
  return [
    ...sections.flatMap((section) =>
      Object.keys(section).filter((name) => name.startsWith('@earendil-works/pi-')),
    ),
    ...bundledDependencies.map(String).filter((name) => name.startsWith('@earendil-works/pi-')),
  ];
}

function assertRepositoryPath(repositoryRoot, path, label) {
  const name = relative(repositoryRoot, path);
  if (isAbsolute(name) || name.startsWith('..') || name === '') {
    throw new Error(`${label} is outside the repository`);
  }
}

function assertContainedPath(root, path, label, allowRoot = false) {
  const name = relative(root, path);
  if (isAbsolute(name) || name.startsWith('..') || (!allowRoot && name === '')) {
    throw new Error(`${label} is outside its trusted root`);
  }
}

function assertPlainFile(entry, label) {
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`${label} must be a plain file`);
  }
  if (entry.nlink !== 1n) throw new Error(`${label} must not be a hard link`);
}

function sameStableFile(left, right) {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.nlink === right.nlink &&
    left.size === right.size &&
    left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs
  );
}

export async function readStablePlainFile(path, { repositoryRoot, trustedRoot = repositoryRoot, label }) {
  const resolvedPath = resolve(path);
  assertRepositoryPath(repositoryRoot, resolvedPath, label);
  assertContainedPath(trustedRoot, resolvedPath, label);
  const pathBefore = await lstat(resolvedPath, { bigint: true });
  assertPlainFile(pathBefore, label);
  const realPathBefore = await realpath(resolvedPath);
  assertRepositoryPath(repositoryRoot, realPathBefore, label);
  assertContainedPath(trustedRoot, realPathBefore, label);

  const handle = await open(resolvedPath, 'r');
  try {
    const handleBefore = await handle.stat({ bigint: true });
    assertPlainFile(handleBefore, label);
    if (!sameStableFile(pathBefore, handleBefore)) {
      throw new Error(`${label} identity changed before it could be read`);
    }
    const content = await handle.readFile();
    const handleAfter = await handle.stat({ bigint: true });
    assertPlainFile(handleAfter, label);
    const pathAfter = await lstat(resolvedPath, { bigint: true });
    assertPlainFile(pathAfter, label);
    const realPathAfter = await realpath(resolvedPath);
    assertRepositoryPath(repositoryRoot, realPathAfter, label);
    assertContainedPath(trustedRoot, realPathAfter, label);
    if (
      realPathAfter !== realPathBefore ||
      !sameStableFile(handleBefore, handleAfter) ||
      !sameStableFile(handleAfter, pathAfter)
    ) {
      throw new Error(`${label} identity or content metadata changed while it was read`);
    }
    return content;
  } finally {
    await handle.close();
  }
}

async function resolvePlainDirectory(path, { repositoryRoot, trustedRoot = repositoryRoot, label }) {
  const resolvedPath = resolve(path);
  if (resolvedPath !== repositoryRoot) assertRepositoryPath(repositoryRoot, resolvedPath, label);
  assertContainedPath(trustedRoot, resolvedPath, label, resolvedPath === trustedRoot);
  const entry = await lstat(resolvedPath);
  if (entry.isSymbolicLink() || !entry.isDirectory()) {
    throw new Error(`${label} must be a plain directory, not a symbolic link`);
  }
  const realPath = await realpath(resolvedPath);
  if (realPath !== repositoryRoot) assertRepositoryPath(repositoryRoot, realPath, label);
  assertContainedPath(trustedRoot, realPath, label, realPath === trustedRoot);
  return realPath;
}

async function resolveRootDirectory(path, label) {
  const resolvedPath = resolve(path);
  const entry = await lstat(resolvedPath);
  if (entry.isSymbolicLink() || !entry.isDirectory()) {
    throw new Error(`${label} must be a plain directory, not a symbolic link`);
  }
  return realpath(resolvedPath);
}

async function productPackageManifests(repositoryRoot, rootManifest, piRoot) {
  const manifests = [{ path: 'package.json', manifest: rootManifest }];
  const workspaces = Array.isArray(rootManifest.workspaces)
    ? rootManifest.workspaces
    : isRecord(rootManifest.workspaces) && Array.isArray(rootManifest.workspaces.packages)
      ? rootManifest.workspaces.packages
      : [];

  async function addManifest(packageRoot) {
    assertRepositoryPath(repositoryRoot, packageRoot, 'Product workspace');
    let realPackageRoot;
    try {
      realPackageRoot = await resolvePlainDirectory(packageRoot, {
        repositoryRoot,
        label: 'Product workspace',
      });
    } catch (error) {
      if (isMissing(error)) return;
      throw error;
    }
    const relativeToPi = relative(piRoot, realPackageRoot);
    if (!isAbsolute(relativeToPi) && !relativeToPi.startsWith('..')) {
      throw new Error('Vendored Pi packages must not be registered as product workspaces');
    }
    const manifestPath = resolve(realPackageRoot, 'package.json');
    let content;
    try {
      content = await readStablePlainFile(manifestPath, {
        repositoryRoot,
        label: `Product workspace manifest ${relative(repositoryRoot, manifestPath)}`,
      });
    } catch (error) {
      if (isMissing(error)) return;
      throw error;
    }
    manifests.push({
      path: relative(repositoryRoot, manifestPath).replaceAll('\\', '/'),
      manifest: JSON.parse(content.toString('utf8')),
    });
  }

  for (const rawPattern of workspaces) {
    if (typeof rawPattern !== 'string' || !rawPattern || rawPattern.includes('\\')) {
      throw new Error('Product workspace pattern is invalid');
    }
    if (!rawPattern.includes('*')) {
      await addManifest(resolve(repositoryRoot, rawPattern));
      continue;
    }
    if (!rawPattern.endsWith('/*') || rawPattern.slice(0, -2).includes('*')) {
      throw new Error(`Unsupported product workspace pattern: ${rawPattern}`);
    }
    const workspaceParent = resolve(repositoryRoot, rawPattern.slice(0, -2));
    assertRepositoryPath(repositoryRoot, workspaceParent, 'Product workspace parent');
    const realWorkspaceParent = await resolvePlainDirectory(workspaceParent, {
      repositoryRoot,
      label: `Product workspace parent ${rawPattern}`,
    }).catch((error) => {
      if (isMissing(error)) return undefined;
      throw error;
    });
    if (!realWorkspaceParent) continue;
    for (const entry of await readdir(realWorkspaceParent, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) {
        throw new Error(`Product workspace must not be a symbolic link: ${rawPattern}`);
      }
      if (entry.isDirectory()) await addManifest(resolve(realWorkspaceParent, entry.name));
    }
  }
  return manifests;
}

async function filesystemPiEntries(repositoryRoot, piRoot) {
  const entries = [];
  async function visit(directory) {
    const realDirectory = await resolvePlainDirectory(directory, {
      repositoryRoot,
      trustedRoot: piRoot,
      label: 'Vendored Pi source directory',
    });
    for (const entry of await readdir(realDirectory, { withFileTypes: true })) {
      const path = resolve(realDirectory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        const name = relative(piRoot, path).replaceAll('\\', '/');
        const content = await readStablePlainFile(path, {
          repositoryRoot,
          trustedRoot: piRoot,
          label: `Vendored Pi source file ${name}`,
        });
        const object = createHash('sha1')
          .update(`blob ${content.byteLength}\0`)
          .update(content)
          .digest('hex');
        entries.push({
          object,
          path: `pi/${name}`,
        });
      } else {
        throw new Error(`Unsupported entry in the vendored Pi source archive: ${path}`);
      }
    }
  }
  await visit(piRoot);
  return entries;
}

function assertPiEntriesMatchLock(entries, lock, label) {
  if (entries.length !== lock.fileCount) {
    throw new Error(`${label} file count ${entries.length} differs from locked ${lock.fileCount}`);
  }

  const manifest = entries
    .map(({ object, path }) => `${path.replace(/^pi\//u, '')}\0${object}\n`)
    .sort()
    .join('');
  const digest = createHash('sha256').update(manifest).digest('hex');
  if (digest !== lock.manifestSha256) {
    throw new Error(`${label} manifest ${digest} differs from locked ${lock.manifestSha256}`);
  }
}

export async function verifyIsolatedPiSourceTree(piRoot, lock) {
  if (!isRecord(lock) || !trustedPiSourceLocks.has(lock)) {
    throw new Error('A trusted verified Pi source lock is required');
  }
  const root = await resolveRootDirectory(piRoot, 'Isolated Pi source root');
  assertPiEntriesMatchLock(await filesystemPiEntries(root, root), lock, 'Isolated Pi source');
}

export async function capturePiSourceSnapshot(piRoot) {
  const root = await resolveRootDirectory(piRoot, 'Locked Pi source root');
  const snapshot = new Map();
  async function visit(directory) {
    const realDirectory = await resolvePlainDirectory(directory, {
      repositoryRoot: root,
      trustedRoot: root,
      label: 'Locked Pi source directory',
    });
    for (const entry of await readdir(realDirectory, { withFileTypes: true })) {
      const path = resolve(realDirectory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        const name = relative(root, path).replaceAll('\\', '/');
        const content = await readStablePlainFile(path, {
          repositoryRoot: root,
          trustedRoot: root,
          label: `Locked Pi source file ${name}`,
        });
        snapshot.set(name, createHash('sha256').update(content).digest('hex'));
      } else {
        throw new Error(`Unsupported entry in the locked Pi source snapshot: ${path}`);
      }
    }
  }
  await visit(root);
  return snapshot;
}

export async function verifyPiSourceSnapshot(piRoot, snapshot) {
  const root = await resolveRootDirectory(piRoot, 'Generated Pi build root');
  function generatedNodeModulesRoot(name) {
    if (name === 'node_modules' || name.startsWith('node_modules/')) return 'node_modules';
    return /^(packages\/(?:[^/]+|session-backends\/[^/]+)\/node_modules)(?:\/|$)/u.exec(name)?.[1];
  }
  for (const [name, expectedHash] of snapshot) {
    const path = resolve(root, name);
    let content;
    try {
      content = await readStablePlainFile(path, {
        repositoryRoot: root,
        trustedRoot: root,
        label: `Locked Pi source file ${name}`,
      });
    } catch (error) {
      if (isMissing(error)) throw new Error(`Locked Pi source file is missing: ${name}`, { cause: error });
      throw error;
    }
    const actualHash = createHash('sha256').update(content).digest('hex');
    if (actualHash !== expectedHash) throw new Error(`Locked Pi source file changed: ${name}`);
  }
  async function verifyWorkspaceBinaryLink(target, targetName, name) {
    const match = /^(packages\/(?:[^/]+|session-backends\/[^/]+))\/(.+)$/u.exec(targetName);
    if (!match || !snapshot.has(`${match[1]}/package.json`)) {
      throw new Error(`Generated Pi binary link resolves outside staged node_modules: ${name}`);
    }
    const packageJson = JSON.parse(
      (
        await readStablePlainFile(resolve(root, match[1], 'package.json'), {
          repositoryRoot: root,
          trustedRoot: root,
          label: `Generated Pi binary workspace manifest ${name}`,
        })
      ).toString('utf8'),
    );
    const linkName = name.slice(name.lastIndexOf('/') + 1);
    const declaredBin =
      typeof packageJson.bin === 'string'
        ? linkName ===
          String(packageJson.name ?? '')
            .split('/')
            .at(-1)
          ? packageJson.bin
          : undefined
        : isRecord(packageJson.bin) && typeof packageJson.bin[linkName] === 'string'
          ? packageJson.bin[linkName]
          : undefined;
    if (!declaredBin) {
      throw new Error(`Generated Pi binary link is undeclared by the locked package bin map: ${name}`);
    }
    const declaredTarget = declaredBin.replaceAll('\\', '/').replace(/^\.\//u, '');
    if (
      declaredTarget.startsWith('/') ||
      declaredTarget.startsWith('../') ||
      declaredTarget.includes('/../') ||
      targetName !== `${match[1]}/${declaredTarget}`
    ) {
      throw new Error(`Generated Pi binary link does not match the locked package bin target: ${name}`);
    }
    await readStablePlainFile(target, {
      repositoryRoot: root,
      trustedRoot: root,
      label: `Generated Pi binary link target ${name}`,
    });
  }
  async function verifyWorkspaceLink(path, name) {
    const segments = name.split('/');
    const binIndex = segments.lastIndexOf('.bin');
    if (
      generatedNodeModulesRoot(name) &&
      binIndex > 0 &&
      binIndex === segments.length - 2 &&
      segments[binIndex - 1] === 'node_modules'
    ) {
      const target = await realpath(path);
      const targetName = relative(root, target).replaceAll('\\', '/');
      const stagedNodeModules = segments.slice(0, binIndex).join('/');
      if (isAbsolute(targetName) || targetName.startsWith('../')) {
        throw new Error(`Generated Pi binary link resolves outside staged node_modules: ${name}`);
      }
      if (!targetName.startsWith(`${stagedNodeModules}/`)) {
        if (stagedNodeModules === 'node_modules') {
          await verifyWorkspaceBinaryLink(target, targetName, name);
          return;
        }
        throw new Error(`Generated Pi binary link resolves outside staged node_modules: ${name}`);
      }
      await readStablePlainFile(target, {
        repositoryRoot: root,
        trustedRoot: root,
        label: `Generated Pi binary link target ${name}`,
      });
      return;
    }
    if (!/^node_modules\/(?:@[^/]+\/)?[^/]+$/u.test(name)) {
      throw new Error(`Generated Pi build output contains an unsupported link: ${name}`);
    }
    const target = await realpath(path);
    const targetName = relative(root, target).replaceAll('\\', '/');
    if (isAbsolute(targetName) || targetName.startsWith('../') || !targetName.startsWith('packages/')) {
      throw new Error(`Generated Pi workspace link resolves outside the locked workspace: ${name}`);
    }
    if (!snapshot.has(`${targetName}/package.json`)) {
      throw new Error(`Generated Pi workspace link target is not part of the locked source: ${name}`);
    }
    await resolvePlainDirectory(target, {
      repositoryRoot: root,
      trustedRoot: root,
      label: `Generated Pi workspace link target ${name}`,
    });
    const packageJson = JSON.parse(
      (
        await readStablePlainFile(resolve(target, 'package.json'), {
          repositoryRoot: root,
          trustedRoot: root,
          label: `Generated Pi workspace manifest ${name}`,
        })
      ).toString('utf8'),
    );
    const expectedPackageName = name.slice('node_modules/'.length);
    if (packageJson.name !== expectedPackageName) {
      throw new Error(`Generated Pi workspace link package name does not match its target: ${name}`);
    }
  }
  async function visit(directory) {
    const realDirectory = await resolvePlainDirectory(directory, {
      repositoryRoot: root,
      trustedRoot: root,
      label: 'Generated Pi build directory',
    });
    for (const entry of await readdir(realDirectory, { withFileTypes: true })) {
      const path = resolve(realDirectory, entry.name);
      const name = relative(root, path).replaceAll('\\', '/');
      if (entry.isSymbolicLink()) {
        await verifyWorkspaceLink(path, name);
        continue;
      }
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        const fileEntry = await lstat(path, { bigint: true });
        assertPlainFile(fileEntry, `Generated Pi build output file ${name}`);
        if (
          !snapshot.has(name) &&
          !generatedNodeModulesRoot(name) &&
          !/^packages\/(?:[^/]+|session-backends\/[^/]+)\/dist\//u.test(name)
        ) {
          throw new Error(`Generated Pi build output used an unexpected generated path: ${name}`);
        }
      } else {
        throw new Error(`Generated Pi build output contains an unsupported entry: ${name}`);
      }
    }
  }
  await visit(root);
}

export async function verifyPiSourceBoundary({
  root = process.cwd(),
  lockPath = resolve(root, 'pi-source.lock.json'),
  piRoot = resolve(root, 'pi'),
  quiet = false,
} = {}) {
  const repositoryRoot = await resolveRootDirectory(root, 'Repository root');
  const verifiedPiRoot = await resolvePlainDirectory(piRoot, {
    repositoryRoot,
    label: 'Vendored Pi root',
  });
  await readStablePlainFile(resolve(verifiedPiRoot, 'packages', 'coding-agent', 'src', 'index.ts'), {
    repositoryRoot,
    trustedRoot: verifiedPiRoot,
    label: 'Vendored Pi coding-agent entrypoint',
  });
  await readStablePlainFile(resolve(verifiedPiRoot, 'AGENTS.md'), {
    repositoryRoot,
    trustedRoot: verifiedPiRoot,
    label: 'Vendored Pi AGENTS.md',
  });
  const lock = Object.freeze(
    normalizePiSourceLock(
      JSON.parse(
        (
          await readStablePlainFile(lockPath, {
            repositoryRoot,
            label: 'Pinned Pi source lock manifest',
          })
        ).toString('utf8'),
      ),
    ),
  );
  const codingAgentPackage = JSON.parse(
    (
      await readStablePlainFile(resolve(verifiedPiRoot, 'packages', 'coding-agent', 'package.json'), {
        repositoryRoot,
        trustedRoot: verifiedPiRoot,
        label: 'Vendored Pi coding-agent manifest',
      })
    ).toString('utf8'),
  );
  if (codingAgentPackage.version !== lock.version) {
    throw new Error(
      `Vendored Pi package version ${codingAgentPackage.version} differs from locked ${lock.version}`,
    );
  }

  try {
    await lstat(resolve(repositoryRoot, '.gitmodules'));
    throw new Error('Vendored Pi must not use a root .gitmodules file');
  } catch (error) {
    if (!isMissing(error)) throw error;
  }

  try {
    await lstat(resolve(verifiedPiRoot, '.git'));
    throw new Error('Vendored Pi must not contain nested Git metadata');
  } catch (error) {
    if (!isMissing(error)) throw error;
  }

  const packageJson = JSON.parse(
    (
      await readStablePlainFile(resolve(repositoryRoot, 'package.json'), {
        repositoryRoot,
        label: 'Product root manifest package.json',
      })
    ).toString('utf8'),
  );
  for (const productManifest of await productPackageManifests(repositoryRoot, packageJson, verifiedPiRoot)) {
    const externalPi = manifestPiDependencies(productManifest.manifest);
    if (externalPi.length > 0) {
      throw new Error(
        `External Pi packages are forbidden in ${productManifest.path}: ${externalPi.join(', ')}`,
      );
    }
  }

  const entries = await filesystemPiEntries(repositoryRoot, verifiedPiRoot);
  assertPiEntriesMatchLock(entries, lock, 'Vendored Pi');

  trustedPiSourceLocks.add(lock);
  if (!quiet) {
    console.log(
      `Vendored Pi source boundary verified at upstream ${lock.upstreamCommit} (${entries.length} files)`,
    );
  }
  return lock;
}
