import { spawnSync } from 'node:child_process';
import { pinPublishedPiBuildCache } from './pi-cache-publication.mjs';
import { buildPiGatewayRuntime, pinPiGatewayRuntime } from './pi-gateway-runtime.mjs';

const repositoryRoot = process.cwd();

async function verifyPiBuildCache() {
  return pinPublishedPiBuildCache({ repositoryRoot });
}

async function verifyGatewayRuntime(expectedBuild) {
  const runtime = await pinPiGatewayRuntime({ repositoryRoot });
  if (
    expectedBuild &&
    (runtime.manifest.source.piGeneration !== expectedBuild.generation ||
      runtime.manifest.source.piManifestSha256 !== expectedBuild.manifestSha256 ||
      runtime.manifest.source.sourceLockSha256 !== expectedBuild.sourceLockSha256 ||
      runtime.manifest.source.piSourceManifestSha256 !== expectedBuild.piSourceManifestSha256)
  ) {
    throw new Error('Pi gateway runtime does not match the currently pinned Pi build generation');
  }
  return runtime;
}

async function verifyCurrentGeneration() {
  const build = await verifyPiBuildCache();
  const runtime = await verifyGatewayRuntime(build);
  return { build: build.generation, runtime: runtime.generation };
}

function runFullPiBuild() {
  const npmCli = process.env.npm_execpath;
  const command = npmCli ? process.execPath : 'npm';
  const arguments_ = npmCli ? [npmCli, 'run', 'build:pi'] : ['run', 'build:pi'];
  const result = spawnSync(command, arguments_, {
    cwd: repositoryRoot,
    env: process.env,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error('Pi build failed with exit code ' + String(result.status ?? 'unknown'));
  }
}

try {
  let build;
  let message;
  try {
    build = await verifyPiBuildCache();
  } catch {
    runFullPiBuild();
    const current = await verifyCurrentGeneration();
    message =
      'Published verified Pi build cache ' + current.build + ' and gateway runtime ' + current.runtime + '\n';
  }

  if (!message) {
    try {
      const runtime = await verifyGatewayRuntime(build);
      message =
        'Reused verified Pi build cache ' +
        build.generation +
        ' and gateway runtime ' +
        runtime.generation +
        '\n';
    } catch {
      // A valid Pi build cache only needs the lightweight gateway bundle repaired;
      // do not rebuild the 18k-file Pi snapshot for a runtime-pointer failure.
      try {
        await buildPiGatewayRuntime({ repositoryRoot });
        const runtime = await verifyGatewayRuntime(build);
        message =
          'Reused verified Pi build cache ' +
          build.generation +
          ' and rebuilt gateway runtime ' +
          runtime.generation +
          '\n';
      } catch {
        // If the gateway repair also proves the Pi generation invalid, perform
        // one and only one complete rebuild, then verify both generations.
        runFullPiBuild();
        const current = await verifyCurrentGeneration();
        message =
          'Published verified Pi build cache ' +
          current.build +
          ' and gateway runtime ' +
          current.runtime +
          '\n';
      }
    }
  }
  process.stdout.write(message);
} catch (error) {
  throw new Error('Verified Pi build cache could not be established', { cause: error });
}
