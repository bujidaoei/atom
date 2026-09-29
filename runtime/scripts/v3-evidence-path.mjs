import { isAbsolute, relative, resolve } from 'node:path';

function isInside(parent, candidate) {
  const pathFromParent = relative(parent, candidate);
  return pathFromParent === '' || (!pathFromParent.startsWith('..') && !isAbsolute(pathFromParent));
}

export function resolveStableV3EvidenceDirectory(repositoryRoot, configuredPath) {
  const root = resolve(repositoryRoot);
  const output = resolve(root, configuredPath);
  const playwrightOutput = resolve(root, 'test-results');
  if (isInside(playwrightOutput, output)) {
    throw new Error('V3 release evidence cannot be stored under Playwright test-results');
  }

  if (isInside(root, output) && !isInside(resolve(root, '.tmp'), output)) {
    throw new Error(
      'V3 release evidence inside the repository must be stored under the ignored .tmp directory',
    );
  }
  return output;
}
