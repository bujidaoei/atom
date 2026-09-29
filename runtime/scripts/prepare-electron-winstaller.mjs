import { access, copyFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

const require = createRequire(import.meta.url);
const packageRoot = dirname(require.resolve('electron-winstaller/package.json'));
const architecture = process.arch;
if (architecture !== 'x64' && architecture !== 'arm64') {
  throw new Error(`Unsupported electron-winstaller host architecture: ${architecture}`);
}

const vendor = join(packageRoot, 'vendor');
const sourceExecutable = join(vendor, `7z-${architecture}.exe`);
const sourceLibrary = join(vendor, `7z-${architecture}.dll`);
const targetExecutable = join(vendor, '7z.exe');
const targetLibrary = join(vendor, '7z.dll');

await Promise.all([access(sourceExecutable), access(sourceLibrary)]);
await Promise.all([copyFile(sourceExecutable, targetExecutable), copyFile(sourceLibrary, targetLibrary)]);

console.log(`Prepared electron-winstaller 7-Zip tools for ${architecture}`);
